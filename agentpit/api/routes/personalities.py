from fastapi import APIRouter

from agentpit.api.deps import PersonalityServiceDep
from agentpit.datastructures.create_personality_request import CreatePersonalityRequest
from agentpit.datastructures.create_personality_response import CreatePersonalityResponse

router = APIRouter(tags=["personalities"])


@router.post("/create_personality", response_model=CreatePersonalityResponse)
def create_personality(
    payload: CreatePersonalityRequest,
    service: PersonalityServiceDep,
) -> CreatePersonalityResponse:
    return service.create_personality(payload)
