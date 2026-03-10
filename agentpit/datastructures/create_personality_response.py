from pydantic import BaseModel
from agentpit.common import check_state


class CreatePersonalityResponse(BaseModel):
    personality_id: int
    title: str
    spec: dict

    def model_post_init(self, __context):
        check_state(self.personality_id > 0, "personality_id must be positive")
        check_state(len(self.title) > 0, "title must not be empty")
        check_state("beliefs" in self.spec, "spec must contain beliefs")
        check_state("methods" in self.spec, "spec must contain methods")
        check_state("needs" in self.spec, "spec must contain needs")
