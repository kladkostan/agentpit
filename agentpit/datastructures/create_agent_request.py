from pydantic import BaseModel
from agentpit.common import check_state


class CreateAgentRequest(BaseModel):
    agent_id: str
    personality_id: str

    def model_post_init(self, __context):
        check_state(len(self.agent_id) > 0, "agent_id must not be empty")
        check_state(len(self.personality_id) > 0, "personality_id must not be empty")

