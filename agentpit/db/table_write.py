import json
import sqlite3

from agentpit.datastructures.market import Market
from agentpit.datastructures.market_state import MarketState
from agentpit.utils.condition_id import compute_condition_id


class TableWrite:
    @staticmethod
    def create_market(
        db: sqlite3.Connection,
        question: str,
        description: str,
        erc155_tokens: list,
    ) -> Market:
        # Compute condition_id from question and number of outcomes
        condition_id = compute_condition_id(question, len(erc155_tokens))
        condition_id_hex = "0x" + condition_id.hex()

        erc155_tokens_json = json.dumps(erc155_tokens, separators=(",", ":"))

        with db:
            row = db.execute(
                "SELECT COALESCE(MAX(MARKET_ID), 0) + 1 FROM markets"
            ).fetchone()
            next_market_id = int(row[0])

            db.execute(
                """
                INSERT INTO markets (MARKET_ID, CONDITION_ID, QUESTION, DESCRIPTION, ERC155_TOKENS)
                VALUES (?, ?, ?, ?, ?)
                """,
                (next_market_id, condition_id_hex, question, description, erc155_tokens_json),
            )

        return Market(
            question=question,
            market_id=next_market_id,
            condition_id=condition_id_hex,
            description=description,
            erc155_tokens=erc155_tokens,
            market_state=MarketState.DRAFT,
        )

