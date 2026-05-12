from fastapi import APIRouter

from agentpit.api.deps import CurrentUserDep
from agentpit.datastructures.auth_response import UserPublic

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserPublic)
def get_me(user: CurrentUserDep) -> UserPublic:
    return UserPublic.model_validate(user.model_dump())
