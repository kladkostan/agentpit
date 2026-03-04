from dataclasses import dataclass
from typing import Optional
from pydantic import BaseModel, field_validator

class OrderResponse(BaseModel):
    success: bool
    orderID: str
    status: str
    filledSize: str
    remainingSize: str
    avgPrice: Optional[str]
    errorMsg: Optional[str]

    @field_validator("success")
    @classmethod
    def check_success(cls, v: bool) -> bool:
        if not isinstance(v, bool):
            raise ValueError("success must be a bool")
        return v

    @field_validator("orderID", "status", "filledSize", "remainingSize")
    @classmethod
    def check_required_str(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("must be a non-empty string")
        return v

    @field_validator("avgPrice", "errorMsg")
    @classmethod
    def check_optional_str(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and (not isinstance(v, str) or not v):
            raise ValueError("must be a non-empty string or None")
        return v
