# agentpit/fastapi/agentpit_server.py
import os
import sqlite3
from fastapi import FastAPI
from pydantic import BaseModel, field_validator

from agentpit.db.table_create import TableCreate
from agentpit.db.table_write import TableWrite
from agentpit.datastructures.market import Market
from agentpit.utils.parse import is_hex256


class CreateMarketRequest(BaseModel):
    condition_id: str
    description: str
    erc155_tokens: list[tuple[str, str]]

    @field_validator("condition_id")
    @classmethod
    def validate_condition_id(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("must be a non-empty string")
        if not is_hex256(v):
            raise ValueError("must be a 256-bit hex string (64 hex chars, optional 0x prefix)")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("must be a non-empty string")
        return v

    @field_validator("erc155_tokens")
    @classmethod
    def validate_erc155_tokens(cls, v: list[tuple[str, str]]) -> list[tuple[str, str]]:
        if not isinstance(v, list):
            raise ValueError("must be a list of [tokenId, label] pairs")
        for pair in v:
            if (
                not isinstance(pair, (list, tuple))
                or len(pair) != 2
                or not all(isinstance(x, str) and x for x in pair)
            ):
                raise ValueError("each token pair must be a tuple or list of two non-empty strings")
        return v


class AgentPitServer(FastAPI):
    def __init__(self, *args, db_path: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._db_path = db_path or os.getenv("AGENTPIT_DB_PATH", ":memory:")
        self._connect_db()
        self.add_api_route("/", self.get_version, methods=["GET"])
        self.add_api_route(
            "/markets",
            self.create_market,
            methods=["POST"],
            response_model=Market,
        )

    def _connect_db(self) -> None:
        self._db = sqlite3.connect(self._db_path, check_same_thread=False)
        TableCreate.create_all_tables(self._db)

    def _ensure_db(self) -> None:
        if not hasattr(self, "_db") or self._db is None:
            self._connect_db()
            return
        try:
            self._db.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            self._connect_db()

    def get_version(self) -> dict[str, str]:
        return {"version": "1.0"}

    def create_market(self, payload: CreateMarketRequest) -> Market:
        self._ensure_db()
        return TableWrite.create_market(
            self._db,
            condition_id=payload.condition_id,
            description=payload.description,
            erc155_tokens=payload.erc155_tokens,
        )

    def shutdown(self) -> None:
        if hasattr(self, "_db") and self._db is not None:
            self._db.close()
            self._db = None
        print("AgentPitServer is shutting down...")
