from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agentpit.auth.jwt import JwtCoder
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead

# Local copy of SessionDep — importing from agentpit.api.deps would create a
# circular dependency (deps.py imports from auth.dependencies via the app).


_bearer = HTTPBearer(auto_error=False)


def _unauth(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def make_current_user_dep(coder: JwtCoder):
    """Build a FastAPI dependency that resolves the bearer token to a User row.

    The coder is captured by closure so we don't recreate one per request, and
    so tests can swap it out via the dependency_overrides hook.
    """
    # Imported lazily to avoid the deps -> auth.dependencies -> deps cycle.
    from agentpit.api.deps import get_db_session

    def current_user(
        creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
        db: Annotated[DbSession, Depends(get_db_session)],
    ) -> User:
        if creds is None or not creds.credentials:
            raise _unauth("missing bearer token")
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
