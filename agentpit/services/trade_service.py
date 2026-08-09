import json

from agentpit.datastructures.match_leg import legs_for_user
from agentpit.datastructures.trade_wire import (
    MakerOrderWire,
    TradesEnvelope,
    TradeWire,
)
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.polymarket.format import price_to_decimal_str, size_to_decimal_str
from agentpit.polymarket.resolve import resolve_by_token_id


def _status(internal: str) -> str:
    # agentpit has PENDING (settled ok) and FAILED; map to Polymarket's
    # unprefixed forms. Non-failed fills are MATCHED.
    return "FAILED" if internal == "FAILED" else "MATCHED"


class TradeService:
    def __init__(self, db: DbSession):
        self._db = db

    def list_trades(self, user: User, *, limit: int = 100, **filters) -> TradesEnvelope:
        with self._db.read() as conn:
            rows = TableRead.list_trades_for_api_key(conn, user.api_key, **filters)
            trades = [
                TradeService._to_wire(
                    conn, r, api_key=user.api_key, user_id=user.user_id,
                    eth_address=user.eth_address,
                )
                for r in rows
            ]
        # next_cursor is the static "no more pages" sentinel ("LTE="): agentpit
        # returns all matching trades up to `limit` in one page (paper-rig
        # volumes are small). TODO: real cursor pagination if counts grow.
        page = trades[:limit]
        return TradesEnvelope(limit=limit, count=len(page), data=page)

    @staticmethod
    def _to_wire(
        conn, r, *, api_key: str, user_id: str, eth_address: str
    ) -> TradeWire:
        trader_side = "TAKER" if r["TAKER_API_KEY"] == api_key else "MAKER"
        legs = legs_for_user(r, api_key)
        leg = next(
            (x for x in legs if x.is_taker == (trader_side == "TAKER")), legs[0]
        )
        makers_raw = json.loads(r["MAKER_ORDERS"]) if r["MAKER_ORDERS"] else []
        maker_orders = [
            MakerOrderWire(
                order_id=m["order_id"],
                owner=m.get("owner", ""),               # counterparty USER_ID
                maker_address=m.get("maker_address", ""),
                matched_amount=size_to_decimal_str(int(m["matched_amount"])),
                price=price_to_decimal_str(int(m["price"])),
                fee_rate_bps=str(m.get("fee_rate_bps", 0)),
                asset_id=m.get("asset_id", r["ASSET_ID"]),
                outcome=m.get("outcome", ""),
                side=m.get("side", ""),
            )
            for m in makers_raw
        ]
        # The outcome label follows the token THIS leg moved. It used to come
        # from maker_orders[0] for both perspectives, which handed a MINT's
        # taker the complement's label.
        resolved = resolve_by_token_id(conn, leg.token_id)
        outcome = (
            resolved.market.erc1155_tokens[resolved.outcome_index][1]
            if resolved and resolved.market else ""
        )
        match_time = str(int(r["MATCH_TIME"]))
        return TradeWire(
            id=r["TRADE_ID"],
            taker_order_id=r["TAKER_ORDER_ID"],
            market=r["MARKET"],
            asset_id=leg.token_id,
            side=leg.side,
            size=size_to_decimal_str(int(r["TRADE_SIZE"])),
            fee_rate_bps=str(r["FEE_RATE_BPS"]),
            price=price_to_decimal_str(leg.price_micro),
            status=_status(r["STATUS"]),
            match_time=match_time,
            last_update=match_time,
            outcome=outcome,
            bucket_index=int(r["BUCKET_INDEX"]),
            owner=str(user_id),
            maker_address=eth_address,
            maker_orders=maker_orders,
            transaction_hash=r["TRANSACTION_HASH"] or "",
            trader_side=trader_side,
        )
