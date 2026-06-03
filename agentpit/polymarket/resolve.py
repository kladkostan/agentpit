"""Bidirectional resolution between agentpit market identifiers
(integer market_id + outcome label) and Polymarket-style identifiers
(condition_id + ERC-1155 token_id / asset_id).

Connection-taking functions, mirroring the TableRead static-method idiom
(callers pass an open sqlite3 connection from DbSession.read()/.write()).
"""

import json
import sqlite3
from dataclasses import dataclass

from agentpit.datastructures.market import Market
from agentpit.db.table_read import TableRead
from agentpit.domain.exceptions import MarketNotFoundError, MarketStateError


@dataclass(frozen=True)
class ResolvedOutcome:
    """One resolved (market, outcome) pair."""

    market: Market
    token_id: str          # ERC-1155 token id (== Polymarket asset_id)
    condition_id: str      # native CTF condition id (== Polymarket `market`)
    outcome_index: int     # 0-based index into market.erc1155_tokens


def resolve_by_market_outcome(
    conn: sqlite3.Connection, market_id: int, outcome: str
) -> ResolvedOutcome:
    """Resolve (market_id, outcome label) -> ResolvedOutcome.

    Outcome matching is case-insensitive. Raises MarketNotFoundError if the
    market does not exist, MarketStateError if the label is not an outcome.
    """
    market = TableRead.read_market(conn, market_id)
    if market is None:
        raise MarketNotFoundError(market_id)
    for index, (token_id, label) in enumerate(market.erc1155_tokens):
        if label.upper() == outcome.upper():
            return ResolvedOutcome(
                market=market,
                token_id=token_id,
                condition_id=market.condition_id.value,
                outcome_index=index,
            )
    raise MarketStateError(f"market {market_id} has no outcome '{outcome}'")


def resolve_by_token_id(
    conn: sqlite3.Connection, token_id: str
) -> ResolvedOutcome | None:
    """Resolve an ERC-1155 token_id -> ResolvedOutcome, or None if unknown.

    The markets table stores ERC1155_TOKENS as a JSON array of
    [token_id, label] pairs, so we find the containing market with a
    quote-anchored LIKE (the surrounding quotes prevent "11" matching "111").
    """
    row = conn.execute(
        "SELECT MARKET_ID, ERC1155_TOKENS FROM markets "
        "WHERE ERC1155_TOKENS LIKE ? LIMIT 1",
        (f'%"{token_id}"%',),
    ).fetchone()
    if row is None:
        return None
    market_id, tokens_json = row[0], row[1]
    pairs = json.loads(tokens_json) if tokens_json else []
    for index, pair in enumerate(pairs):
        if pair[0] == token_id:
            market = TableRead.read_market(conn, market_id)
            if market is None:
                return None
            return ResolvedOutcome(
                market=market,
                token_id=token_id,
                condition_id=market.condition_id.value,
                outcome_index=index,
            )
    return None
