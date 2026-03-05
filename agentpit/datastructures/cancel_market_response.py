from pydantic import BaseModel


class CancelMarketResponse(BaseModel):
    market_id: int
    message: str
    refunds_processed: int

