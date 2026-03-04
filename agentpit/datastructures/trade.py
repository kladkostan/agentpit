from dataclasses import asdict
from json import dumps
from typing import Any
from pydantic import BaseModel, field_validator

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

    @field_validator("id", "taker_order_id", "market", "asset_id", "transaction_hash")
    @classmethod
    def check_non_empty_str(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("must be a non-empty string")
        return v

    @field_validator("maker_orders")
    @classmethod
    def check_maker_orders(cls, v: Any) -> list[dict[str, Any]]:
        if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
            raise ValueError("maker_orders must be a list of dicts")
        return v

    @field_validator("price", "trade_size", "remaining_size", "match_time", "bucket_index", "fee_rate_bps")
    @classmethod
    def check_non_negative_int(cls, v: int) -> int:
        if not isinstance(v, int) or v < 0:
            raise ValueError("must be a non-negative int")
        return v

    @field_validator("side")
    @classmethod
    def check_side(cls, v: str) -> str:
        if v not in {"BUY", "SELL"}:
            raise ValueError('side must be "BUY" or "SELL"')
        return v

    @property
    def dict(self) -> dict[str, Any]:
        return self.model_dump()

    @property
    def json(self) -> str:
        return self.model_dump_json()
