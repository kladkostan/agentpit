from pydantic import BaseModel


class RedeemPositionRequest(BaseModel):
    """Empty body — JWT identifies the user; market_id is in the URL."""

    pass
