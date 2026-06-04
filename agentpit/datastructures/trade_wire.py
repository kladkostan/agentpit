from pydantic import BaseModel, Field


class MakerOrderWire(BaseModel):
    order_id: str
    owner: str            # USER_ID
    maker_address: str
    matched_amount: str   # decimal shares
    price: str
    fee_rate_bps: str
    asset_id: str
    outcome: str
    side: str


class TradeWire(BaseModel):
    id: str
    taker_order_id: str
    market: str           # condition_id
    asset_id: str         # token_id
    side: str
    size: str             # decimal shares
    fee_rate_bps: str
    price: str
    status: str
    match_time: str       # unix seconds, stringified
    last_update: str
    outcome: str
    bucket_index: int
    owner: str            # USER_ID
    maker_address: str
    maker_orders: list[MakerOrderWire] = Field(default_factory=list)
    transaction_hash: str
    trader_side: str      # TAKER | MAKER


class TradesEnvelope(BaseModel):
    limit: int = 100
    count: int = 0
    next_cursor: str = "LTE="
    data: list[TradeWire] = Field(default_factory=list)
