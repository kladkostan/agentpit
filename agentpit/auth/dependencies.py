from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import (
    APIKeyHeader,
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from agentpit.auth.jwt import JwtCoder
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead

_bearer = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _unauth(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def make_current_user_dep(coder: JwtCoder):
    """Build a FastAPI dependency that resolves a request credential to a User.

    Two accepted credentials: a long-lived `X-API-Key` header (checked first),
    or a bearer JWT (the original path, unchanged). The coder is captured by
    closure so tests can swap it via dependency_overrides.
    """
    from agentpit.api.deps import get_db_session

    def current_user(
        api_key: Annotated[str | None, Depends(_api_key_header)],
        creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
        db: Annotated[DbSession, Depends(get_db_session)],
    ) -> User:
        if api_key:
            with db.read() as conn:
                user = TableRead.get_user_by_api_key(conn, api_key)
            if user is None:
                raise _unauth("invalid api key")
            return user

        if creds is None or not creds.credentials:
            raise _unauth("missing credentials")
        try:
            payload = coder.decode(creds.credentials)
        except jwt.ExpiredSignatureError:
            raise _unauth("token expired")
        except jwt.PyJWTError:
            raise _unauth("invalid token")

        user_id = payload.get("sub")
        if not isinstance(user_id, str):
            raise _unauth("invalid token payload")

        with db.read() as conn:
            user = TableRead.get_user_by_userid(conn, user_id)
        if user is None:
            raise _unauth("user no longer exists")
        return user

    return current_user
