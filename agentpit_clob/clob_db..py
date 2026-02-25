from py_order_utils.model import SignedOrder
from py_clob_client import OrderType

import logging
import sqlite3
import json
from decimal import Decimal
from typing import Literal, Any
from datetime import datetime

from py_clob_client.clob_types import PostOrdersArgs
from py_clob_client.utilities import order_to_json, price_valid
from agentpit_clob.order_response import OrderResponse
from agentpit_clob.trade import Trade

from eth_utils import keccak
from py_order_utils.utils import prepend_zx
from py_order_utils.model import Order
from py_clob_client.signing.eip712 import get_clob_auth_domain

class ClobDB:
    def __init__(self, api_key: str, chain_id: int):
        self.api_key = api_key
        self.chain_id = chain_id
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db = sqlite3.connect('/tmp/x.db')
        self.db.row_factory = sqlite3.Row

        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key TEXT,
                price TEXT,
                post_only INTEGER,
                order_type TEXT,
                salt TEXT,
                maker TEXT,
                taker TEXT,
                signer TEXT,
                tokenId TEXT,
                makerAmount TEXT,
                takerAmount TEXT,
                expiration TEXT,
                nonce TEXT,
                feeRateBps TEXT,
                side TEXT,
                signatureType TEXT,
                order_json TEXT,
                status TEXT DEFAULT 'open',
                remaining_amount TEXT,
                order_id TEXT NOT NULL UNIQUE
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
            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                taker_order_id TEXT,
                maker_orders TEXT,
                market TEXT,
                asset_id TEXT,
                price TEXT,
                trade_size TEXT,
                remaining_size TEXT,
                side TEXT,
                status TEXT,
                match_time TEXT,
                transaction_hash TEXT,
                bucket_index INTEGER,
                fee_rate_bps INTEGER
            )
            """
        )

    def process_new_order(self, signed_order: SignedOrder, order_type: OrderType, post_only: bool):
        # use string order_id as the external order id
        taker_order_id = self.add_order_to_db(signed_order, order_type, post_only)

        if not post_only:
            matches, remaining = self.match_and_fill_order(taker_order_id)
        else:
            remaining = Decimal(signed_order.order.makerAmount)

        response = OrderResponse(
            success=True,
            orderID=taker_order_id,
            status="open" if remaining > 0 else "filled",
            filledSize=str(Decimal(signed_order.order.makerAmount) - remaining),
            remainingSize=str(remaining),
            avgPrice=None,
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

    def add_order_to_db(self, signed_order: SignedOrder, order_type: OrderType, post_only: bool) -> str:
        order = signed_order.order
        tick_size = order.tickSize
        if not price_valid(float(order.price), tick_size):
            raise ValueError(f"Invalid price {order.price} for tick_size {tick_size}")

        order_type_str = str(order_type)
        remaining_amount = str(order.makerAmount)
        price_u256 = str(order.price)

        serialized_body = order_to_json(signed_order, self.api_key, order_type, post_only)

        # previously "order_hash"
        order_id = self.compute_polymarket_compatible_order_id(order)
        self.logger.debug(f"Computed order id: {order_id}")

        with self.db:
            self.db.execute(
                """
                INSERT INTO orders (api_key, price, post_only, order_type,
                                    salt, maker, taker, signer, tokenId,
                                    makerAmount, takerAmount, expiration, nonce,
                                    feeRateBps, side, signatureType, order_json,
                                    status, remaining_amount, order_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.api_key,
                    price_u256,
                    int(post_only),
                    order_type_str,
                    order.salt,
                    order.maker,
                    order.taker,
                    order.signer,
                    order.tokenId,
                    str(order.makerAmount),
                    str(order.takerAmount),
                    order.expiration,
                    order.nonce,
                    order.feeRateBps,
                    order.side,
                    order.signatureType,
                    serialized_body,
                    "open",
                    remaining_amount,
                    order_id,
                ),
            )
        # return canonical id: the order_id column
        return order_id

    def is_price_acceptable(
        self,
        maker: sqlite3.Row,
        taker_side: Literal["BUY", "SELL"],
        taker_price: int,
    ) -> bool:
        maker_price = int(str(maker["price"]))
        return maker_price <= taker_price if taker_side == "BUY" else maker_price >= taker_price

    def match_and_fill_order(self, order_id: str):
        """
        Match a single taker order against the book.

        order_id is the canonical external id; we resolve it to the row and
        then use the integer primary key (id) internally.
        """
        with self.db:
            taker = self.get_existing_order(order_id)

            taker_side = taker["side"]
            taker_price = int(str(taker["price"]))
            taker_remaining = Decimal(taker["remaining_amount"])

            candidates = self.get_sorted_candidates(taker_side, taker_price)

            matches: list[dict[str, Any]] = []
            for maker in candidates:
                if taker_remaining <= 0:
                    break

                maker_remaining = Decimal(maker["remaining_amount"])
                if maker_remaining <= 0:
                    continue

                trade_size = min(taker_remaining, maker_remaining)
                taker_remaining -= trade_size
                maker_remaining -= trade_size

                self.update_maker_remaining(maker, maker_remaining)

                match = {
                    "taker_order_id": taker["order_id"],
                    "maker_order_id": maker["order_id"],
                    "price": str(maker["price"]),
                    "size": str(trade_size),
                }
                matches.append(match)

                self._insert_trade_row(
                    taker_row=taker,
                    maker_row=maker,
                    trade_size=trade_size,
                    remaining_taker=taker_remaining,
                )

            self.update_taker_remaining(taker["id"], taker_remaining)

        return matches, taker_remaining

    def get_existing_order(self, order_id: str) -> Any:
        taker = self.db.execute(
            """
            SELECT *
            FROM orders
            WHERE order_id = ?
              AND status = 'open'
            """,
            (order_id,),
        ).fetchone()

        if not taker:
            raise RuntimeError(f"Taker order {order_id} not found or not open")
        return taker

    def sort_candidates(self, candidates: list[Any], taker_side: Literal["BUY", "SELL"]):
        candidates.sort(
            key=lambda m: (int(str(m["price"])), m["id"]) if taker_side == "BUY"
            else (-int(str(m["price"])), m["id"])
        )

    def get_sorted_candidates(
        self,
        taker_side: Literal["BUY", "SELL"],
        taker_price: int,
    ) -> list[Any]:
        """
        Return maker orders on the opposite side that are price-acceptable
        for the given taker side and limit price.

        Price is stored as TEXT but represents an integer, so we cast it
        to INTEGER in SQL for correct numeric comparison.
        """
        opposite_side = "SELL" if taker_side == "BUY" else "BUY"

        # BUY taker: maker_price <= taker_price
        # SELL taker: maker_price >= taker_price
        if taker_side == "BUY":
            sql = """
                  SELECT *
                  FROM orders
                  WHERE side = ?
                    AND status = 'open'
                    AND CAST(price AS INTEGER) <= ? \
                  """
        else:
            sql = """
                  SELECT *
                  FROM orders
                  WHERE side = ?
                    AND status = 'open'
                    AND CAST(price AS INTEGER) >= ? \
                  """

        candidates = self.db.execute(sql, (opposite_side, taker_price)).fetchall()
        self.sort_candidates(candidates, taker_side)
        return candidates

    def update_taker_remaining(self, order_pk: int, taker_remaining: Decimal):
        # order_id here is the internal integer primary key (orders.id)
        self.db.execute(
            """
            UPDATE orders
            SET remaining_amount = ?,
                status           = CASE WHEN ? = 0 THEN 'filled' ELSE 'open' END
            WHERE id = ?
            """,
            (str(taker_remaining), taker_remaining, order_pk)
        )

    def append_new_match(self, maker, matches: list[Any], order_id: str, trade_size: Decimal):
        matches.append(
            {
                "taker_order_id": order_id,
                "maker_order_id": maker["order_id"],
                "price": str(maker["price"]),
                "size": str(trade_size),
            }
        )

    def update_maker_remaining(self, maker, maker_remaining: Decimal):
        self.db.execute(
            """
            UPDATE orders
            SET remaining_amount = ?,
                status           = CASE WHEN ? = 0 THEN 'filled' ELSE 'open' END
            WHERE id = ?
            """,
            (str(maker_remaining), maker_remaining, maker["id"])
        )

    # Keep old name for compatibility, but now it runs matching by external order_id
    def find_matching_orders(self, orderId: str):
        return self.match_and_fill_order(orderId)

    def compute_polymarket_compatible_order_id(self, order: Order) -> str:
        """
        Compute the canonical EIP-712 order hash (chash) for a given CLOB Order.

        \- Uses the same EIP-712 encoding as signing: order.signable_bytes(domain).
        \- Returns a 0x-prefixed hex string.
        """
        # Build the EIP-712 domain used for orders on this chain
        domain = get_clob_auth_domain(self.chain_id)  # or get_clob_order_domain if available

        # Bytes that are signed for this order
        signable = order.signable_bytes(domain)

        # EIP-712 struct hash
        struct_hash = keccak(signable)

        # 0x-prefixed hex string
        return prepend_zx(struct_hash.hex())

    def _insert_trade_row(
        self,
        taker_row: sqlite3.Row,
        maker_row: sqlite3.Row,
        trade_size: Decimal,
        remaining_taker: Decimal,
    ) -> None:
        """
        Insert a single trade into the trades table.

        - maker_orders is stored as JSON; currently a single-maker array.
        - match_time is an ISO-8601 timestamp in UTC.
        - status is always 'CONFIRMED' for now.
        """
        trade_id = f"{taker_row['order_id']}-{maker_row['order_id']}-{datetime.utcnow().timestamp()}"
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
            price=str(maker_row["price"]),
            trade_size=str(trade_size),
            remaining_size=str(remaining_taker),
            side=taker_row["side"],
            match_time=datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            transaction_hash="",
            bucket_index=0,
            fee_rate_bps=int(taker_row["feeRateBps"]),
        )

        self.db.execute(
            """
            INSERT INTO trades (
                id,
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
                fee_rate_bps
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                trade.side,
                "CONFIRMED",
                trade.match_time,
                trade.transaction_hash,
                trade.bucket_index,
                trade.fee_rate_bps,
            ),
        )
