from py_order_utils.model import Order

from py_clob_client import ClobClient, OrderType

import logging
import sqlite3

from py_clob_client.clob_types import PostOrdersArgs
from py_clob_client.utilities import order_to_json


class ClobDB:
    def __init__(
            self,
            api_key: str
    ):
        self.api_key = api_key
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db = sqlite3.connect('/tmp/x.db')
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS orders
            (
                api_key
                TEXT,
                price
                REAL,
                post_only
                INTEGER,
                order_type
                TEXT,
                salt
                TEXT,
                maker
                TEXT,
                signer
                TEXT,
                taker
                TEXT,
                tokenId
                TEXT,
                makerAmount
                TEXT,
                takerAmount
                TEXT,
                expiration
                TEXT,
                nonce
                TEXT,
                feeRateBps
                TEXT,
                side
                TEXT,
                signatureType
                TEXT,
                order_json
                TEXT
            )
            """
        )

    def save_order(self, order: Order, order_type: OrderType, post_only: bool):
        serialized_body = order_to_json(order, self.api_key, order_type, post_only)
        with self.db:
            self.db.execute(
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

    def save_orders(self, args: list[PostOrdersArgs]) -> None:
        # Insert all orders in a single transaction using executemany
        rows = []
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

        if not rows:
            return

        with self.db:  # begins a transaction and commits on success
            self.db.executemany(
                """
                INSERT INTO orders (api_key, price, post_only, order_type,
                                    salt, maker, signer, taker, tokenId,
                                    makerAmount, takerAmount, expiration, nonce,
                                    feeRateBps, side, signatureType, order_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
