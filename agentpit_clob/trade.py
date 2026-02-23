from dataclasses import dataclass, asdict
from json import dumps
from typing import Any

@dataclass
class Trade:
    id: str
    taker_order_id: str
    maker_orders: list[dict[str, Any]]
    market: str
    asset_id: str
    price: str
    size: str
    remaining_size: str
    side: str
    match_time: str
    transaction_hash: str
    bucket_index: int
    fee_rate_bps: int

    @property
    def __dict__(self):
        return asdict(self)

    @property
    def json(self):
        return dumps(self.__dict__)
