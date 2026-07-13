from fastapi import APIRouter, Depends

from agentpit.api.deps import PersonalityServiceDep, require_admin_token
from agentpit.datastructures.create_personality_request import CreatePersonalityRequest
from agentpit.datastructures.create_personality_response import (
    CreatePersonalityResponse,
)

router = APIRouter(tags=["personalities"])


@router.post(
    "/create_personality",
    response_model=CreatePersonalityResponse,
    dependencies=[Depends(require_admin_token)],
)
def create_personality(
    payload: CreatePersonalityRequest,
    service: PersonalityServiceDep,
) -> CreatePersonalityResponse:
    return service.create_personality(payload)
