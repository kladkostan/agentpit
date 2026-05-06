from agentpit.datastructures.create_personality_request import CreatePersonalityRequest
from agentpit.datastructures.create_personality_response import CreatePersonalityResponse
from agentpit.db.session import DbSession
from agentpit.db.table_write import TableWrite


class PersonalityService:
    def __init__(self, db: DbSession):
        self._db = db

    def create_personality(self, payload: CreatePersonalityRequest) -> CreatePersonalityResponse:
        with self._db.write() as conn:
            personality_id = TableWrite.create_personality(
                conn,
                payload.personality_id,
                payload.title,
                payload.beliefs,
                payload.methods,
                payload.needs,
            )
        return CreatePersonalityResponse(
            personality_id=personality_id,
            title=payload.title,
            spec={
                "beliefs": payload.beliefs,
                "methods": payload.methods,
                "needs": payload.needs,
            },
        )
