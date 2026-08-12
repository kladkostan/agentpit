from fastapi import APIRouter, HTTPException, Request

from agentpit.api.deps import AuthKitServiceDep
from agentpit.datastructures.auth_response import AuthResponse, UserPublic
from agentpit.datastructures.authkit_requests import (
    CallbackRequest,
    CodeSignInRequest,
    RefreshRequest,
    SendCodeRequest,
)

router = APIRouter(tags=["auth"])


@router.post("/register", status_code=410)
def register() -> dict:
    """Gone: accounts are created by signing in.

    410 rather than 404 because this endpoint existed and was removed, and
    rather than deleting the route because that would answer 404 -- which reads
    as a typo to whoever calls it. The service code behind it is untouched, so
    reverting this commit restores a working legacy sign-in; plan 4 deletes it.
    """
    raise HTTPException(
        status_code=410, detail="sign in with a mailed code instead"
    )


@router.post("/login", status_code=410)
def login() -> dict:
    """Gone: sign in with a mailed code. See `register` above for why 410."""
    raise HTTPException(
        status_code=410, detail="sign in with a mailed code instead"
    )


@router.post("/auth/google", status_code=410)
def google_sign_in() -> dict:
    """Gone: Google now arrives through the WorkOS redirect.

    The browser is sent to AuthKit's authorize URL and comes back to
    `/auth/callback` with a code, so no Google credential is ever posted here.
    See `register` above for why 410.
    """
    raise HTTPException(
        status_code=410,
        detail="continue with Google, which returns through /auth/callback",
    )


@router.post("/auth/code", status_code=202)
def send_auth_code(
    payload: SendCodeRequest, request: Request, service: AuthKitServiceDep
) -> dict:
    """Mail a six-digit code to this address.

    Always 202, whether or not the address has an account here: the reply must
    not tell a stranger who is registered. WorkOS creates the user on this call
    and mails the code; nothing is created on our side until the code comes
    back.
    """
    # `request.client.host` is the real caller only because uvicorn runs with
    # `--proxy-headers`, which rewrites it from `X-Forwarded-For` -- and only
    # from a proxy it is told to trust. Without that flag every caller would
    # look like Caddy and the per-IP rule would become a global kill switch;
    # trusting the header from anywhere would let a caller forge it and skip
    # the rule entirely. The precondition is that the api container publishes
    # no ports, so Caddy is the only thing that can reach it.
    client_ip = request.client.host if request.client else None
    service.send_code(payload.email, client_ip=client_ip)
    return {"status": "sent"}


@router.post("/auth/session", response_model=AuthResponse)
def sign_in_with_code(
    payload: CodeSignInRequest, service: AuthKitServiceDep
) -> AuthResponse:
    session = service.sign_in(payload.email, payload.code)
    return AuthResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        user=UserPublic.model_validate(session.user.model_dump()),
    )


@router.post("/auth/callback", response_model=AuthResponse)
def complete_callback(
    payload: CallbackRequest, service: AuthKitServiceDep
) -> AuthResponse:
    """Exchange the code a WorkOS redirect came back with.

    Provider-agnostic on purpose: `authorization_code` is not a Google grant,
    so this route takes a code from any provider WorkOS is configured with, and
    from the AuthKit Hosted UI, without a line of new code. Hence
    `/auth/callback` and not `/auth/google/callback`.

    The exchange is server-side because `client_secret` is our API key. That is
    why the redirect lands on a page and the code arrives here by POST: the
    browser may carry the code, never the secret.
    """
    session = service.sign_in_with_authorization_code(payload.code)
    return AuthResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        user=UserPublic.model_validate(session.user.model_dump()),
    )


@router.post("/auth/refresh", response_model=AuthResponse)
def refresh_session(
    payload: RefreshRequest, service: AuthKitServiceDep
) -> AuthResponse:
    session = service.refresh(payload.refresh_token)
    return AuthResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        user=UserPublic.model_validate(session.user.model_dump()),
    )
