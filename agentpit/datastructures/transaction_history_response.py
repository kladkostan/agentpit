from pydantic import BaseModel
from typing import List, Dict, Any
from agentpit.common import check_state

class Transaction(BaseModel):
    """Represents a single transaction in a user's history."""
    transaction_id: int
    timestamp: str
    transaction_type: str
    market_id: int
    details: Dict[str, Any]

    def model_post_init(self, __context):
        check_state(self.transaction_id >= 0, "Transaction ID must be non-negative")
        check_state(len(self.timestamp) > 0, "Timestamp must not be empty")
        check_state(len(self.transaction_type) > 0, "Transaction type must not be empty")
        check_state(self.market_id >= 0, "Market ID must be non-negative")

class TransactionHistoryResponse(BaseModel):
    """Response model for a user's transaction history."""
    eth_address: str
    transactions: List[Transaction]

    def model_post_init(self, __context):
        check_state(len(self.eth_address) > 0, "ETH address must not be empty")
        check_state(self.transactions is not None, "Transactions list must not be None")
