import json
import sqlite3
from pydantic import validate_call

from agentpit.datastructures.market import Market
from agentpit.datastructures.market_state import MarketState


class TableWrite:
    @staticmethod
    @validate_call
    def create_market(
        db: sqlite3.Connection,
        condition_id: str,
        description: str,
        erc155_tokens: list,
    ) -> Market:
        erc155_tokens_json = json.dumps(erc155_tokens, separators=(",", ":"))

        with db:
            row = db.execute(
                "SELECT COALESCE(MAX(MARKET_ID), 0) + 1 FROM markets"
            ).fetchone()
            next_market_id = int(row[0])

            db.execute(
                """
                INSERT INTO markets (MARKET_ID, CONDITION_ID, DESCRIPTION, ERC155_TOKENS)
                VALUES (?, ?, ?, ?)
                """,
                (next_market_id, condition_id, description, erc155_tokens_json),
            )

        return Market(
            question=description,
            market_id=next_market_id,
            condition_id=condition_id,
            description=description,
            erc155_tokens=erc155_tokens,
            market_state=MarketState.DRAFT,
        )
