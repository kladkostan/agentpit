from pydantic import BaseModel
from agentpit.common import check_state


class CreatePersonalityRequest(BaseModel):
    personality_id: str
    title: str
    beliefs: str
    methods: str
    needs: str

    def model_post_init(self, __context):
        check_state(len(self.personality_id) > 0, "personality_id must not be empty")
        check_state(len(self.title) > 0, "title must not be empty")
        check_state(len(self.beliefs) > 0, "beliefs must not be empty")
        check_state(len(self.methods) > 0, "methods must not be empty")
        check_state(len(self.needs) > 0, "needs must not be empty")

