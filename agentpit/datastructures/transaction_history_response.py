from pydantic import BaseModel
from typing import List, Dict, Any

class Transaction(BaseModel):
    """Represents a single transaction in a user's history."""
    transaction_id: int
    timestamp: str
    transaction_type: str
    market_id: int
    details: Dict[str, Any]

class TransactionHistoryResponse(BaseModel):
    """Response model for a user's transaction history."""
    eth_address: str
    transactions: List[Transaction]

