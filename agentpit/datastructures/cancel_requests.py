from pydantic import BaseModel, Field


class CancelOrderRequest(BaseModel):
    """Body for `DELETE /order`."""

    orderID: str = Field(min_length=1)


class CancelMarketOrdersRequest(BaseModel):
    """Body for `DELETE /cancel-market-orders` (both filters optional)."""

    market: str | None = None      # condition_id
    asset_id: str | None = None    # token_id
