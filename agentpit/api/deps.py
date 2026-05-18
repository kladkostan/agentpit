from typing import Annotated

from fastapi import Depends

from agentpit.auth.jwt import JwtCoder
from agentpit.config import Settings
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.onchain.admin import OnchainAdmin
from agentpit.services.agent_service import AgentService
from agentpit.services.auth_service import AuthService
from agentpit.services.event_service import EventService
from agentpit.services.market_service import MarketService
from agentpit.services.order_service import OrderService
from agentpit.services.personality_service import PersonalityService
from agentpit.services.portfolio_service import PortfolioService
from agentpit.services.position_service import PositionService
from agentpit.services.usdc_service import UsdcService


# --- placeholders overridden by the app factory ---------------------------


def get_db_session() -> DbSession:
    raise RuntimeError("get_db_session has not been overridden by the app factory")


def get_settings() -> Settings:
    raise RuntimeError("get_settings has not been overridden by the app factory")


def get_jwt_coder() -> JwtCoder:
    raise RuntimeError("get_jwt_coder has not been overridden by the app factory")


def get_onchain_admin() -> OnchainAdmin:
    raise RuntimeError("get_onchain_admin has not been overridden by the app factory")


def get_current_user() -> User:
    raise RuntimeError("get_current_user has not been overridden by the app factory")


# --- common annotated types ----------------------------------------------

SessionDep = Annotated[DbSession, Depends(get_db_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
JwtCoderDep = Annotated[JwtCoder, Depends(get_jwt_coder)]
OnchainAdminDep = Annotated[OnchainAdmin, Depends(get_onchain_admin)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]


# --- service factories ---------------------------------------------------


def get_market_service(db: SessionDep, onchain: OnchainAdminDep) -> MarketService:
    return MarketService(db, onchain)


def get_event_service(db: SessionDep) -> EventService:
    return EventService(db)


def get_usdc_service(db: SessionDep, onchain: OnchainAdminDep) -> UsdcService:
    return UsdcService(db, onchain)


def get_position_service(db: SessionDep, onchain: OnchainAdminDep) -> PositionService:
    return PositionService(db, onchain)


def get_personality_service(db: SessionDep) -> PersonalityService:
    return PersonalityService(db)


def get_agent_service(db: SessionDep) -> AgentService:
    return AgentService(db)


def get_portfolio_service(db: SessionDep, onchain: OnchainAdminDep) -> PortfolioService:
    return PortfolioService(db, onchain)


def get_auth_service(
    db: SessionDep,
    coder: JwtCoderDep,
    onchain: OnchainAdminDep,
    settings: SettingsDep,
) -> AuthService:
    return AuthService(db, coder, onchain, settings)


def get_order_service(db: SessionDep, onchain: OnchainAdminDep) -> OrderService:
    return OrderService(db, onchain)


MarketServiceDep = Annotated[MarketService, Depends(get_market_service)]
EventServiceDep = Annotated[EventService, Depends(get_event_service)]
UsdcServiceDep = Annotated[UsdcService, Depends(get_usdc_service)]
PositionServiceDep = Annotated[PositionService, Depends(get_position_service)]
PersonalityServiceDep = Annotated[PersonalityService, Depends(get_personality_service)]
AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]
PortfolioServiceDep = Annotated[PortfolioService, Depends(get_portfolio_service)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
OrderServiceDep = Annotated[OrderService, Depends(get_order_service)]
