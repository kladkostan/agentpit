import hashlib
import json
import logging
import secrets
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from eth_utils.crypto import keccak
from web3 import Web3

from agentpit.datastructures.cancel_orders_response import CancelOrdersResponse
from agentpit.datastructures.orderbook_summary import OrderBookLevel, OrderBookSummary
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.order_response import OrderResponse
from agentpit.datastructures.place_order_request import PlaceOrderRequest
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.domain.exceptions import (
    InsufficientBalanceError,
    MarketNotFoundError,
    MarketStateError,
    NotFoundError,
)
from agentpit.onchain.admin import OnchainAdmin
from agentpit.onchain.order_signer import OrderData, sign_order
from agentpit.onchain.user_wallet import send_admin_tx
from agentpit.datastructures.open_order import OpenOrder
from agentpit.polymarket.format import decimal_str_to_size_micro, price_to_decimal_str, price_to_float, size_to_decimal_str
from agentpit.polymarket.resolve import resolve_by_token_id

log = logging.getLogger(__name__)

_USDC_DECIMALS = 6
_USDC_SCALE = Decimal(10**_USDC_DECIMALS)
_PRICE_ONE = 10**_USDC_DECIMALS  # stored PRICE units that equal $1.00
_ZERO_ADDR = "0x0000000000000000000000000000000000000000"


class OrderService:
    """Place + match + settle the simple-trade flow.

    The orderbook is off-chain (the `orders` table). When two opposing orders
    cross, the operator (admin key) submits a `matchOrders` tx so settlement
    happens on-chain via the deployed CTFExchange.
    """

    def __init__(self, db: DbSession, onchain: OnchainAdmin):
        self._db = db
        self._onchain = onchain

    # --- public API -----------------------------------------------------

    def place_order(self, user: User, payload: PlaceOrderRequest) -> OrderResponse:
        token_id_int, _token_id_str = self._resolve_token(payload)
        size_micro = decimal_str_to_size_micro(str(payload.size))
        maker_amount, taker_amount = self._amounts_from_price_size(
            payload.side, payload.price, size_micro
        )

        # Pre-flight balance check — reject obvious losers before signing.
        self._check_balance(user.eth_address, payload.side, maker_amount, token_id_int)

        order = OrderData(
            salt=secrets.randbits(256),
            maker=user.eth_address,
            signer=user.eth_address,
            taker=_ZERO_ADDR,
            tokenId=token_id_int,
            makerAmount=maker_amount,
            takerAmount=taker_amount,
            expiration=int(payload.expiration),
            nonce=0,
            feeRateBps=0,
            side=0 if payload.side == "BUY" else 1,
            signatureType=0,
        )
        signature = sign_order(user.eth_key, self._onchain._client.deployment, order)

        order_id = self._compute_order_id(order)
        price_int = self._price_int(order)

        with self._db.write() as conn:
            self._insert_order(
                conn,
                api_key=user.api_key,
                order=order,
                order_id=order_id,
                signature=signature,
                price_int=price_int,
                order_type=payload.order_type,
            )
            taker_row = self._get_order_row(conn, order_id)
            matches = self._match(conn, taker_row, dry_run=False)

        tx_hashes: list[str] = []
        if matches:
            try:
                hashes = self._settle_on_chain(order, signature, matches)
                tx_hashes = ["0x" + h.hex() for h in hashes]
            except Exception as exc:
                log.exception("on-chain settlement failed for order %s", order_id)
                with self._db.write() as conn:
                    conn.execute(
                        "UPDATE trades SET STATUS = 'FAILED' "
                        "WHERE TAKER_ORDER_ID = %s",
                        (order_id,),
                    )
                failed_row = self._safe_row(order_id)
                return OrderResponse(
                    success=False,
                    orderID=order_id,
                    status=failed_row["STATUS"] if failed_row else "live",
                    errorMsg=f"settlement failed: {exc}",
                )

        with self._db.read() as conn:
            row = self._get_order_row(conn, order_id)
        # takingAmount/makingAmount come from the immediate match (taker's
        # perspective), in decimal strings (§4); "" when nothing filled.
        # The taker transacts at its OWN limit price for every fill (see
        # _taker_fill_amount) — true for NORMAL fills and for MINT/MERGE,
        # where taker and maker pay different prices summing to 1 — so the
        # taker's collateral is taker_price × filled, not the maker's price.
        filled_micro = sum(int(m["trade_size"]) for m in matches)
        collateral_micro = (price_int * filled_micro) // _PRICE_ONE
        if matches and payload.side == "BUY":
            making_amount = size_to_decimal_str(collateral_micro)  # USDC given
            taking_amount = size_to_decimal_str(filled_micro)      # shares received
        elif matches:  # SELL taker
            making_amount = size_to_decimal_str(filled_micro)      # shares given
            taking_amount = size_to_decimal_str(collateral_micro)  # USDC received
        else:
            making_amount = taking_amount = ""

        return OrderResponse(
            success=True,
            orderID=order_id,
            status=row["STATUS"],
            transactionsHashes=tx_hashes,
            takingAmount=taking_amount,
            makingAmount=making_amount,
            tradeIDs=[m["trade_id"] for m in matches],
        )

    def list_open_orders(
        self,
        user: User,
        *,
        market: str | None = None,
        asset_id: str | None = None,
        order_id: str | None = None,
    ) -> list[OpenOrder]:
        """Return the caller's live orders as Polymarket OpenOrder[] (§8.3)."""
        clauses = ["API_KEY = %s", "STATUS = 'live'"]
        params: list = [user.api_key]
        if asset_id is not None:
            clauses.append("TOKEN_ID = %s")
            params.append(asset_id)
        if order_id is not None:
            clauses.append("ORDER_ID = %s")
            params.append(order_id)
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT ORDER_ID, TOKEN_ID, SIDE, PRICE, REMAINING_AMOUNT, MAKER, "
                "MAKER_AMOUNT, TAKER_AMOUNT, CREATED_AT, EXPIRATION, ORDER_TYPE "
                f"FROM orders WHERE {' AND '.join(clauses)} "
                "ORDER BY CREATED_AT DESC",
                params,
            ).fetchall()
            out: list[OpenOrder] = []
            for r in rows:
                resolved = resolve_by_token_id(conn, r["TOKEN_ID"])
                if resolved is None:
                    continue
                if market is not None and resolved.condition_id != market:
                    continue
                # Original outcome-token size: BUY → takerAmount, SELL → makerAmount.
                original = int(
                    r["TAKER_AMOUNT"] if r["SIDE"] == "BUY" else r["MAKER_AMOUNT"]
                )
                matched = original - int(r["REMAINING_AMOUNT"])
                outcome_label = resolved.market.erc1155_tokens[
                    resolved.outcome_index
                ][1]
                out.append(
                    OpenOrder(
                        id=r["ORDER_ID"],
                        owner=user.user_id,
                        maker_address=r["MAKER"],
                        market=resolved.condition_id,
                        asset_id=r["TOKEN_ID"],
                        side=r["SIDE"],
                        original_size=size_to_decimal_str(original),
                        size_matched=size_to_decimal_str(matched),
                        price=price_to_decimal_str(int(r["PRICE"])),
                        outcome=outcome_label,
                        created_at=int(r["CREATED_AT"]),
                        expiration=str(r["EXPIRATION"]),
                        order_type=r["ORDER_TYPE"],
                    )
                )
        return out

    def cancel_orders(self, user: User, order_ids: list[str]) -> CancelOrdersResponse:
        """Cancel a set of the caller's live orders by id (§8.2)."""
        order_ids = list(dict.fromkeys(order_ids))  # dedup, preserve order (Polymarket ignores dupes)
        result = CancelOrdersResponse()
        with self._db.write() as conn:
            for order_id in order_ids:
                cur = conn.execute(
                    "UPDATE orders SET STATUS = 'cancelled' "
                    "WHERE ORDER_ID = %s AND API_KEY = %s AND STATUS = 'live'",
                    (order_id, user.api_key),
                )
                if cur.rowcount > 0:
                    result.canceled.append(order_id)
                else:
                    result.not_canceled[order_id] = (
                        "order not found, not yours, or not live"
                    )
        return result

    def cancel_all(self, user: User) -> CancelOrdersResponse:
        """Cancel every live order owned by the caller."""
        with self._db.read() as conn:
            ids = [
                r["ORDER_ID"]
                for r in conn.execute(
                    "SELECT ORDER_ID FROM orders "
                    "WHERE API_KEY = %s AND STATUS = 'live'",
                    (user.api_key,),
                ).fetchall()
            ]
        return self.cancel_orders(user, ids)

    def cancel_market_orders(
        self, user: User, market: str | None, asset_id: str | None
    ) -> CancelOrdersResponse:
        """Cancel the caller's live orders filtered by condition_id (`market`)
        and/or token_id (`asset_id`). With neither filter, cancels all."""
        clauses = ["API_KEY = %s", "STATUS = 'live'"]
        params: list = [user.api_key]
        if asset_id is not None:
            clauses.append("TOKEN_ID = %s")
            params.append(asset_id)
        if market is not None:
            # `market` is a condition_id; resolve it to the market's token ids.
            with self._db.read() as conn:
                m = TableRead.read_market_by_condition_id(conn, ConditionId(market))
            token_ids = [t for t, _label in m.erc1155_tokens] if m else ["\x00"]
            placeholders = ",".join("%s" for _ in token_ids)
            clauses.append(f"TOKEN_ID IN ({placeholders})")
            params.extend(token_ids)
        with self._db.read() as conn:
            ids = [
                r["ORDER_ID"]
                for r in conn.execute(
                    f"SELECT ORDER_ID FROM orders WHERE {' AND '.join(clauses)}",
                    params,
                ).fetchall()
            ]
        return self.cancel_orders(user, ids)

    def get_book(self, token_id: str) -> OrderBookSummary:
        """Aggregated order book for one outcome token (§8.5)."""
        with self._db.read() as conn:
            resolved = resolve_by_token_id(conn, token_id)
            if resolved is None:
                raise MarketNotFoundError(0)
            rows = conn.execute(
                "SELECT SIDE, PRICE, SUM(REMAINING_AMOUNT) AS SZ FROM orders "
                "WHERE TOKEN_ID = %s AND STATUS = 'live' GROUP BY SIDE, PRICE",
                (token_id,),
            ).fetchall()
            last = conn.execute(
                "SELECT PRICE FROM trades WHERE ASSET_ID = %s AND STATUS != 'FAILED' "
                "ORDER BY MATCH_TIME DESC LIMIT 1",
                (token_id,),
            ).fetchone()
        bids = sorted(
            (r for r in rows if r["SIDE"] == "BUY"),
            key=lambda r: -int(r["PRICE"]),
        )
        asks = sorted(
            (r for r in rows if r["SIDE"] == "SELL"),
            key=lambda r: int(r["PRICE"]),
        )

        def level(r) -> OrderBookLevel:
            return OrderBookLevel(
                price=price_to_decimal_str(int(r["PRICE"])),
                size=size_to_decimal_str(int(r["SZ"])),
            )

        bid_levels = [level(r) for r in bids]
        ask_levels = [level(r) for r in asks]
        last_trade_price = (
            price_to_decimal_str(int(last["PRICE"])) if last is not None else "0"
        )
        timestamp = str(int(datetime.now(timezone.utc).timestamp() * 1000))
        digest_src = "".join(
            f"{l.price}:{l.size}|" for l in (*bid_levels, *ask_levels)
        )
        book_hash = hashlib.sha1(digest_src.encode()).hexdigest()  # noqa: S324
        return OrderBookSummary(
            market=resolved.condition_id,
            asset_id=token_id,
            timestamp=timestamp,
            hash=book_hash,
            bids=bid_levels,
            asks=ask_levels,
            last_trade_price=last_trade_price,
        )

    def get_books(self, token_ids: list[str]) -> list[OrderBookSummary]:
        """Batch book read (§8.5). Skips unknown token ids."""
        out: list[OrderBookSummary] = []
        for token_id in token_ids:
            try:
                out.append(self.get_book(token_id))
            except MarketNotFoundError:
                continue
        return out

    _INTERVAL_HOURS = {
        "1h": 1, "6h": 6, "1d": 24, "1w": 168, "1m": 720, "max": 24 * 365 * 100,
    }

    def get_prices_history(
        self,
        token_id: str,
        *,
        start_ts: int | None = None,
        end_ts: int | None = None,
        interval: str = "1d",
        fidelity: int = 0,
    ) -> dict:
        """Trade-price history for one outcome token (§8.6).

        Returns ``{"history": [{"t": int_seconds, "p": float_0_1}]}`` ascending.
        `interval` selects a trailing window unless explicit start/end are given;
        `fidelity` (minutes) thins the series.
        """
        now = int(datetime.now(timezone.utc).timestamp())
        end = end_ts if end_ts is not None else now
        if start_ts is not None:
            start = start_ts
        else:
            hours = self._INTERVAL_HOURS.get(interval, 24)
            start = end - hours * 3600
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT MATCH_TIME, PRICE FROM trades "
                "WHERE ASSET_ID = %s AND STATUS != 'FAILED' "
                "AND MATCH_TIME >= %s AND MATCH_TIME <= %s "
                "ORDER BY MATCH_TIME ASC",
                (token_id, start, end),
            ).fetchall()
        points = [
            {"t": int(r["MATCH_TIME"]), "p": price_to_float(int(r["PRICE"]))}
            for r in rows
        ]
        # Optional fidelity thinning (minutes between kept points).
        if fidelity > 0 and points:
            step = fidelity * 60
            thinned = [points[0]]
            for pt in points[1:]:
                if pt["t"] - thinned[-1]["t"] >= step:
                    thinned.append(pt)
            if thinned[-1] is not points[-1]:
                thinned.append(points[-1])
            points = thinned
        return {"history": points}

    def _best_bid_ask(self, token_id: str) -> tuple[int | None, int | None]:
        """(best_bid_price_int, best_ask_price_int) from the live book."""
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT SIDE, PRICE FROM orders "
                "WHERE TOKEN_ID = %s AND STATUS = 'live'",
                (token_id,),
            ).fetchall()
        bids = [int(r["PRICE"]) for r in rows if r["SIDE"] == "BUY"]
        asks = [int(r["PRICE"]) for r in rows if r["SIDE"] == "SELL"]
        return (max(bids) if bids else None, min(asks) if asks else None)

    def get_midpoint(self, token_id: str) -> dict:
        best_bid, best_ask = self._best_bid_ask(token_id)
        if best_bid is None or best_ask is None:
            raise NotFoundError("no book for token")
        return {"mid": price_to_decimal_str((best_bid + best_ask) // 2)}

    def get_price(self, token_id: str, side: str) -> dict:
        best_bid, best_ask = self._best_bid_ask(token_id)
        chosen = best_ask if side == "BUY" else best_bid
        if chosen is None:
            raise NotFoundError("no resting orders on that side")
        return {"price": price_to_decimal_str(chosen)}

    def get_last_trade_price(self, token_id: str) -> dict:
        with self._db.read() as conn:
            row = conn.execute(
                "SELECT PRICE, SIDE FROM trades "
                "WHERE ASSET_ID = %s AND STATUS != 'FAILED' "
                "ORDER BY MATCH_TIME DESC LIMIT 1",
                (token_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError("no trades for token")
        return {"price": price_to_decimal_str(int(row["PRICE"])), "side": row["SIDE"]}

    # --- internals ------------------------------------------------------

    def _resolve_token(self, payload: PlaceOrderRequest) -> tuple[int, str]:
        """Resolve the order's canonical token_id to (token_id_int, token_id_str)."""
        with self._db.read() as conn:
            resolved = resolve_by_token_id(conn, payload.token_id)
        if resolved is None:
            raise MarketStateError(f"unknown token_id '{payload.token_id}'")
        return int(resolved.token_id), resolved.token_id

    def _safe_row(self, order_id: str):
        with self._db.read() as conn:
            try:
                return self._get_order_row(conn, order_id)
            except RuntimeError:
                return None

    @staticmethod
    def _amounts_from_price_size(
        side: str, price: Decimal, size: int
    ) -> tuple[int, int]:
        """Return (makerAmount, takerAmount) given order side, price, and outcome-token size.

        BUY: maker offers collateral (USDC) to receive outcome tokens.
            makerAmount = price * size, takerAmount = size.
        SELL: maker offers outcome tokens to receive collateral.
            makerAmount = size, takerAmount = price * size.
        """
        collateral = (Decimal(price) * Decimal(size)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        collateral_int = int(collateral)
        if side == "BUY":
            return collateral_int, int(size)
        return int(size), collateral_int

    def _check_balance(
        self, eth_address: str, side: str, maker_amount: int, token_id_int: int
    ) -> None:
        if side == "BUY":
            bal = self._onchain.usd_balance(eth_address)
            if bal < maker_amount:
                raise InsufficientBalanceError(f"need {maker_amount} apUSD, have {bal}")
        else:
            bal = self._onchain.ctf_balance(eth_address, token_id_int)
            if bal < maker_amount:
                raise InsufficientBalanceError(
                    f"need {maker_amount} outcome tokens, have {bal}"
                )

    def _insert_order(
        self,
        conn,
        *,
        api_key: str,
        order: OrderData,
        order_id: str,
        signature: bytes,
        price_int: int,
        order_type: str,
    ) -> None:
        order_json = json.dumps(self._signed_order_payload(order, signature))
        # REMAINING_AMOUNT is tracked in outcome-token units regardless of side
        # so the matching loop can compare BUY and SELL orders directly.
        # BUY: takerAmount = outcome qty. SELL: makerAmount = outcome qty.
        outcome_remaining = order.takerAmount if order.side == 0 else order.makerAmount
        conn.execute(
            """
            INSERT INTO orders (
                API_KEY, PRICE, POST_ONLY, ORDER_TYPE,
                SALT, MAKER, TAKER, SIGNER,
                TOKEN_ID, MAKER_AMOUNT, TAKER_AMOUNT,
                EXPIRATION, NONCE, FEE_RATE_BPS,
                SIDE, SIGNATURE_TYPE, SIGNATURE, ORDER_JSON,
                STATUS, REMAINING_AMOUNT, CREATED_AT, ORDER_ID
            ) VALUES (%s, %s, 0, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                api_key,
                price_int,
                order_type,
                str(order.salt),
                order.maker,
                order.taker,
                order.signer,
                str(order.tokenId),
                order.makerAmount,
                order.takerAmount,
                order.expiration,
                order.nonce,
                order.feeRateBps,
                "BUY" if order.side == 0 else "SELL",
                "EIP712",
                "0x" + signature.hex(),
                order_json,
                "live",
                outcome_remaining,
                int(datetime.now(timezone.utc).timestamp()),
                order_id,
            ),
        )

    @staticmethod
    def _signed_order_payload(order: OrderData, signature: bytes) -> dict:
        d = asdict(order)
        d["signature"] = "0x" + signature.hex()
        # JSON can't carry the 256-bit ints; stringify the big ones
        for big in ("salt", "tokenId", "makerAmount", "takerAmount"):
            d[big] = str(d[big])
        return d

    @staticmethod
    def _compute_order_id(order: OrderData) -> str:
        # Stable id derived from the signed fields. Not the EIP-712 hash; this
        # is purely an internal identifier.
        payload = json.dumps(
            {
                k: (str(v) if isinstance(v, int) else v)
                for k, v in asdict(order).items()
            },
            sort_keys=True,
        ).encode()
        return "0x" + keccak(payload).hex()

    @staticmethod
    def _price_int(order: OrderData) -> int:
        # price = collateral/asset scaled by 10^6.
        # For BUY: maker=collateral, taker=asset.
        maker = Decimal(order.makerAmount)
        taker = Decimal(order.takerAmount)
        if maker <= 0 or taker <= 0:
            raise ValueError("amounts must be positive")
        if order.side == 0:
            price = maker / taker
        else:
            price = taker / maker
        return int((price * _USDC_SCALE).to_integral_value(rounding=ROUND_HALF_UP))

    @staticmethod
    def _complement_token_id(conn, token_id: str) -> str | None:
        """Look up the binary-market complement of `token_id`, if one exists.

        Returns None when no two-outcome market contains this token (so the
        MINT/MERGE paths simply don't apply).
        """
        row = conn.execute(
            "SELECT ERC1155_TOKENS FROM markets WHERE ERC1155_TOKENS LIKE %s LIMIT 1",
            (f'%"{token_id}"%',),
        ).fetchone()
        if row is None:
            return None
        pairs = json.loads(row["ERC1155_TOKENS"])
        if len(pairs) != 2:
            return None
        a, b = pairs[0][0], pairs[1][0]
        if a == token_id:
            return b
        if b == token_id:
            return a
        return None

    @staticmethod
    def _get_order_row(conn, order_id: str):
        row = conn.execute(
            "SELECT * FROM orders WHERE ORDER_ID = %s LIMIT 1", (order_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError(f"order {order_id} not found post-insert")
        return row

    def _match(
        self, conn, taker_row, *, dry_run: bool
    ) -> list[dict]:
        """Match the taker order against resting orders.

        Considers two cross types:
        - NORMAL: same token, opposite side (existing book sweep).
        - MINT/MERGE: complementary token, same side, when prices satisfy
          the split/merge invariant ``p_taker + p_maker >= 1`` for MINT or
          ``<= 1`` for MERGE.

        Returns a list of match dicts with keys: maker_order_id, price,
        trade_size, maker_row, match_kind. Updates DB rows for both sides
        and inserts trade rows when not in dry_run.
        """
        taker_side = taker_row["SIDE"]
        taker_price = int(taker_row["PRICE"])
        token_id = taker_row["TOKEN_ID"]
        taker_remaining = int(taker_row["REMAINING_AMOUNT"])

        opposite = "SELL" if taker_side == "BUY" else "BUY"
        if taker_side == "BUY":
            sql = (
                "SELECT * FROM orders WHERE SIDE=%s AND STATUS='live' "
                "AND PRICE <= %s AND TOKEN_ID=%s AND ORDER_ID != %s"
            )
        else:
            sql = (
                "SELECT * FROM orders WHERE SIDE=%s AND STATUS='live' "
                "AND PRICE >= %s AND TOKEN_ID=%s AND ORDER_ID != %s"
            )
        same_token = conn.execute(
            sql, (opposite, taker_price, token_id, taker_row["ORDER_ID"])
        ).fetchall()
        same_token = sorted(
            same_token,
            key=lambda r: (
                (int(r["PRICE"]), int(r["CREATED_AT"]))
                if taker_side == "BUY"
                else (-int(r["PRICE"]), int(r["CREATED_AT"]))
            ),
        )
        tagged: list[tuple[str, Any]] = [("NORMAL", c) for c in same_token]

        complement_id = self._complement_token_id(conn, token_id)
        if complement_id is not None:
            threshold = _PRICE_ONE - taker_price
            if taker_side == "BUY":
                comp_sql = (
                    "SELECT * FROM orders WHERE SIDE='BUY' AND STATUS='live' "
                    "AND PRICE >= %s AND TOKEN_ID=%s AND ORDER_ID != %s"
                )
                kind = "MINT"
                # best maker = highest price (covers more of the mint cost).
                comp_key = lambda r: (-int(r["PRICE"]), int(r["CREATED_AT"]))
            else:
                comp_sql = (
                    "SELECT * FROM orders WHERE SIDE='SELL' AND STATUS='live' "
                    "AND PRICE <= %s AND TOKEN_ID=%s AND ORDER_ID != %s"
                )
                kind = "MERGE"
                # best maker = lowest ask (smallest cut of the merge proceeds).
                comp_key = lambda r: (int(r["PRICE"]), int(r["CREATED_AT"]))
            comp_rows = conn.execute(
                comp_sql, (threshold, complement_id, taker_row["ORDER_ID"])
            ).fetchall()
            tagged.extend((kind, r) for r in sorted(comp_rows, key=comp_key))

        matches: list[dict] = []
        for kind, maker in tagged:
            if taker_remaining <= 0:
                break
            maker_remaining = int(maker["REMAINING_AMOUNT"])
            if maker_remaining <= 0:
                continue
            trade_size = min(maker_remaining, taker_remaining)
            taker_remaining -= trade_size
            new_maker_remaining = maker_remaining - trade_size
            matches.append(
                {
                    "maker_row": maker,
                    "maker_order_id": maker["ORDER_ID"],
                    "price": int(maker["PRICE"]),
                    "trade_size": trade_size,
                    "new_maker_remaining": new_maker_remaining,
                    "match_kind": kind,
                }
            )

        if dry_run:
            return matches

        # Apply DB updates
        for m in matches:
            new_maker_remaining = m["new_maker_remaining"]
            new_status = "matched" if new_maker_remaining == 0 else "live"
            conn.execute(
                "UPDATE orders SET REMAINING_AMOUNT=%s, STATUS=%s WHERE ORDER_ID=%s",
                (new_maker_remaining, new_status, m["maker_order_id"]),
            )
            m["trade_id"] = self._insert_trade(conn, taker_row, m)

        new_taker_status = "matched" if taker_remaining == 0 else "live"
        conn.execute(
            "UPDATE orders SET REMAINING_AMOUNT=%s, STATUS=%s WHERE ORDER_ID=%s",
            (taker_remaining, new_taker_status, taker_row["ORDER_ID"]),
        )
        return matches

    @staticmethod
    def _insert_trade(
        conn, taker_row, match: dict
    ) -> str:
        trade_id = "{}-{}-{}".format(
            taker_row["ORDER_ID"], match["maker_order_id"], secrets.token_hex(8)
        )
        token_id = taker_row["TOKEN_ID"]
        resolved = resolve_by_token_id(conn, token_id)
        condition_id = resolved.condition_id if resolved else token_id
        outcome_label = (
            resolved.market.erc1155_tokens[resolved.outcome_index][1]
            if resolved else ""
        )
        maker_row = match["maker_row"]
        maker_user_id = TableRead.get_user_id_by_api_key(conn, maker_row["API_KEY"])
        maker_side = maker_row["SIDE"]
        maker_orders_payload = [
            {
                "order_id": match["maker_order_id"],
                "owner": maker_user_id or "",         # non-secret USER_ID (§13)
                "maker_address": maker_row["MAKER"],  # eth address
                "matched_amount": str(match["trade_size"]),
                "price": int(match["price"]),
                "fee_rate_bps": int(maker_row["FEE_RATE_BPS"]),
                "asset_id": token_id,
                "outcome": outcome_label,
                "side": maker_side,
            }
        ]
        conn.execute(
            """
            INSERT INTO trades (
                TRADE_ID, TAKER_ORDER_ID, MAKER_ORDERS, MARKET, ASSET_ID,
                PRICE, TRADE_SIZE, REMAINING_SIZE, SIDE, STATUS,
                MATCH_TIME, TRANSACTION_HASH, BUCKET_INDEX, FEE_RATE_BPS,
                TAKER_API_KEY, MAKER_API_KEY
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                trade_id,
                taker_row["ORDER_ID"],
                json.dumps(maker_orders_payload),
                condition_id,                 # MARKET = condition_id (§7 fix)
                token_id,                     # ASSET_ID = token_id
                match["price"],
                match["trade_size"],
                taker_row["REMAINING_AMOUNT"],
                taker_row["SIDE"],
                "PENDING",
                int(datetime.now(timezone.utc).timestamp()),
                "",
                0,
                int(taker_row["FEE_RATE_BPS"]),
                taker_row["API_KEY"],          # internal filter key (never serialized)
                maker_row["API_KEY"],          # internal filter key
            ),
        )
        return trade_id

    # --- on-chain settlement -------------------------------------------

    def _settle_on_chain(
        self, taker_order: OrderData, taker_signature: bytes, matches: list[dict]
    ) -> list[bytes]:
        """Submit `matchOrders` as the operator, one tx per match-kind group.

        Each call to CTFExchange.matchOrders resolves to a single MatchType
        derived from the taker/maker token pairing, so NORMAL fills cannot
        share a tx with MINT/MERGE fills. Returns one tx hash per group.
        """
        client = self._onchain._client  # noqa: SLF001
        exchange = self._onchain._contracts.exchange  # noqa: SLF001

        groups: dict[str, list[dict]] = {}
        for m in matches:
            groups.setdefault(m.get("match_kind", "NORMAL"), []).append(m)

        taker_solidity = self._to_solidity_order(taker_order, taker_signature)
        tx_hashes: list[bytes] = []
        for group in groups.values():
            maker_solidity_orders = []
            maker_fill_amounts = []
            taker_fill_amount = 0
            for m in group:
                maker_row = m["maker_row"]
                maker_signed = json.loads(maker_row["ORDER_JSON"])
                maker_order = OrderData(
                    salt=int(maker_signed["salt"]),
                    maker=maker_signed["maker"],
                    signer=maker_signed["signer"],
                    taker=maker_signed["taker"],
                    tokenId=int(maker_signed["tokenId"]),
                    makerAmount=int(maker_signed["makerAmount"]),
                    takerAmount=int(maker_signed["takerAmount"]),
                    expiration=int(maker_signed["expiration"]),
                    nonce=int(maker_signed["nonce"]),
                    feeRateBps=int(maker_signed["feeRateBps"]),
                    side=int(maker_signed["side"]),
                    signatureType=int(maker_signed["signatureType"]),
                )
                maker_sig = bytes.fromhex(maker_signed["signature"][2:])
                maker_solidity_orders.append(
                    self._to_solidity_order(maker_order, maker_sig)
                )
                # matchOrders expects fill amounts in each side's makerAsset units.
                maker_fill_amounts.append(
                    self._maker_fill_amount(maker_order, m["trade_size"])
                )
                taker_fill_amount += self._taker_fill_amount(
                    taker_order, m["trade_size"]
                )

            fn = exchange.functions.matchOrders(
                taker_solidity,
                maker_solidity_orders,
                taker_fill_amount,
                maker_fill_amounts,
            )
            receipt = send_admin_tx(client, fn, timeout=60)
            tx_hashes.append(receipt["transactionHash"])
        return tx_hashes

    @staticmethod
    def _to_solidity_order(order: OrderData, signature: bytes) -> tuple:
        return (
            order.salt,
            Web3.to_checksum_address(order.maker),
            Web3.to_checksum_address(order.signer),
            Web3.to_checksum_address(order.taker),
            order.tokenId,
            order.makerAmount,
            order.takerAmount,
            order.expiration,
            order.nonce,
            order.feeRateBps,
            order.side,
            order.signatureType,
            signature,
        )

    @staticmethod
    def _maker_fill_amount(maker: OrderData, trade_size: int) -> int:
        # `trade_size` is denominated in outcome-token units regardless of side.
        # For matchOrders, makerFillAmounts must be in the maker-asset units of
        # each maker order. SELL maker: makerAsset = outcome tokens → trade_size.
        # BUY maker: makerAsset = collateral → trade_size * price (rounded down).
        if maker.side == 1:  # SELL
            return trade_size
        # BUY maker
        ratio = Decimal(maker.makerAmount) / Decimal(maker.takerAmount)
        return int(
            (Decimal(trade_size) * ratio).to_integral_value(rounding=ROUND_HALF_UP)
        )

    @staticmethod
    def _taker_fill_amount(taker: OrderData, trade_size: int) -> int:
        # takerFillAmount is in the taker's makerAsset units.
        if taker.side == 0:  # BUY taker → makerAsset = collateral
            ratio = Decimal(taker.makerAmount) / Decimal(taker.takerAmount)
            return int(
                (Decimal(trade_size) * ratio).to_integral_value(rounding=ROUND_HALF_UP)
            )
        # SELL taker → makerAsset = outcome tokens
        return trade_size
