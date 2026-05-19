from fastapi import APIRouter

from agentpit.api.deps import AgentServiceDep
from agentpit.datastructures.create_agent_request import CreateAgentRequest
from agentpit.datastructures.create_agent_response import CreateAgentResponse

router = APIRouter(tags=["agents"])


@router.post("/create_agent", response_model=CreateAgentResponse)
def create_agent(
    payload: CreateAgentRequest, service: AgentServiceDep
) -> CreateAgentResponse:
    return service.create_agent(payload)
