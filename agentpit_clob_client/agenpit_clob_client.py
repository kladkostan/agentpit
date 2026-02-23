from py_order_utils.model import Order

from py_clob_client import ClobClient, OrderType

import logging
import sqlite3

from py_clob_client.clob_types import PostOrdersArgs
from py_clob_client.utilities import order_to_json




class AgentPitClobClient:
    def __init__(
        self,
        api_key: str
    ):
        self.api_key = api_key
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db = sqlite3.connect('/tmp/x.db')
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
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

    def post_order(self, order : Order, order_type: OrderType, post_only: bool):
        serialized_body = order_to_json(order, self.api_key, order_type, post_only)
        self.db.execute(
            """
            INSERT INTO orders (
                api_key, price, post_only, order_type,
                salt, maker, signer, taker, tokenId,
                makerAmount, takerAmount, expiration, nonce,
                feeRateBps, side, signatureType, order_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.api_key,
                order.price,
                int(post_only),
                str(order_type),
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
        self.db.commit()

    def post_orders(self, args: list[PostOrdersArgs]):
        for arg in args:
            self.post_order(arg.order, arg.order_type, arg.post_only)
