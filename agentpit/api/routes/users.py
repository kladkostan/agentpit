import time

import psycopg.errors

from fastapi import APIRouter
from pydantic import BaseModel

from agentpit.api.deps import (
    AuthServiceDep,
    BalanceServiceDep,
    CurrentUserDep,
    SessionDep,
)
from agentpit.datastructures.auth_response import UserPublic
from agentpit.datastructures.change_password_request import ChangePasswordRequest
from agentpit.datastructures.update_handle_request import UpdateHandleRequest
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.domain.exceptions import HandleAlreadyExistsError

router = APIRouter(tags=["users"])


class TopUpStatusWire(BaseModel):
    nextAllowedAt: int


class TopUpWire(BaseModel):
    balance: str
    minted: str
    nextAllowedAt: int


@router.get("/me", response_model=UserPublic)
def get_me(user: CurrentUserDep) -> UserPublic:
    return UserPublic.model_validate(user.model_dump())


@router.patch("/me", response_model=UserPublic)
def update_me_handle(
    payload: UpdateHandleRequest,
    user: CurrentUserDep,
    db: SessionDep,
) -> UserPublic:
    try:
        with db.write() as conn:
            updated = TableWrite.update_user_handle(conn, user.user_id, payload.handle)
        if not updated:
            return UserPublic.model_validate(user.model_dump())
    except psycopg.errors.UniqueViolation as exc:
        raise HandleAlreadyExistsError(payload.handle) from exc

    with db.read() as conn:
        refreshed = TableRead.get_user_by_userid(conn, user.user_id)
    if refreshed is None:
        return UserPublic.model_validate(user.model_dump())
    return UserPublic.model_validate(refreshed.model_dump())


@router.patch("/me/password", response_model=UserPublic)
def update_me_password(
    payload: ChangePasswordRequest,
    user: CurrentUserDep,
    service: AuthServiceDep,
) -> UserPublic:
    service.change_password(
        user_id=user.user_id,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return UserPublic.model_validate(user.model_dump())


@router.get("/me/top-up", response_model=TopUpStatusWire)
def get_top_up_status(
    user: CurrentUserDep, service: BalanceServiceDep
) -> TopUpStatusWire:
    """Cooldown status only — database read, no chain call, no mint, no write.

    The profile page already fetches the balance from `/balance-allowance`;
    re-reading it here would double an RPC round-trip on every page load for
    no benefit. This just tells the button when it may be clicked, so it can
    be disabled with a countdown instead of only failing after a click.
    """
    return TopUpStatusWire(nextAllowedAt=service.next_allowed(user))


@router.post("/me/top-up", response_model=TopUpWire)
def top_up_balance(user: CurrentUserDep, service: BalanceServiceDep) -> TopUpWire:
    """Restore the paper balance to the target, at most once a day.

    Returns 200 with `minted: "0"` when the cooldown is still running or the
    balance is already at the target — the button shows the reason, and neither
    case is an error worth an exception.
    """
    result = service.top_up(user, int(time.time()))
    return TopUpWire(
        balance=str(result.balance_raw),
        minted=str(result.minted_raw),
        nextAllowedAt=result.next_allowed_at,
    )
