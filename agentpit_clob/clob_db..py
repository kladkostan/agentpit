from py_order_utils.model import Order

from py_clob_client import ClobClient, OrderType

import logging
import sqlite3
import json

from py_clob_client.clob_types import PostOrdersArgs
from py_clob_client.utilities import order_to_json
from agentpit_clob.order_response import OrderResponse


class ClobDB:
    def __init__(
            self,
            api_key: str
    ):
        self.api_key = api_key
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db = sqlite3.connect('/tmp/x.db')
        # Explicit integer primary key for stable order IDs
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS orders
            (
                api_key TEXT,
                price REAL,
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
                order_json TEXT
            )
            """
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_price ON orders(price)"
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS trades
            (
                id TEXT PRIMARY KEY,
                taker_order_id TEXT,
                maker_orders TEXT, -- JSON array
                market TEXT,
                asset_id TEXT,
                price TEXT,
                size TEXT,
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

    def create_order(self, order: Order, order_type: OrderType, post_only: bool):
        serialized_body = order_to_json(order, self.api_key, order_type, post_only)
        order_id = self.add_order_to_db(order, order_type, post_only, serialized_body)

        response = OrderResponse(
                success=True,
                orderID=str(order_id),
                status="open",
                filledSize="0",
                remainingSize=str(order.makerAmount),
                avgPrice=None,
                errorMsg=None
            )
        return json.dumps(response.__dict__)

    def create_orders(self, args: list[PostOrdersArgs]) -> str:
        responses = []
        for arg in args:
            response_json = self.create_order(arg.order, arg.order_type, arg.post_only)
            response_dict = json.loads(response_json)
            responses.append(response_dict)
        return json.dumps(responses)

    def add_order_to_db(self, order: Order, order_type: OrderType, post_only: bool, serialized_body: dict) -> int | None:
        with self.db:
            cursor = self.db.execute(
                """
                INSERT INTO orders (api_key, price, post_only, order_type,
                                    salt, maker, taker, signer, tokenId,
                                    makerAmount, takerAmount, expiration, nonce,
                                    feeRateBps, side, signatureType, order_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.api_key,
                    order.price,
                    int(post_only),
                    order_type.value,
                    order.salt,
                    order.maker,
                    order.taker,
                    order.signer,
                    order.tokenId,
                    order.makerAmount,
                    order.takerAmount,
                    order.expiration,
                    order.nonce,
                    order.feeRateBps,
                    order.side,
                    order.signatureType,
                    serialized_body
                )
            )
            order_id = cursor.lastrowid
        return order_id

    def find_matching_orders(self, orderId: str):
        with self.db:
            row = self.db.execute(
                "SELECT price, order_type, side FROM orders WHERE rowid = ?",
                (orderId,)
            ).fetchone()
            if not row:
                return []
            price, order_type, side = row
            opposite_side = "SELL" if side == "BUY" else "BUY"

            if order_type == "MARKET":
                cursor = self.db.execute(
                    """
                    SELECT * FROM orders
                    WHERE side = ? AND rowid != ?
                    ORDER BY price ASC
                    """,
                    (opposite_side, orderId)
                )
            elif order_type in ("GTC", "GTD", "FAK", "FOK"):
                if side == "BUY":
                    cursor = self.db.execute(
                        """
                        SELECT * FROM orders
                        WHERE side = ? AND price <= ? AND rowid != ?
                        ORDER BY price ASC
                        """,
                        (opposite_side, price, orderId)
                    )
                else:
                    cursor = self.db.execute(
                        """
                        SELECT * FROM orders
                        WHERE side = ? AND price >= ? AND rowid != ?
                        ORDER BY price DESC
                        """,
                        (opposite_side, price, orderId)
                    )
            else:
                return []
            matching_orders = cursor.fetchall()
        return matching_orders
