import json
import logging
import secrets
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from eth_utils.crypto import keccak
from web3 import Web3

from agentpit.datastructures.cancel_orders_response import CancelOrdersResponse
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
)
from agentpit.onchain.admin import OnchainAdmin
from agentpit.onchain.order_signer import OrderData, sign_order
from agentpit.onchain.user_wallet import send_admin_tx
from agentpit.polymarket.format import decimal_str_to_size_micro, size_to_decimal_str
from agentpit.polymarket.resolve import resolve_by_market_outcome, resolve_by_token_id

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
                        "WHERE TAKER_ORDER_ID = ?",
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
        filled_micro = sum(int(m["trade_size"]) for m in matches)
        collateral_micro = sum(
            (int(m["price"]) * int(m["trade_size"])) // _PRICE_ONE for m in matches
        )
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

    def list_live_orders(self, user: User) -> list[dict[str, Any]]:
        with self._db.read() as conn:
            return TableRead.list_live_orders_for_api_key(conn, user.api_key)

    def cancel_orders(self, user: User, order_ids: list[str]) -> CancelOrdersResponse:
        """Cancel a set of the caller's live orders by id (§8.2)."""
        result = CancelOrdersResponse()
        with self._db.write() as conn:
            for order_id in order_ids:
                cur = conn.execute(
                    "UPDATE orders SET STATUS = 'cancelled' "
                    "WHERE ORDER_ID = ? AND API_KEY = ? AND STATUS = 'live'",
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
            conn.row_factory = sqlite3.Row
            ids = [
                r["ORDER_ID"]
                for r in conn.execute(
                    "SELECT ORDER_ID FROM orders "
                    "WHERE API_KEY = ? AND STATUS = 'live'",
                    (user.api_key,),
                ).fetchall()
            ]
        return self.cancel_orders(user, ids)

    def cancel_market_orders(
        self, user: User, market: str | None, asset_id: str | None
    ) -> CancelOrdersResponse:
        """Cancel the caller's live orders filtered by condition_id (`market`)
        and/or token_id (`asset_id`). With neither filter, cancels all."""
        clauses = ["API_KEY = ?", "STATUS = 'live'"]
        params: list = [user.api_key]
        if asset_id is not None:
            clauses.append("TOKEN_ID = ?")
            params.append(asset_id)
        if market is not None:
            # `market` is a condition_id; resolve it to the market's token ids.
            with self._db.read() as conn:
                m = TableRead.read_market_by_condition_id(conn, ConditionId(market))
            token_ids = [t for t, _label in m.erc1155_tokens] if m else ["\x00"]
            placeholders = ",".join("?" for _ in token_ids)
            clauses.append(f"TOKEN_ID IN ({placeholders})")
            params.extend(token_ids)
        with self._db.read() as conn:
            conn.row_factory = sqlite3.Row
            ids = [
                r["ORDER_ID"]
                for r in conn.execute(
                    f"SELECT ORDER_ID FROM orders WHERE {' AND '.join(clauses)}",
                    params,
                ).fetchall()
            ]
        return self.cancel_orders(user, ids)

    def get_orderbook(self, market_id: int, outcome: str) -> dict[str, Any]:
        _, _, token_id_str = self._resolve_market_lookup(market_id, outcome)
        with self._db.read() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT ORDER_ID, SIDE, PRICE, REMAINING_AMOUNT, MAKER, CREATED_AT "
                "FROM orders WHERE TOKEN_ID = ? AND STATUS = 'live'",
                (token_id_str,),
            )
            rows = [dict(r) for r in cur.fetchall()]
        bids = sorted(
            (r for r in rows if r["SIDE"] == "BUY"),
            key=lambda r: (-int(r["PRICE"]), int(r["CREATED_AT"])),
        )
        asks = sorted(
            (r for r in rows if r["SIDE"] == "SELL"),
            key=lambda r: (int(r["PRICE"]), int(r["CREATED_AT"])),
        )
        return {"market_id": market_id, "outcome": outcome, "bids": bids, "asks": asks}

    def get_sparkline(
        self, market_id: int, outcome: str, window_hours: int = 24
    ) -> dict[str, Any]:
        """Recent trade prices + window volume for a market+outcome.

        Returns at most 60 (time, price) points from the trailing
        `window_hours` window. Used by home-page cards to render a
        sparkline + the trailing-window % move and dollar volume.
        """
        _, _, token_id_str = self._resolve_market_lookup(market_id, outcome)
        now = int(datetime.now(timezone.utc).timestamp())
        since = now - max(1, window_hours) * 3600
        # Single query returns the windowed points and both the windowed
        # and all-time volume aggregates so the endpoint only hits SQLite
        # once per request.
        with self._db.read() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT MATCH_TIME, PRICE, TRADE_SIZE FROM trades "
                "WHERE ASSET_ID = ? AND STATUS != 'FAILED' "
                "ORDER BY MATCH_TIME ASC",
                (token_id_str,),
            ).fetchall()
        windowed = [r for r in rows if int(r["MATCH_TIME"]) >= since]
        points = [{"t": int(r["MATCH_TIME"]), "p": int(r["PRICE"])} for r in windowed]
        # Downsample if we have a lot of trades — keep the shape readable.
        max_points = 60
        if len(points) > max_points:
            stride = len(points) / max_points
            sampled = [points[int(i * stride)] for i in range(max_points)]
            if sampled[-1] != points[-1]:
                sampled[-1] = points[-1]
            points = sampled
        volume_micro_usd = sum(
            (int(r["PRICE"]) * int(r["TRADE_SIZE"])) // _PRICE_ONE for r in windowed
        )
        volume_total_micro_usd = sum(
            (int(r["PRICE"]) * int(r["TRADE_SIZE"])) // _PRICE_ONE for r in rows
        )
        return {
            "market_id": market_id,
            "outcome": outcome,
            "window_hours": window_hours,
            "points": points,
            "volume_micro_usd": int(volume_micro_usd),
            "volume_total_micro_usd": int(volume_total_micro_usd),
        }

    # --- internals ------------------------------------------------------

    def _resolve_token(self, payload: PlaceOrderRequest) -> tuple[int, str]:
        """Resolve the order's outcome to (token_id_int, token_id_str).

        `token_id` wins when present; `market_id`+`outcome` is the
        transitional fallback. If both are supplied and disagree, that's a
        conflicting request (400, via MarketStateError → BusinessRuleError).
        """
        with self._db.read() as conn:
            if payload.token_id is not None:
                resolved = resolve_by_token_id(conn, payload.token_id)
                if resolved is None:
                    raise MarketStateError(f"unknown token_id '{payload.token_id}'")
                if payload.market_id is not None and payload.outcome is not None:
                    alt = resolve_by_market_outcome(
                        conn, payload.market_id, payload.outcome
                    )
                    if alt.token_id != resolved.token_id:
                        raise MarketStateError(
                            "token_id conflicts with market_id/outcome"
                        )
                return int(resolved.token_id), resolved.token_id
            resolved = resolve_by_market_outcome(
                conn, payload.market_id, payload.outcome
            )
            return int(resolved.token_id), resolved.token_id

    def _safe_row(self, order_id: str):
        with self._db.read() as conn:
            try:
                return self._get_order_row(conn, order_id)
            except RuntimeError:
                return None

    def _resolve_market_lookup(self, market_id: int, outcome: str):
        with self._db.read() as conn:
            market = TableRead.read_market(conn, market_id)
        if market is None:
            raise MarketNotFoundError(market_id)
        for token_id_str, label in market.erc1155_tokens:
            if label.upper() == outcome.upper():
                return market, int(token_id_str), token_id_str
        raise MarketStateError(f"market {market_id} has no outcome '{outcome}'")

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
        conn: sqlite3.Connection,
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
            ) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    def _complement_token_id(conn: sqlite3.Connection, token_id: str) -> str | None:
        """Look up the binary-market complement of `token_id`, if one exists.

        Returns None when no two-outcome market contains this token (so the
        MINT/MERGE paths simply don't apply).
        """
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT ERC1155_TOKENS FROM markets WHERE ERC1155_TOKENS LIKE ? LIMIT 1",
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
    def _get_order_row(conn: sqlite3.Connection, order_id: str) -> sqlite3.Row:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM orders WHERE ORDER_ID = ? LIMIT 1", (order_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError(f"order {order_id} not found post-insert")
        return row

    def _match(
        self, conn: sqlite3.Connection, taker_row: sqlite3.Row, *, dry_run: bool
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
                "SELECT * FROM orders WHERE SIDE=? AND STATUS='live' "
                "AND PRICE <= ? AND TOKEN_ID=? AND ORDER_ID != ?"
            )
        else:
            sql = (
                "SELECT * FROM orders WHERE SIDE=? AND STATUS='live' "
                "AND PRICE >= ? AND TOKEN_ID=? AND ORDER_ID != ?"
            )
        conn.row_factory = sqlite3.Row
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
        tagged: list[tuple[str, sqlite3.Row]] = [("NORMAL", c) for c in same_token]

        complement_id = self._complement_token_id(conn, token_id)
        if complement_id is not None:
            threshold = _PRICE_ONE - taker_price
            if taker_side == "BUY":
                comp_sql = (
                    "SELECT * FROM orders WHERE SIDE='BUY' AND STATUS='live' "
                    "AND PRICE >= ? AND TOKEN_ID=? AND ORDER_ID != ?"
                )
                kind = "MINT"
                # best maker = highest price (covers more of the mint cost).
                comp_key = lambda r: (-int(r["PRICE"]), int(r["CREATED_AT"]))
            else:
                comp_sql = (
                    "SELECT * FROM orders WHERE SIDE='SELL' AND STATUS='live' "
                    "AND PRICE <= ? AND TOKEN_ID=? AND ORDER_ID != ?"
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
                "UPDATE orders SET REMAINING_AMOUNT=?, STATUS=? WHERE ORDER_ID=?",
                (new_maker_remaining, new_status, m["maker_order_id"]),
            )
            m["trade_id"] = self._insert_trade(conn, taker_row, m)

        new_taker_status = "matched" if taker_remaining == 0 else "live"
        conn.execute(
            "UPDATE orders SET REMAINING_AMOUNT=?, STATUS=? WHERE ORDER_ID=?",
            (taker_remaining, new_taker_status, taker_row["ORDER_ID"]),
        )
        return matches

    @staticmethod
    def _insert_trade(
        conn: sqlite3.Connection, taker_row: sqlite3.Row, match: dict
    ) -> str:
        trade_id = "{}-{}-{}".format(
            taker_row["ORDER_ID"], match["maker_order_id"], secrets.token_hex(8)
        )
        maker_orders_payload = [
            {
                "order_id": match["maker_order_id"],
                "owner": match["maker_row"]["MAKER"],
                "matched_amount": str(match["trade_size"]),
            }
        ]
        conn.execute(
            """
            INSERT INTO trades (
                TRADE_ID, TAKER_ORDER_ID, MAKER_ORDERS, MARKET, ASSET_ID,
                PRICE, TRADE_SIZE, REMAINING_SIZE, SIDE, STATUS,
                MATCH_TIME, TRANSACTION_HASH, BUCKET_INDEX, FEE_RATE_BPS
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id,
                taker_row["ORDER_ID"],
                json.dumps(maker_orders_payload),
                taker_row["TOKEN_ID"],
                taker_row["TOKEN_ID"],
                match["price"],
                match["trade_size"],
                taker_row["REMAINING_AMOUNT"],
                taker_row["SIDE"],
                "PENDING",
                int(datetime.now(timezone.utc).timestamp()),
                "",
                0,
                int(taker_row["FEE_RATE_BPS"]),
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
