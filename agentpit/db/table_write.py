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
                erc1155_tokens_json
            ),
        )

        return Market(
            question=request.question,
            market_id=next_market_id,
            polymarket_id=request.polymarket_id,
            condition_id=condition_id_hex,
            description=request.description,
            slug=request.slug,
            erc1155_tokens=request.erc1155_tokens,
            market_state=MarketState.ACTIVE,
            start_date=request.start_date,
            end_date=request.end_date,
            resolved_outcome=None,
        )

    @staticmethod
    def update_market(
            db: sqlite3.Connection,
            request: CreateMarketRequest
    ) -> Market:
        # Compute condition_id from question and number of outcomes
        condition_id = compute_condition_id(request.question, len(request.erc1155_tokens))
        condition_id_hex = "0x" + condition_id.hex()
        erc1155_tokens_json = json.dumps(request.erc1155_tokens, separators=(",", ":"))

        # Fetch existing market details to preserve state and IDs
        cursor = db.execute(
            "SELECT MARKET_ID, COALESCE(MARKET_STATE, 'DRAFT'), RESOLVED_OUTCOME FROM markets WHERE POLYMARKET_ID = ?",
            (request.polymarket_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Market with Polymarket ID {request.polymarket_id} not found")

        market_id, market_state, resolved_outcome = row

        db.execute(
            """
            UPDATE markets
            SET CONDITION_ID   = ?,
                QUESTION       = ?,
                DESCRIPTION    = ?,
                SLUG           = ?,
                START_DATE     = ?,
                END_DATE       = ?,
                erc1155_TOKENS = ?
            WHERE POLYMARKET_ID = ?
            """,
            (
                condition_id_hex,
                request.question,
                request.description,
                request.slug,
                request.start_date,
                request.end_date,
                erc1155_tokens_json,
                request.polymarket_id
            ),
        )

        return Market(
            question=request.question,
            market_id=market_id,
            polymarket_id=request.polymarket_id,
            condition_id=condition_id_hex,
            description=request.description,
            slug=request.slug,
            erc1155_tokens=request.erc1155_tokens,
            market_state=MarketState(market_state),
            start_date=request.start_date,
            end_date=request.end_date,
            resolved_outcome=resolved_outcome,
        )
