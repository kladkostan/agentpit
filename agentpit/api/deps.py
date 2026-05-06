from typing import Annotated

from fastapi import Depends

from agentpit.db.session import DbSession
from agentpit.services.agent_service import AgentService
from agentpit.services.market_service import MarketService
from agentpit.services.personality_service import PersonalityService
from agentpit.services.portfolio_service import PortfolioService
from agentpit.services.position_service import PositionService
from agentpit.services.usdc_service import UsdcService
from agentpit.services.user_service import UserService


def get_db_session() -> DbSession:
    """Placeholder dependency. The app factory overrides this with the real session."""
    raise RuntimeError("get_db_session has not been overridden by the app factory")


SessionDep = Annotated[DbSession, Depends(get_db_session)]


def get_market_service(db: SessionDep) -> MarketService:
    return MarketService(db)


def get_usdc_service(db: SessionDep) -> UsdcService:
    return UsdcService(db)


def get_position_service(db: SessionDep) -> PositionService:
    return PositionService(db)


def get_user_service(db: SessionDep) -> UserService:
    return UserService(db)


def get_personality_service(db: SessionDep) -> PersonalityService:
    return PersonalityService(db)


def get_agent_service(db: SessionDep) -> AgentService:
    return AgentService(db)


def get_portfolio_service(db: SessionDep) -> PortfolioService:
    return PortfolioService(db)


MarketServiceDep = Annotated[MarketService, Depends(get_market_service)]
UsdcServiceDep = Annotated[UsdcService, Depends(get_usdc_service)]
PositionServiceDep = Annotated[PositionService, Depends(get_position_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
PersonalityServiceDep = Annotated[PersonalityService, Depends(get_personality_service)]
AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]
PortfolioServiceDep = Annotated[PortfolioService, Depends(get_portfolio_service)]
