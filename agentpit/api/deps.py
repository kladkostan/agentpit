from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from agentpit.auth.jwt import JwtCoder
from agentpit.config import Settings
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.onchain.admin import OnchainAdmin
from agentpit.services.account_service import AccountService
from agentpit.services.agent_service import AgentService
from agentpit.services.auth_service import AuthService
from agentpit.services.balance_service import BalanceService
from agentpit.services.event_service import EventService
from agentpit.services.leaderboard_service import LeaderboardService
from agentpit.services.market_service import MarketService
from agentpit.services.order_service import OrderService
from agentpit.services.personality_service import PersonalityService
from agentpit.services.position_service import PositionService
from agentpit.services.trade_service import TradeService
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


# --- auth guards -----------------------------------------------------------


def require_admin_token(
    settings: SettingsDep,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    """Operator gate: X-Admin-Token header must match Settings.admin_token."""
    if x_admin_token is None or x_admin_token != settings.admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="admin token missing or invalid",
        )


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


def get_auth_service(
    db: SessionDep,
    coder: JwtCoderDep,
    onchain: OnchainAdminDep,
    settings: SettingsDep,
) -> AuthService:
    return AuthService(db, coder, onchain, settings)


def get_order_service(db: SessionDep, onchain: OnchainAdminDep) -> OrderService:
    return OrderService(db, onchain)


def get_trade_service(db: SessionDep) -> TradeService:
    return TradeService(db)


def get_account_service(db: SessionDep, onchain: OnchainAdminDep) -> AccountService:
    return AccountService(db, onchain)


AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]


def get_balance_service(
    db: SessionDep,
    onchain: OnchainAdminDep,
    settings: SettingsDep,
    accounts: AccountServiceDep,
) -> BalanceService:
    return BalanceService(db, onchain, settings, accounts)


def get_leaderboard_service(
    db: SessionDep,
    onchain: OnchainAdminDep,
    accounts: AccountServiceDep,
    settings: SettingsDep,
) -> LeaderboardService:
    return LeaderboardService(db, onchain, accounts, settings)


LeaderboardServiceDep = Annotated[
    LeaderboardService, Depends(get_leaderboard_service)
]


BalanceServiceDep = Annotated[BalanceService, Depends(get_balance_service)]
MarketServiceDep = Annotated[MarketService, Depends(get_market_service)]
EventServiceDep = Annotated[EventService, Depends(get_event_service)]
UsdcServiceDep = Annotated[UsdcService, Depends(get_usdc_service)]
PositionServiceDep = Annotated[PositionService, Depends(get_position_service)]
PersonalityServiceDep = Annotated[PersonalityService, Depends(get_personality_service)]
AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
OrderServiceDep = Annotated[OrderService, Depends(get_order_service)]
TradeServiceDep = Annotated[TradeService, Depends(get_trade_service)]
