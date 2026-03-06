from pydantic import field_validator, BaseModel


class SplitPositionRequest(BaseModel):
    api_key: str
    amount: int  # number of complete sets to split
