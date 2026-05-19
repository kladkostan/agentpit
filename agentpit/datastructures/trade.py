from dataclasses import asdict
from json import dumps
from typing import Any
from pydantic import BaseModel, field_validator


def check_state(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


class Trade(BaseModel):
    id: str
    taker_order_id: str
    maker_orders: list[dict[str, Any]]
    market: str
    asset_id: str
    price: int
    trade_size: int
    remaining_size: int
    side: str
    match_time: int
    transaction_hash: str
    bucket_index: int
    fee_rate_bps: int

    @property
    def dict(self) -> dict[str, Any]:
        return self.model_dump()

    @property
    def json(self) -> str:
        return self.model_dump_json()

    def model_post_init(self, __context):
        check_state(len(self.maker_orders) > 0, "Maker orders must not be empty")
