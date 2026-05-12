from fastapi import APIRouter

from agentpit.api.deps import AuthServiceDep
from agentpit.datastructures.auth_response import AuthResponse
from agentpit.datastructures.login_request import LoginRequest
from agentpit.datastructures.register_request import RegisterRequest

router = APIRouter(tags=["auth"])


@router.post("/register", response_model=AuthResponse)
def register(payload: RegisterRequest, service: AuthServiceDep) -> AuthResponse:
    return service.register(payload)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, service: AuthServiceDep) -> AuthResponse:
    return service.login(payload)
