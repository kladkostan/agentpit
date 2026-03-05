import sqlite3
import json

from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market import Market
from agentpit.datastructures.market_state import MarketState
from agentpit.utils.condition_id import compute_condition_id
from pydantic import validate_call


class TableWrite:
    @staticmethod
    def create_market(
            db : sqlite3.Connection,
            request: CreateMarketRequest
    ) -> Market:
        # Compute condition_id from question and number of outcomes
        condition_id = compute_condition_id(request.question, len(request.erc1155_tokens))
        condition_id_hex = "0x" + condition_id.hex()
        erc1155_tokens_json = json.dumps(request.erc1155_tokens, separators=(",", ":"))

        row = db.execute(
            "SELECT COALESCE(MAX(MARKET_ID), 0) + 1 FROM markets"
        ).fetchone()
        next_market_id = int(row[0])

        db.execute(
            """
            INSERT INTO markets (MARKET_ID,
                                 CONDITION_ID,
                                 POLYMARKET_ID,
                                 QUESTION,
                                 DESCRIPTION,
                                 SLUG,
                                 START_DATE,
                                 END_DATE,
                                 erc1155_TOKENS)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                next_market_id,
                condition_id_hex,
                request.polymarket_id,
                request.question,
                request.description,
                request.slug,
                request.start_date,
                request.end_date,
                request.erc1155_tokens_json,
            ),
        )

        return Market(
            question=request.question,
            market_id=next_market_id,
            polymarket_id=request.polymarket_id,
            condition_id=condition_id_hex,
            description=request.description,
            erc1155_tokens=request.erc1155_tokens,
            market_state=MarketState.ACTIVE,
            start_date=request.start_date,
            end_date=request.end_date,
            resolved_outcome=None,
        )
