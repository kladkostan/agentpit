from pydantic import BaseModel


class ResolveMarketRequest(BaseModel):
    winning_outcome_index: int

