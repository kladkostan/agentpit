
from enum import StrEnum

class MarketState(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    RESOLVING = "RESOLVING"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"
