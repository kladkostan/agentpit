"""Admin-only routes. Guarded by an X-Admin-Token header matching
``Settings.admin_token``.

These endpoints exist for operational bot management (flagging bot users
out of public leaderboards). They are not user-facing.
"""

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from agentpit.api.deps import SessionDep, SettingsDep
from agentpit.db.table_write import TableWrite

router = APIRouter(tags=["admin"], prefix="/admin")


class MarkBotRequest(BaseModel):
    eth_address: str


class MarkBotResponse(BaseModel):
    eth_address: str
    is_bot: bool


def _check_admin(provided: str | None, expected: str) -> None:
    if provided is None or provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="admin token missing or invalid",
        )


@router.post("/mark_bot", response_model=MarkBotResponse)
def mark_bot(
    payload: MarkBotRequest,
    settings: SettingsDep,
    db: SessionDep,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> MarkBotResponse:
    _check_admin(x_admin_token, settings.admin_token)
    with db.write() as conn:
        updated = TableWrite.mark_user_as_bot_by_eth_address(conn, payload.eth_address)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no user with eth_address {payload.eth_address}",
        )
    return MarkBotResponse(eth_address=payload.eth_address, is_bot=True)
