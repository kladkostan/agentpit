from agentpit.datastructures.create_user_request import CreateUserRequest
from agentpit.datastructures.create_user_response import CreateUserResponse
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.domain.exceptions import UserAlreadyExistsError


class UserService:
    def __init__(self, db: DbSession):
        self._db = db

    def create_user(self, payload: CreateUserRequest) -> CreateUserResponse:
        with self._db.write() as conn:
            if TableRead.get_user_by_userid(conn, payload.user_id) is not None:
                raise UserAlreadyExistsError(payload.user_id)
            api_key = TableWrite.create_user(conn, payload.user_id)
            user = TableRead.get_user_by_userid(conn, payload.user_id)
        return CreateUserResponse(
            user_id=payload.user_id,
            api_key=api_key,
            eth_address=user.eth_key.address,
        )
