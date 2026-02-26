from dataclasses import dataclass
from typing import Optional

@dataclass
class OrderResponse:
    success: bool
    orderID: str
    status: str
    filledSize: str
    remainingSize: str
    avgPrice: Optional[str]
    errorMsg: Optional[str]

