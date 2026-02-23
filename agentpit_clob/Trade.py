from dataclasses import dataclass, asdict
from json import dumps
from typing import Any, Optional

@dataclass
class Trade:
    id: Optional[str] = None
    taker_order_id: Optional[str] = None
    maker_orders: Optional[list[dict[str, Any]]] = None
    market: Optional[str] = None
    asset_id: Optional[str] = None
    price: Optional[str] = None
    size: Optional[str] = None
    remaining_size: Optional[str] = None
    side: Optional[str] = None
    status: Optional[str] = None
    match_time: Optional[str] = None
    transaction_hash: Optional[str] = None
    bucket_index: Optional[int] = None
    fee_rate_bps: Optional[int] = None

    @property
    def __dict__(self):
        return asdict(self)

    @property
    def json(self):
        return dumps(self.__dict__)
