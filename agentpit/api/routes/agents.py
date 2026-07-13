from fastapi import APIRouter, Depends

from agentpit.api.deps import AgentServiceDep, require_admin_token
from agentpit.datastructures.create_agent_request import CreateAgentRequest
from agentpit.datastructures.create_agent_response import CreateAgentResponse

router = APIRouter(tags=["agents"])


@router.post(
    "/create_agent",
    response_model=CreateAgentResponse,
    dependencies=[Depends(require_admin_token)],
)
def create_agent(
    payload: CreateAgentRequest, service: AgentServiceDep
) -> CreateAgentResponse:
    return service.create_agent(payload)
