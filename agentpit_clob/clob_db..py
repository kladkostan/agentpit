import threading

from py_order_utils.model import SignedOrder, Order
from py_clob_client import OrderType

import logging
import sqlite3
import json

from typing import Literal, Any
from datetime import datetime

from py_clob_client.clob_types import PostOrdersArgs
from agentpit_clob.order_response import OrderResponse
from agentpit_clob.trade import Trade

from eth_utils import keccak
from py_order_utils.utils import prepend_zx
from py_clob_client.signing.eip712 import get_clob_auth_domain
from decimal import Decimal, ROUND_HALF_UP

from agentpit_clob.match import Match

from py_clob_client.utilities import order_to_json
from enum import Enum
import uuid
from pathlib import Path

ORDER_TYPE_GTC = "GTC"
ORDER_TYPE_GTD = "GTD"
ORDER_TYPE_FOK = "FOK"
ORDER_TYPE_FAK = "FAK"


class OrderStatus(str, Enum):
    LIVE = "live"
    MATCHED = "matched"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ClobDB:
    def __init__(self, api_key: str, chain_id: int, full_path: Path):
        self.api_key = api_key
        self.chain_id = chain_id
        self.logger = logging.getLogger(self.__class__.__name__)

        # Initialize lock before DB operations
        self._lock = threading.Lock()

        # sqlite3 accepts Path objects directly
        self.db = sqlite3.connect(full_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row

        with self._lock:
            with self.db:
                self.create_orders_table()
                self.create_trades_table()

    def create_trades_table(self):
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS trades
            (
                trade_id
                TEXT
                PRIMARY
                KEY,
                taker_order_id
                TEXT,
                maker_orders
                TEXT,
                market
                TEXT,
                asset_id
                TEXT,
                price
                INTEGER,
                trade_size
                INTEGER,
                remaining_size
                INTEGER,
                side
                TEXT,
                status
                TEXT,
                match_time
                INTEGER,
                transaction_hash
                TEXT,
                bucket_index
                INTEGER,
                fee_rate_bps
                INTEGER
            )
            """
        )

    def create_orders_table(self):
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS orders
            (
                api_key
                TEXT,
                price
                INTEGER,
                post_only
                INTEGER,
                order_type
                TEXT,
                salt
                INTEGER,
                maker
                TEXT,
                taker
                TEXT,
                signer
                TEXT,
                tokenId
                TEXT,
                maker_amount
                INTEGER,
                taker_amount
                INTEGER,
                expiration
                INTEGER,
                nonce
                INTEGER,
                fee_rate_bps
                INTEGER,
                side
                TEXT,
                signature_type
                TEXT,
                order_json
                TEXT,
                status
                TEXT
                DEFAULT
                'live',
                remaining_amount
                INTEGER,
                created_at
                INTEGER,
                order_id
                TEXT
                NOT
                NULL
                UNIQUE
            )
            """
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_price_side ON orders(price, side)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_order_id ON orders(order_id)"
        )
        self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_orders_order_type_status_expiration
                ON orders(order_type, status, expiration)
            """
        )
        self.db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_orders_status_expiration
                ON orders(status, expiration)
            """
        )

    def process_new_order(self, signed_order: SignedOrder, order_type: OrderType, post_only: bool):

        _processed = self._process_expired_orders()

        matches: list[Match] = []
        total_spent = int(0)
        status = OrderStatus.LIVE
        with self._lock:
            with self.db:
                taker_order_id = self.add_order_to_db(signed_order, order_type, post_only)

                cancel_fok = False
                if (order_type == OrderType.FOK):
                    # For FOK  cancel if not fully filled.
                    # Do a dry run
                    dry_run_spent, dry_run_remaining, dry_run_status = self._match_and_fill_order(taker_order_id, True)
                    if dry_run_remaining > 0:
                        # Cancel the order by setting its status to CANCELLED
                        self.set_order_status(taker_order_id, OrderStatus.CANCELLED)
                        cancel_fok = True
                if not post_only and not cancel_fok:
                    total_spent, remaining, status = self._match_and_fill_order(taker_order_id)
                else:
                    remaining = int(signed_order.order.makerAmount)

        total_requested = int(signed_order.order.makerAmount)
        filled = total_requested - remaining

        # compute volume‑weighted average price from matches

        for m in matches:
            size = int(m.trade_size)
            price = int(m.price)
            total_spent += size * price

        avg_price: str | None
        if filled > 0:
            avg_price = str(Decimal(total_spent) / (Decimal(filled)) * Decimal(10 ** 6))
        else:
            avg_price = None

        response = OrderResponse(
            success=True,
            orderID=taker_order_id,
            status=status,
            filledSize=str(filled),
            remainingSize=str(remaining),
            avgPrice=avg_price,
            errorMsg=None,
        )
        return json.dumps(response.__dict__)

    def process_new_orders(self, args: list[PostOrdersArgs]) -> str:
        responses = []
        for arg in args:
            # PostOrdersArgs uses orderType/postOnly (camelCase)
            response_json = self.process_new_order(arg.order, arg.orderType, arg.postOnly)
            response_dict = json.loads(response_json)
            responses.append(response_dict)
        return json.dumps(responses)

    def add_order_to_db(
            self,
            signed_order: SignedOrder,
            order_type: OrderType,
            post_only: bool,
    ) -> str:

        order = signed_order.order

        serialized_body = order_to_json(
            signed_order,
            self.api_key,
            order_type,
            post_only,
        )

        order_id = self._compute_polymarket_compatible_order_id(order)
        order_type_str = self._order_type_as_str(order_type)
        side_str = self._side_as_str(order)

        # Capture creation time
        created_at = int(datetime.utcnow().timestamp())

        self.db.execute(
            """
            INSERT INTO orders (api_key,
                                price,
                                post_only,
                                order_type,
                                salt,
                                maker,
                                taker,
                                signer,
                                tokenId,
                                maker_amount,
                                taker_amount,
                                expiration,
                                nonce,
                                fee_rate_bps,
                                side,
                                signature_type,
                                order_json,
                                status,
                                remaining_amount,
                                created_at,
                                order_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.api_key,
                self._get_price_int(order),
                int(post_only),
                order_type_str,
                int(order.salt),
                order.maker,
                order.taker,
                order.signer,
                order.tokenId,
                int(order.makerAmount),
                int(order.takerAmount),
                int(order.expiration),
                int(order.nonce),
                int(order.feeRateBps),
                side_str,
                self._signature_type_as_str(order.signatureType),
                serialized_body,
                OrderStatus.LIVE,
                int(order.makerAmount),
                created_at,
                order_id,
            ),
        )

        return order_id

    def _side_as_str(self, order: Order) -> str:
        side_int = int(order.side)
        if side_int == 0:
            side_str = "BUY"
        elif side_int == 1:
            side_str = "SELL"
        else:
            raise ValueError(f"Invalid order.side value: {order.side!r} (expected 0=BUY or 1=SELL)")
        return side_str

    def _signature_type_as_str(self, signature_type: int | str) -> str:
        SIG_TYPE_MAP = {
            0: "EIP712",
            1: "ETHSIGN",
            2: "EOA"
        }
        sig_type_int = int(signature_type)
        try:
            return SIG_TYPE_MAP[sig_type_int]
        except KeyError:
            raise ValueError(f"Unsupported signatureType: {sig_type_int}")

    def _match_and_fill_order(self, order_id: str, dry_run: bool = False) -> tuple[int, int, str]:
        taker = self._get_existing_order(order_id)

        taker_side = taker["side"]  # string "BUY"/"SELL"
        taker_price = int(taker["price"])
        taker_remaining = int(taker["remaining_amount"])

        candidates = self._get_sorted_candidates(taker_side, taker_price)

        matches: list[Match] = []
        for maker in candidates:
            if taker_remaining <= 0:
                break

            maker_remaining = int(maker["remaining_amount"])
            if maker_remaining <= 0:
                continue

            match = self._fill_order(maker, maker_remaining, taker, taker_remaining)
            taker_remaining = taker_remaining - match.trade_size
            matches.append(match)

        total_spent = int(0)
        for m in matches:
            size = int(m.trade_size)
            price = int(m.price)
            total_spent += size * price

        # update taker by external order_id as well
        if not dry_run:
            self._update_taker_remaining_in_db(taker["order_id"], taker_remaining)
            self.set_order_type_to_cancelled_if_order_is_fak_and_order_status_is_live(order_id)

        status = self.get_order_status(order_id)

        return total_spent, taker_remaining, status

    def get_order_status(self, order_id: str, status) -> Any:
        row = self.db.execute(
            "SELECT status FROM orders WHERE order_id = ?",
            (order_id,)
        ).fetchone()
        status = row["status"]
        return status

    def _sort_candidates(self, candidates: list[Any], taker_side: Literal["BUY", "SELL"]):
        """
        Sorts candidates for Price-Time priority.
        1. Price:
           - Taker BUY (wants SELLs): Lowest price first (Ascending).
           - Taker SELL (wants BUYs): Highest price first (Descending).
        2. Time (created_at):
           - Oldest orders first (Ascending) for both sides.
        """
        candidates.sort(
            key=lambda m: (int(m["price"]), int(m["created_at"])) if taker_side == "BUY"
            else (-int(m["price"]), int(m["created_at"]))
        )

    def _get_sorted_candidates(
            self,
            taker_side: Literal["BUY", "SELL"],
            taker_price: int,
    ) -> list[Any]:
        """
        Return maker orders on the opposite side that are price-acceptable
        for the given taker side and limit price.
        """
        opposite_side = "SELL" if taker_side == "BUY" else "BUY"

        # Taker BUY matches with SELLS having price <= taker_price
        if taker_side == "BUY":
            sql = """
                  SELECT *
                  FROM orders
                  WHERE side = ?
                    AND status = ?
                    AND price <= ?
                  """
        # Taker SELL matches with BUYS having price >= taker_price
        else:
            sql = """
                  SELECT *
                  FROM orders
                  WHERE side = ?
                    AND status = ?
                    AND price >= ?
                  """

        # Execute query. Note: We use OrderStatus.LIVE explicitly.
        candidates = self.db.execute(
            sql,
            (opposite_side, OrderStatus.LIVE, taker_price)
        ).fetchall()

        self._sort_candidates(candidates, taker_side)
        return candidates

    def _fill_order(self, maker, maker_remaining: int, taker, taker_remaining: int, dry_run: bool = False) -> Match:
        trade_size = min(taker_remaining, maker_remaining)
        taker_remaining -= trade_size
        maker_remaining -= trade_size

        if not dry_run:
            self._update_maker_remaining_in_db(maker["order_id"], maker_remaining)

            self._insert_trade_row(
                taker_row=taker,
                maker_row=maker,
                trade_size=trade_size,
                remaining_taker=taker_remaining,
            )

        match = Match(
            taker_order_id=taker["order_id"],
            maker_order_id=maker["order_id"],
            price=int(maker["price"]),
            trade_size=int(trade_size),
        )
        return match

    def _get_existing_order(self, order_id: str) -> Any:
        taker = self.db.execute(
            """
            SELECT *
            FROM orders
            WHERE order_id = ?
              AND status = ?
            """,
            (order_id, OrderStatus.LIVE),
        ).fetchone()

        if not taker:
            raise RuntimeError(f"Taker order {order_id} not found or not live")
        return taker

    def _update_taker_remaining_in_db(self, order_id: str, taker_remaining: int):
        """
        Update remaining amount and status for the taker order by external order_id.
        """
        remaining_int = int(taker_remaining)
        self.db.execute(
            """
            UPDATE orders
            SET remaining_amount = ?,
                status           = CASE WHEN ? = 0 THEN ? ELSE ? END
            WHERE order_id = ?
            """,
            (remaining_int, remaining_int, OrderStatus.MATCHED, OrderStatus.LIVE, order_id)
        )

    def _update_maker_remaining_in_db(self, order_id: str, maker_remaining: int):
        remaining_int = int(maker_remaining)
        self.db.execute(
            """
            UPDATE orders
            SET remaining_amount = ?,
                status           = CASE WHEN ? = 0 THEN ? ELSE ? END
            WHERE order_id = ?
            """,
            (remaining_int, remaining_int, OrderStatus.MATCHED, OrderStatus.LIVE, order_id)
        )

    def _compute_polymarket_compatible_order_id(self, order: Order) -> str:
        # Polymarket currently uses the auth domain for order hashes
        domain = get_clob_auth_domain(self.chain_id)
        signable = order.signable_bytes(domain)
        struct_hash = keccak(signable)
        return prepend_zx(struct_hash.hex())

    def _insert_trade_row(
            self,
            taker_row: sqlite3.Row,
            maker_row: sqlite3.Row,
            trade_size: int,
            remaining_taker: int,
    ) -> None:
        """
        Insert a single trade into the trades table.

        - maker_orders is stored as JSON; currently a single-maker array.
        - status is always 'CONFIRMED' for now.
        """

        trade_id = (
            f"{taker_row['order_id']}-"
            f"{maker_row['order_id']}-"
            f"{uuid.uuid4()}"
        )

        maker_orders_payload = [
            {
                "order_id": maker_row["order_id"],
                "owner": maker_row["maker"],
                "matched_amount": str(trade_size),
            }
        ]

        trade = Trade(
            id=str(trade_id),
            taker_order_id=str(taker_row["order_id"]),
            maker_orders=maker_orders_payload,
            market=taker_row["tokenId"],
            asset_id=taker_row["tokenId"],
            price=maker_row["price"],
            trade_size=int(trade_size),
            remaining_size=int(remaining_taker),
            side=taker_row["side"],  # string "BUY"/"SELL"
            match_time=int(datetime.utcnow().timestamp()),
            transaction_hash="",
            bucket_index=0,
            fee_rate_bps=int(taker_row["fee_rate_bps"]),
        )
        self.db.execute(
            """
            INSERT INTO trades (trade_id,
                                taker_order_id,
                                maker_orders,
                                market,
                                asset_id,
                                price,
                                trade_size,
                                remaining_size,
                                side,
                                status,
                                match_time,
                                transaction_hash,
                                bucket_index,
                                fee_rate_bps)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.id,
                trade.taker_order_id,
                json.dumps(trade.maker_orders),
                trade.market,
                trade.asset_id,
                trade.price,
                trade.trade_size,
                trade.remaining_size,
                trade.side,  # TEXT in DB
                "CONFIRMED",
                trade.match_time,
                trade.transaction_hash,
                trade.bucket_index,
                trade.fee_rate_bps,
            ),
        )

    def _get_price_int(self, order: Order) -> int:
        USDC_DECIMALS = 6
        USDC_SCALE = Decimal(10 ** USDC_DECIMALS)

        maker_amount = Decimal(str(int(order.makerAmount)))
        taker_amount = Decimal(str(int(order.takerAmount)))

        if maker_amount <= 0 or taker_amount <= 0:
            raise ValueError("maker_amount and taker_amount must be positive")

        side_int = int(order.side)

        # 0 = BUY: Maker gives Collateral (makerAmount), receives Asset (takerAmount)
        if side_int == 0:
            # Price = Collateral / Asset
            price_dec = maker_amount / taker_amount

        # 1 = SELL: Maker gives Asset (makerAmount), receives Collateral (takerAmount)
        elif side_int == 1:
            # Price = Collateral / Asset
            price_dec = taker_amount / maker_amount

        else:
            raise ValueError(f"Invalid order.side value: {order.side!r}")

        scaled = price_dec * USDC_SCALE
        return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))

    def _order_type_as_str(self, order_type: OrderType) -> str:
        if order_type == OrderType.GTC:
            return ORDER_TYPE_GTC
        elif order_type == OrderType.FOK:
            return ORDER_TYPE_FOK
        elif order_type == OrderType.GTD:
            return ORDER_TYPE_GTD
        elif order_type == OrderType.FAK:
            return ORDER_TYPE_FAK
        else:
            raise ValueError(f"Unsupported OrderType: {order_type}")

    def _process_expired_orders(self) -> int:
        """
        Move all GTD orders that are currently 'live' and whose expiration
        timestamp is in the past to status 'expired'.
        """
        now = int(datetime.utcnow().timestamp())
        with self._lock:
            with self.db:
                cur = self.db.execute(
                    """
                    UPDATE orders
                    SET status = ?
                    WHERE order_type = ?
                      AND status = ?
                      AND expiration <= ?
                    """,
                    (
                        OrderStatus.EXPIRED,
                        ORDER_TYPE_GTD,
                        OrderStatus.LIVE,
                        now
                    ),
                )
                return cur.rowcount

    def set_order_status(self, order_id: str, status: OrderStatus):
        with self._lock:
            with self.db:
                self.db.execute(
                    """
                    UPDATE orders
                    SET status = ?
                    WHERE order_id = ?
                    """,
                    (status, order_id)
                )

    def set_order_type_to_cancelled_if_order_is_fak_and_order_status_is_live(self, order_id: str):
        with self._lock:
            with self.db:
                self.db.execute(
                    """
                    UPDATE orders
                    SET status = ?
                    WHERE order_id = ?
                      AND order_type = ?
                      AND status = ?
                    """,
                    (OrderStatus.CANCELLED, order_id, ORDER_TYPE_FAK, OrderStatus.LIVE)
                )
