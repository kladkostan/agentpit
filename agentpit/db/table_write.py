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

    @staticmethod
    def resolve_market(
        db: sqlite3.Connection, market_id: int, winning_outcome_index: int
    ) -> Market:
        """
        Resolve a market by setting the winning outcome and updating state to RESOLVED.
        """
        with db:
            # Validate market exists and get its info
            from agentpit.db.table_read import TableRead
            market = TableRead.read_market(db, market_id)
            if market is None:
                raise ValueError(f"Market {market_id} not found")

            # Validate winning outcome index is within bounds
            if winning_outcome_index < 0 or winning_outcome_index >= len(market.erc155_tokens):
                raise ValueError(
                    f"Invalid winning outcome index {winning_outcome_index}. "
                    f"Market has {len(market.erc155_tokens)} outcomes (indices 0-{len(market.erc155_tokens)-1})"
                )

            # Update market state and resolved outcome
            db.execute(
                """
                UPDATE markets
                SET MARKET_STATE = ?, RESOLVED_OUTCOME = ?
                WHERE MARKET_ID = ?
                """,
                (MarketState.RESOLVED.value, winning_outcome_index, market_id),
            )

        # Return updated market
        from agentpit.db.table_read import TableRead
        return TableRead.read_market(db, market_id)

