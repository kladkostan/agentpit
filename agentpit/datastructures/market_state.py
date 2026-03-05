
from enum import Enum

class MarketState(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RESOLVING = "RESOLVING"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"
