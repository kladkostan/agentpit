class DomainError(Exception):
    """Base class for application-domain errors translated to HTTP responses."""


class NotFoundError(DomainError):
    pass


class AlreadyExistsError(DomainError):
    pass


class BusinessRuleError(DomainError):
    pass


class MarketNotFoundError(NotFoundError):
    def __init__(self, market_id: int):
        super().__init__("Market not found")
        self.market_id = market_id


class PersonalityNotFoundError(NotFoundError):
    def __init__(self, personality_id: str):
        super().__init__(f"Personality '{personality_id}' not found")
        self.personality_id = personality_id


class UserAlreadyExistsError(AlreadyExistsError):
    def __init__(self, user_id: str):
        super().__init__(f"User '{user_id}' already exists")
        self.user_id = user_id


class AgentAlreadyExistsError(AlreadyExistsError):
    def __init__(self, agent_id: str):
        super().__init__(f"Agent '{agent_id}' already exists")
        self.agent_id = agent_id


class InsufficientBalanceError(BusinessRuleError):
    pass


class InvalidPaginationError(BusinessRuleError):
    pass


class MarketStateError(BusinessRuleError):
    """Raised when an operation is invalid for the market's current state."""
