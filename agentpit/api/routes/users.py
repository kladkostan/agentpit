from fastapi import APIRouter

from agentpit.api.deps import UserServiceDep
from agentpit.datastructures.create_user_request import CreateUserRequest
from agentpit.datastructures.create_user_response import CreateUserResponse

router = APIRouter(tags=["users"])


@router.post("/create_user", response_model=CreateUserResponse)
def create_user(payload: CreateUserRequest, service: UserServiceDep) -> CreateUserResponse:
    return service.create_user(payload)
