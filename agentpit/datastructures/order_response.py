from dataclasses import dataclass
from typing import Optional

@dataclass(slots=True, init=False)
class OrderResponse:
    success: bool
    orderID: str
    status: str
    filledSize: str
    remainingSize: str
    avgPrice: Optional[str]
    errorMsg: Optional[str]

    def __init__(
        self,
        success: bool,
        orderID: str,
        status: str,
        filledSize: str,
        remainingSize: str,
        avgPrice: Optional[str],
        errorMsg: Optional[str],
    ) -> None:
        if not isinstance(success, bool):
            raise ValueError("success must be a bool")
        for name, value in {
            "orderID": orderID,
            "status": status,
            "filledSize": filledSize,
            "remainingSize": remainingSize,
        }.items():
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        if avgPrice is not None and (not isinstance(avgPrice, str) or not avgPrice):
            raise ValueError("avgPrice must be a non-empty string or None")
        if errorMsg is not None and (not isinstance(errorMsg, str) or not errorMsg):
            raise ValueError("errorMsg must be a non-empty string or None")
        self.success = success
        self.orderID = orderID
        self.status = status
        self.filledSize = filledSize
        self.remainingSize = remainingSize
        self.avgPrice = avgPrice
        self.errorMsg = errorMsg
