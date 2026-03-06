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

