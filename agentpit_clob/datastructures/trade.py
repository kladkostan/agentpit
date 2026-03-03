from dataclasses import dataclass, asdict
from json import dumps
from typing import Any

@dataclass(slots=True, init=False)
class Trade:
    id: str
    taker_order_id: str
    maker_orders: list[dict[str, Any]]
    market: str
    asset_id: str
    price: int
    trade_size: int
    remaining_size: int
    side: str          # "BUY" or "SELL"
    match_time: int
    transaction_hash: str
    bucket_index: int
    fee_rate_bps: int

    def __init__(
        self,
        id: str,
        taker_order_id: str,
        maker_orders: list[dict[str, Any]],
        market: str,
        asset_id: str,
        price: int,
        trade_size: int,
        remaining_size: int,
        side: str,
        match_time: int,
        transaction_hash: str,
        bucket_index: int,
        fee_rate_bps: int,
    ) -> None:
        for name, value in {
            "id": id,
            "taker_order_id": taker_order_id,
            "market": market,
            "asset_id": asset_id,
            "transaction_hash": transaction_hash,
        }.items():
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(maker_orders, list) or not all(isinstance(x, dict) for x in maker_orders):
            raise ValueError("maker_orders must be a list of dicts")
        for name, value in {
            "price": price,
            "trade_size": trade_size,
            "remaining_size": remaining_size,
            "match_time": match_time,
            "bucket_index": bucket_index,
            "fee_rate_bps": fee_rate_bps,
        }.items():
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative int")
        if side not in {"BUY", "SELL"}:
            raise ValueError('side must be "BUY" or "SELL"')
        self.id = id
        self.taker_order_id = taker_order_id
        self.maker_orders = maker_orders
        self.market = market
        self.asset_id = asset_id
        self.price = price
        self.trade_size = trade_size
        self.remaining_size = remaining_size
        self.side = side
        self.match_time = match_time
        self.transaction_hash = transaction_hash
        self.bucket_index = bucket_index
        self.fee_rate_bps = fee_rate_bps

    @property
    def dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def json(self) -> str:
        return dumps(self.dict)
