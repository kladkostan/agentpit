from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import (
    APIKeyHeader,
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from agentpit.auth.authkit_tokens import AuthKitVerifier
from agentpit.auth.jwt import JwtCoder
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.domain.exceptions import InvalidCredentialsError

_bearer = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _unauth(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _authkit_user(db: DbSession, authkit: AuthKitVerifier, token: str) -> User:
    """The account an AuthKit access token belongs to -- never a new one.

    A token that verifies but matches no row is rejected, not onboarded.
    Creating the account here would hand a funded wallet to any valid AuthKit
    session for our application that touched any authenticated route; creation
    belongs to `POST /auth/session` alone, which has the mailed code as proof
    the caller owns the address.
    """
    try:
        workos_user_id = authkit.verify(token)
    except InvalidCredentialsError:
        # Same wording as the legacy branch above: which of the two verifiers
        # refused is nothing a caller should be able to probe for.
        raise _unauth("invalid token")

    with db.read() as conn:
        user = TableRead.get_user_by_workos_id(conn, workos_user_id)
    if user is None:
        raise _unauth("unknown session")
    return user


def make_current_user_dep(coder: JwtCoder, authkit: AuthKitVerifier | None = None):
    """Build a FastAPI dependency that resolves a request credential to a User.

    Three accepted credentials: a long-lived `X-API-Key` header (checked
    first), a legacy `JwtCoder` bearer token, or an AuthKit access token. The
    coder and the verifier are captured by closure so tests can swap them via
    dependency_overrides.

    `authkit` is None on a deployment with no `WORKOS_CLIENT_ID` -- the issuer
    and the JWKS URL are both derived from it, so a verifier built without one
    could only reject everything. That deployment behaves exactly as it did
    before this plan.

    Both bearer paths are accepted for the whole of this transition; plan 3
    removes the legacy one.
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
            # PyJWT checks the signature before `exp`, so reaching this means
            # the token verified against OUR secret: it is certainly a legacy
            # one, and handing it to AuthKit could only replace an accurate
            # message with a vaguer one.
            raise _unauth("token expired")
        except jwt.PyJWTError:
            # Legacy first, AuthKit second, and deliberately in that order: the
            # legacy check is a local HMAC verification with no I/O, while
            # `authkit.verify` may fetch a JWKS. During the transition the
            # common case then costs nothing extra.
            #
            # Anything that is not a legacy token lands here, including
            # unauthenticated junk, so `verify` must not fetch for a token that
            # is not plausibly ours -- see the gate at the top of it, and the
            # single-flight guard in `cached_key_resolver`. Without those, this
            # line hands a stranger one live request to api.workos.com per
            # request, in the threadpool the X-API-Key path shares.
            if authkit is None:
                raise _unauth("invalid token")
            return _authkit_user(db, authkit, creds.credentials)

        user_id = payload.get("sub")
        if not isinstance(user_id, str):
            raise _unauth("invalid token payload")

        with db.read() as conn:
            user = TableRead.get_user_by_userid(conn, user_id)
        if user is None:
            raise _unauth("user no longer exists")
        return user

    return current_user
