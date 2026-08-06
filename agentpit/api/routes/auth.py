from fastapi import APIRouter

from agentpit.api.deps import AuthServiceDep
from agentpit.datastructures.auth_response import AuthResponse, GoogleAuthResponse
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
