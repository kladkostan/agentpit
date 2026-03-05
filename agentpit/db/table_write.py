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
        erc1155_tokens: list,
        slug: str,
        start_date: int,
        end_date: int,
        polymarket_id: int | None = None,
    ) -> Market:
        # Compute condition_id from question and number of outcomes
        condition_id = compute_condition_id(question, len(erc1155_tokens))
        condition_id_hex = "0x" + condition_id.hex()

        erc1155_tokens_json = json.dumps(erc1155_tokens, separators=(",", ":"))

        row = db.execute(
            "SELECT COALESCE(MAX(MARKET_ID), 0) + 1 FROM markets"
        ).fetchone()
        next_market_id = int(row[0])

        db.execute(
            """
            INSERT INTO markets (
                MARKET_ID,
                CONDITION_ID,
                POLYMARKET_ID,
                QUESTION,
                DESCRIPTION,
                SLUG,
                START_DATE,
                END_DATE,
                erc1155_TOKENS
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                next_market_id,
                condition_id_hex,
                polymarket_id,
                question,
                description,
                slug,
                start_date,
                end_date,
                erc1155_tokens_json,
            ),
        )

        return Market(
            question=question,
            market_id=next_market_id,
            polymarket_id=polymarket_id,
            condition_id=condition_id_hex,
            description=description,
            erc1155_tokens=erc1155_tokens,
            market_state=MarketState.DRAFT,
            start_date=start_date,
            end_date=end_date,
            resolved_outcome=None,
        )
