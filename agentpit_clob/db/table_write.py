import json
import sqlite3


class TableWrite:
    @staticmethod
    def create_market(
        db: sqlite3.Connection,
        market_id: int,
        condition_id: str,
        description: str,
        erc155_tokens: list,
    ) -> None:
        if not isinstance(market_id, int):
            raise TypeError("market_id must be int")
        if not isinstance(condition_id, str):
            raise TypeError("condition_id must be str")
        if not isinstance(description, str):
            raise TypeError("description must be str")
        if not isinstance(erc155_tokens, list):
            raise TypeError("erc155_tokens must be list")

        erc155_tokens_json = json.dumps(erc155_tokens, separators=(",", ":"))

        with db:
            db.execute(
                """
                INSERT INTO markets (MARKET_ID, CONDITION_ID, DESCRIPTION, ERC155_TOKENS)
                VALUES (?, ?, ?, ?)
                """,
                (market_id, condition_id, description, erc155_tokens_json),
            )
