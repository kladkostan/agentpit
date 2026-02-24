from py_order_utils.model import SignedOrder
from py_clob_client import ClobClient, OrderType

import logging
import sqlite3
import json
from decimal import Decimal
from typing import Literal

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
        self.db.row_factory = sqlite3.Row

        # Explicit primary key and remaining_amount for partial fills
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS orders
            (
                id
                INTEGER
                PRIMARY
                KEY
                AUTOINCREMENT,
                api_key
                TEXT,
                price
                TEXT,
                post_only
                INTEGER,
                order_type
                TEXT,
                salt
                TEXT,
                maker
                TEXT,
                taker
                TEXT,
                signer
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
                TEXT,
                status
                TEXT
                DEFAULT
                'open',
                remaining_amount
                TEXT
            )
            """
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_price_side ON orders(price, side)"
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS trades
            (
                id
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
                TEXT,
                size
                TEXT,
                remaining_size
                TEXT,
                side
                TEXT,
                status
                TEXT,
                match_time
                TEXT,
                transaction_hash
                TEXT,
                bucket_index
                INTEGER,
                fee_rate_bps
                INTEGER
            )
            """
        )

    def process_new_order(self, signed_order: SignedOrder, order_type: OrderType, post_only: bool):
        taker_order_id = self.add_order_to_db(signed_order, order_type, post_only)

        # Run matching for this new taker order
        matches, remaining = self.match_order(taker_order_id)

        response = OrderResponse(
            success=True,
            orderID=str(taker_order_id),
            status="open" if remaining > 0 else "filled",
            filledSize=str(Decimal(signed_order.order.makerAmount) - remaining),
            remainingSize=str(remaining),
            avgPrice=None,
            errorMsg=None
        )
        return json.dumps(response.__dict__)

    def process_new_orders(self, args: list[PostOrdersArgs]) -> str:
        responses = []
        for arg in args:
            response_json = self.process_new_order(arg.order, arg.order_type, arg.post_only)
            response_dict = json.loads(response_json)
            responses.append(response_dict)
        return json.dumps(responses)

    def add_order_to_db(self, signed_order: SignedOrder, order_type: OrderType, post_only: bool) -> int:
        order = signed_order.order
        serialized_body = order_to_json(order, self.api_key, order_type, post_only)
        remaining_amount = str(order.makerAmount)
        price_u256 = str(order.price)

        with self.db:
            cursor = self.db.execute(
                """
                INSERT INTO orders (api_key, price, post_only, order_type,
                                    salt, maker, taker, signer, tokenId,
                                    makerAmount, takerAmount, expiration, nonce,
                                    feeRateBps, side, signatureType, order_json,
                                    status, remaining_amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.api_key,
                    price_u256,
                    int(post_only),
                    order_type.value,
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
                )
            )
            order_id = cursor.lastrowid
        return int(order_id)

    def is_price_acceptable(
            self,
            maker: sqlite3.Row,
            taker_side: Literal["BUY", "SELL"],
            taker_price: int
    ) -> bool:
        maker_price = int(str(maker["price"]))
        return maker_price <= taker_price if taker_side == "BUY" else maker_price >= taker_price

    def match_order(self, order_id: int):
        """
        Match a single taker order against the book.

        \- Respects price priority then time (id) priority.
        \- Supports partial fills via remaining_amount updates.
        """
        with self.db:
            taker = self.db.execute(
                """
                SELECT *
                FROM orders
                WHERE id = ?
                  AND status = 'open'
                """,
                (order_id,)
            ).fetchone()

            if not taker:
                return [], Decimal(0)

            taker_side = taker["side"]
            taker_price = int(str(taker["price"]))
            taker_remaining = Decimal(taker["remaining_amount"])

            opposite_side = "SELL" if taker_side == "BUY" else "BUY"

            candidates = self.db.execute(
                """
                SELECT *
                FROM orders
                WHERE side = ?
                  AND status = 'open'
                """,
                (opposite_side,)
            ).fetchall()

            filtered = [m for m in candidates if self.is_price_acceptable(m, taker_side, taker_price)]

            filtered.sort(
                key=lambda m: (int(str(m["price"])), m["id"]) if taker_side == "BUY"
                else (-int(str(m["price"])), m["id"])
            )

            matches = []
            for maker in filtered:
                if taker_remaining <= 0:
                    break

                maker_remaining = Decimal(maker["remaining_amount"])
                if maker_remaining <= 0:
                    continue

                trade_size = min(taker_remaining, maker_remaining)
                taker_remaining -= trade_size
                maker_remaining -= trade_size

                # Update maker order
                self.db.execute(
                    """
                    UPDATE orders
                    SET remaining_amount = ?,
                        status           = CASE WHEN ? = 0 THEN 'filled' ELSE 'open' END
                    WHERE id = ?
                    """,
                    (str(maker_remaining), maker_remaining, maker["id"])
                )

                matches.append(
                    {
                        "taker_order_id": order_id,
                        "maker_order_id": maker["id"],
                        "price": str(maker["price"]),
                        "size": str(trade_size),
                    }
                )

            # Update taker order
            self.db.execute(
                """
                UPDATE orders
                SET remaining_amount = ?,
                    status           = CASE WHEN ? = 0 THEN 'filled' ELSE 'open' END
                WHERE id = ?
                """,
                (str(taker_remaining), taker_remaining, order_id)
            )

        return matches, taker_remaining

    # Keep old name for compatibility, but now it runs matching
    def find_matching_orders(self, orderId: str):
        return self.match_order(int(orderId))
