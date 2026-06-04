import json

from agentpit.datastructures.trade_wire import (
    MakerOrderWire,
    TradesEnvelope,
    TradeWire,
)
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.polymarket.format import price_to_decimal_str, size_to_decimal_str


def _status(internal: str) -> str:
    # agentpit has PENDING (settled ok) and FAILED; map to Polymarket's
    # unprefixed forms. Non-failed fills are MATCHED.
    return "FAILED" if internal == "FAILED" else "MATCHED"


class TradeService:
    def __init__(self, db: DbSession):
        self._db = db

    def list_trades(self, user: User, **filters) -> TradesEnvelope:
        with self._db.read() as conn:
            rows = TableRead.list_trades_for_api_key(conn, user.api_key, **filters)
        trades: list[TradeWire] = []
        for r in rows:
            trader_side = "TAKER" if r["TAKER_API_KEY"] == user.api_key else "MAKER"
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
            # Perspective: TAKER → taker's side/owner; MAKER → the maker leg.
            if trader_side == "TAKER":
                side = r["SIDE"]
                owner = user.user_id
                maker_address = user.eth_address
                outcome = maker_orders[0].outcome if maker_orders else ""
            else:
                leg = maker_orders[0] if maker_orders else None
                side = leg.side if leg else r["SIDE"]
                owner = user.user_id
                maker_address = user.eth_address
                outcome = leg.outcome if leg else ""
            match_time = str(int(r["MATCH_TIME"]))
            trades.append(
                TradeWire(
                    id=r["TRADE_ID"],
                    taker_order_id=r["TAKER_ORDER_ID"],
                    market=r["MARKET"],
                    asset_id=r["ASSET_ID"],
                    side=side,
                    size=size_to_decimal_str(int(r["TRADE_SIZE"])),
                    fee_rate_bps=str(r["FEE_RATE_BPS"]),
                    price=price_to_decimal_str(int(r["PRICE"])),
                    status=_status(r["STATUS"]),
                    match_time=match_time,
                    last_update=match_time,
                    outcome=outcome,
                    bucket_index=int(r["BUCKET_INDEX"]),
                    owner=owner,
                    maker_address=maker_address,
                    maker_orders=maker_orders,
                    transaction_hash=r["TRANSACTION_HASH"] or "",
                    trader_side=trader_side,
                )
            )
        return TradesEnvelope(count=len(trades), data=trades)
