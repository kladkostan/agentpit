from pydantic import field_validator, BaseModel


class ResolveMarketRequest(BaseModel):
    winning_outcome_index: int

    @field_validator("winning_outcome_index")
    @classmethod
    def validate_winning_outcome_index(cls, v: int) -> int:
        if not isinstance(v, int) or v < 0:
            raise ValueError("must be a non-negative integer")
        return v
