from agentpit.datastructures.create_agent_request import CreateAgentRequest
from agentpit.datastructures.create_agent_response import CreateAgentResponse
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.domain.exceptions import AgentAlreadyExistsError, PersonalityNotFoundError


class AgentService:
    def __init__(self, db: DbSession):
        self._db = db

    def create_agent(self, payload: CreateAgentRequest) -> CreateAgentResponse:
        with self._db.write() as conn:
            if TableRead.get_agent_by_id(conn, payload.agent_id) is not None:
                raise AgentAlreadyExistsError(payload.agent_id)

            personality_row = conn.execute(
                "SELECT 1 FROM personalities WHERE PERSONALITY_ID = ? LIMIT 1",
                (payload.personality_id,),
            ).fetchone()
            if personality_row is None:
                raise PersonalityNotFoundError(payload.personality_id)

            TableWrite.create_agent(conn, payload.agent_id, payload.personality_id)
            agent = TableRead.get_agent_by_id(conn, payload.agent_id)

        return CreateAgentResponse(
            agent_id=agent["agent_id"],
            personality_id=agent["personality_id"],
            state=agent["state"],
            history=agent["history"],
            todo=agent["todo"],
        )
