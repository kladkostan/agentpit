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
                signer TEXT,
                taker TEXT,
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

    def create_order(self, order: Order, order_type: OrderType, post_only: bool):
        serialized_body = order_to_json(order, self.api_key, order_type, post_only)
        with self.db:
            cursor = self.db.execute(
                """
                INSERT INTO orders (api_key, price, post_only, order_type,
                                    salt, maker, signer, taker, tokenId,
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
                    order.signer,
                    order.taker,
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
        # Prepare rows and keep a parallel list of orders for response building
        rows = []
        orders_for_response: list[Order] = []
        for arg in args:
            order = arg.order
            serialized_body = order_to_json(order, self.api_key, arg.order_type, arg.post_only)
            rows.append(
                (
                    self.api_key,
                    order.price,
                    int(arg.post_only),
                    arg.order_type.value,
                    order.salt,
                    order.maker,
                    order.signer,
                    order.taker,
                    order.tokenId,
                    order.makerAmount,
                    order.takerAmount,
                    order.expiration,
                    order.nonce,
                    order.feeRateBps,
                    order.side,
                    order.signatureType,
                    serialized_body,
                )
            )
            orders_for_response.append(order)

        if not rows:
            return json.dumps([])

        responses: list[OrderResponse] = []

        # Insert each row and collect rowid in a single transaction
        with self.db:
            insert_sql = """
                INSERT INTO orders (api_key, price, post_only, order_type,
                                    salt, maker, signer, taker, tokenId,
                                    makerAmount, takerAmount, expiration, nonce,
                                    feeRateBps, side, signatureType, order_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            for row, order in zip(rows, orders_for_response):
                cursor = self.db.execute(insert_sql, row)
                order_id = cursor.lastrowid
                responses.append(
                    OrderResponse(
                        success=True,
                        orderID=str(order_id),
                        status="open",
                        filledSize="0",
                        remainingSize=str(order.makerAmount),
                        avgPrice=None,
                        errorMsg=None,
                    )
                )

        # Return JSON array of responses
        return json.dumps([r.__dict__ for r in responses])
