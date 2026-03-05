
from enum import Enum

class MarketState(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    RESOLVING = "RESOLVING"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"
