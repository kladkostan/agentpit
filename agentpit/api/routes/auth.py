from fastapi import APIRouter

from agentpit.api.deps import AuthKitServiceDep, AuthServiceDep
from agentpit.datastructures.auth_response import (
    AuthResponse,
    GoogleAuthResponse,
    UserPublic,
)
from agentpit.datastructures.authkit_requests import (
    CodeSignInRequest,
    RefreshRequest,
    SendCodeRequest,
)
from agentpit.datastructures.google_auth_request import GoogleAuthRequest
from agentpit.datastructures.login_request import LoginRequest
from agentpit.datastructures.register_request import RegisterRequest

router = APIRouter(tags=["auth"])


@router.post("/register", response_model=AuthResponse)
def register(payload: RegisterRequest, service: AuthServiceDep) -> AuthResponse:
    return service.register(payload)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, service: AuthServiceDep) -> AuthResponse:
    return service.login(payload)


@router.post("/auth/google", response_model=GoogleAuthResponse)
def google_sign_in(
    payload: GoogleAuthRequest, service: AuthServiceDep
) -> GoogleAuthResponse:
    return service.google_sign_in(payload.credential)


@router.post("/auth/code", status_code=202)
def send_auth_code(payload: SendCodeRequest, service: AuthKitServiceDep) -> dict:
    """Mail a six-digit code to this address.

    Always 202, whether or not the address has an account here: the reply must
    not tell a stranger who is registered. WorkOS creates the user on this call
    and mails the code; nothing is created on our side until the code comes
    back.
    """
    service.send_code(payload.email)
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
