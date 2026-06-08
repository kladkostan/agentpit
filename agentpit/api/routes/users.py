import psycopg.errors

from fastapi import APIRouter

from agentpit.api.deps import AuthServiceDep, CurrentUserDep, SessionDep
from agentpit.datastructures.auth_response import UserPublic
from agentpit.datastructures.change_password_request import ChangePasswordRequest
from agentpit.datastructures.update_handle_request import UpdateHandleRequest
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.domain.exceptions import HandleAlreadyExistsError

router = APIRouter(tags=["users"])


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
