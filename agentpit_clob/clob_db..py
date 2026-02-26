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
from dataclasses import dataclass


class ClobDB:
    def __init__(self, api_key: str, chain_id: int):
        self.api_key = api_key
        self.chain_id = chain_id
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db = sqlite3.connect('/tmp/x.db')
        self.db.row_factory = sqlite3.Row

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
                'open',
                remaining_amount
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

    def process_new_order(self, signed_order: SignedOrder, order_type: OrderType, post_only: bool):
        # use string order_id as the external order id
        taker_order_id = self.add_order_to_db(signed_order, order_type, post_only)

        matches: list[Match] = []
        if not post_only:
            matches, remaining = self.match_and_fill_order(taker_order_id)
        else:
            remaining = int(signed_order.order.makerAmount)

        total_requested = int(signed_order.order.makerAmount)
        filled = total_requested - remaining

        # compute volume‑weighted average price from matches
        total_spent = int(0)

        for m in matches:
            size = int(m.trade_size)
            price = int(m.price)
            total_spent += size * price

        avg_price: str | None
        if filled > 0:
            avg_price = str(Decimal(total_spent) / Decimal(filled))
        else:
            avg_price = None

        response = OrderResponse(
            success=True,
            orderID=taker_order_id,
            status="open" if remaining > 0 else "filled",
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

        order_id = self.compute_polymarket_compatible_order_id(order)

        # Normalize order_type from py_clob_client.OrderType to a plain string.
        order_type_str = self.order_type_as_str(order_type)

        side_str = self.side_as_str(order)

        with self.db:
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
                                    order_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.api_key,
                    self.get_price_int(order),
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
                    self.signature_type_as_str(order.signatureType),  # store as TEXT
                    serialized_body,
                    "open",
                    int(order.makerAmount),
                    order_id,
                ),
            )

        # always use order_id (hash) as canonical identifier
        return order_id

    def side_as_str(self, order: Order) -> str:
        side_int = int(order.side)
        if side_int == 0:
            side_str = "BUY"
        elif side_int == 1:
            side_str = "SELL"
        else:
            raise ValueError(f"Invalid order.side value: {order.side!r} (expected 0=BUY or 1=SELL)")
        return side_str

    def signature_type_as_str(self, signature_type: int | str) -> str:
        SIG_TYPE_MAP = {
            0: "EIP712",
            1: "ETHSIGN",
        }
        sig_type_int = int(signature_type)
        try:
            return SIG_TYPE_MAP[sig_type_int]
        except KeyError:
            raise ValueError(f"Unsupported signatureType: {sig_type_int}")

    def match_and_fill_order(self, order_id: str):
        with self.db:
            taker = self.get_existing_order(order_id)

            taker_side = taker["side"]  # string "BUY"/"SELL"
            taker_price = int(taker["price"])
            taker_remaining = int(taker["remaining_amount"])

            candidates = self.get_sorted_candidates(taker_side, taker_price)

            matches: list[Match] = []
            for maker in candidates:
                if taker_remaining <= 0:
                    break

                maker_remaining = int(maker["remaining_amount"])
                if maker_remaining <= 0:
                    continue

                match = self.fill_order(maker, maker_remaining, taker, taker_remaining)
                taker_remaining = taker_remaining - match.trade_size
                matches.append(match)

            # update taker by external order_id as well
            self.update_taker_remaining_in_db(taker["order_id"], taker_remaining)

        return matches, taker_remaining

    def sort_candidates(self, candidates: list[Any], taker_side: Literal["BUY", "SELL"]):
        # price is INTEGER in DB; avoid noisy int(str(...)) casts
        candidates.sort(
            key=lambda m: (int(m["price"]), m["order_id"]) if taker_side == "BUY"
            else (-int(m["price"]), m["order_id"])
        )

    def get_sorted_candidates(
            self,
            taker_side: Literal["BUY", "SELL"],
            taker_price: int,
    ) -> list[Any]:
        """
        Return maker orders on the opposite side that are price-acceptable
        for the given taker side and limit price.


        are done directly in SQL without CAST.
        """
        opposite_side = "SELL" if taker_side == "BUY" else "BUY"
        if taker_side == "BUY":
            sql = """
                  SELECT *
                  FROM orders
                  WHERE side = ?
                    AND status = 'open'
                    AND price <= ?
                  """
        else:
            sql = """
                  SELECT *
                  FROM orders
                  WHERE side = ?
                    AND status = 'open'
                    AND price >= ?
                  """

        candidates = self.db.execute(sql, (opposite_side, taker_price)).fetchall()
        self.sort_candidates(candidates, taker_side)
        return candidates

    def fill_order(self, maker, maker_remaining: int, taker, taker_remaining: int) -> Match:
        trade_size = min(taker_remaining, maker_remaining)
        taker_remaining -= trade_size
        maker_remaining -= trade_size

        self.update_maker_remaining_in_db(maker["order_id"], maker_remaining)

        self.insert_trade_row(
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

    def update_taker_remaining_in_db(self, order_id: str, taker_remaining: int):
        """
        Update remaining amount and status for the taker order by external order_id.
        """
        remaining_int = int(taker_remaining)
        self.db.execute(
            """
            UPDATE orders
            SET remaining_amount = ?,
                status           = CASE WHEN ? = 0 THEN 'filled' ELSE 'open' END
            WHERE order_id = ?
            """,
            (remaining_int, remaining_int, order_id)
        )

    def update_maker_remaining_in_db(self, order_id: str, maker_remaining: int):
        remaining_int = int(maker_remaining)
        self.db.execute(
            """
            UPDATE orders
            SET remaining_amount = ?,
                status           = CASE WHEN ? = 0 THEN 'filled' ELSE 'open' END
            WHERE order_id = ?
            """,
            (remaining_int, remaining_int, order_id)
        )

    # Keep old name for compatibility, but now it runs matching by external order_id
    def find_matching_orders(self, orderId: str):
        return self.match_and_fill_order(orderId)

    def compute_polymarket_compatible_order_id(self, order: Order) -> str:
        # Polymarket currently uses the auth domain for order hashes
        domain = get_clob_auth_domain(self.chain_id)
        signable = order.signable_bytes(domain)
        struct_hash = keccak(signable)
        return prepend_zx(struct_hash.hex())

    def insert_trade_row(
            self,
            taker_row: sqlite3.Row,
            maker_row: sqlite3.Row,
            trade_size: int,
            remaining_taker: int,
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

        price_int = maker_row["price"]
        trade_size_int = int(trade_size)
        remaining_int = int(remaining_taker)
        match_time_int = int(datetime.utcnow().timestamp() * 1000)

        trade = Trade(
            id=str(trade_id),
            taker_order_id=str(taker_row["order_id"]),
            maker_orders=maker_orders_payload,
            market=taker_row["tokenId"],
            asset_id=taker_row["tokenId"],
            price=price_int,
            trade_size=trade_size_int,
            remaining_size=remaining_int,
            side=taker_row["side"],  # string "BUY"/"SELL"
            match_time=match_time_int,
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


    def get_price_int(self, order: Order) -> int:

        USDC_DECIMALS = 6
        USDC_SCALE = 10 ** USDC_DECIMALS

        """
        Derive Polymarket limit price from order amounts and side, then
        convert to 6‑decimal integer for DB storage.

        BUY:  price = taker_amount / maker_amount
        SELL: price = maker_amount / taker_amount
        """
        maker_amount = Decimal(str(int(order.makerAmount)))
        taker_amount = Decimal(str(int(order.takerAmount)))

        if maker_amount <= 0 or taker_amount <= 0:
            raise ValueError("maker_amount and taker_amount must be positive")

        side_int = int(order.side)
        if side_int == 0:
            side = "BUY"
        elif side_int == 1:
            side = "SELL"
        else:
            raise ValueError(f"Invalid order.side value: {order.side!r} (expected 0=BUY or 1=SELL)")

        if side == "BUY":
            price_dec = taker_amount / maker_amount
        else:  # side == "SELL"
            price_dec = maker_amount / taker_amount

        scaled = price_dec * USDC_SCALE
        return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))


    def order_type_as_str(self, order_type: OrderType):
        if order_type == OrderType.GTC:
            return "GTC"
        elif order_type == OrderType.FOK:
            return "FOK"
        elif order_type == OrderType.GTD:
            return "GTD"
        elif order_type == OrderType.FAK:
            return "FAK"
        else:
            raise ValueError(f"Unsupported OrderType: {order_type}")

