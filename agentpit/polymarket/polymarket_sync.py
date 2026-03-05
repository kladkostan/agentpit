"""
Utility to fetch all markets from Polymarket and re-create them locally
using TableWrite.create_market.
"""

import logging
import sqlite3

from py_clob_client.http_helpers.helpers import get

from agentpit.db.table_write import TableWrite
from agentpit.datastructures.market import Market

logger = logging.getLogger(__name__)

POLYMARKET_CLOB_URL = "https://clob.polymarket.com"
END_CURSOR = "LTE="


def fetch_all_polymarket_markets(host: str = POLYMARKET_CLOB_URL) -> list[dict]:
    """
    Fetch all markets from Polymarket's CLOB API, paginating through all pages.

    Args:
        host: The Polymarket CLOB API base URL.

    Returns:
        A list of raw market dicts from the Polymarket API.
    """
    all_markets = []
    next_cursor = "MA=="

    while next_cursor != END_CURSOR:
        response = get(f"{host}/markets?next_cursor={next_cursor}")
        next_cursor = response.get("next_cursor", END_CURSOR)
        data = response.get("data", [])
        all_markets.extend(data)
        logger.info(
            "Fetched %d markets (total so far: %d)", len(data), len(all_markets)
        )

    logger.info("Finished fetching %d markets from Polymarket", len(all_markets))
    return all_markets


def fetch_polymarket_market(
    condition_id: str, host: str = POLYMARKET_CLOB_URL
) -> dict | None:
    """
    Fetch a single market from Polymarket by condition_id.
    """
    try:
        result = get(f"{host}/markets/{condition_id}")
        # Relax validation: if we got a dict back without an HTTP error, return it.
        if isinstance(result, dict):
            return result
    except Exception as e:
        logger.warning("Failed to fetch market %s: %s", condition_id, e)
    return None


def _polymarket_to_erc1155_tokens(pm_market: dict) -> list[tuple[str, str]]:
    """
    Convert a Polymarket market's token list into erc1155_tokens format:
    list of [token_id, label] pairs.

    Polymarket markets have a ``tokens`` field that is a list of dicts like:
        [{"token_id": "123...", "outcome": "Yes"}, ...]
    """
    tokens = pm_market.get("tokens", [])
    return [(t["token_id"], t["outcome"]) for t in tokens]


def sync_polymarket_markets(
    db: sqlite3.Connection,
    host: str = POLYMARKET_CLOB_URL,
) -> list[Market]:
    """
    Fetch all markets from Polymarket and re-create them locally using
    TableWrite.create_market.

    Args:
        db: An open sqlite3 connection with tables already created.
        host: The Polymarket CLOB API base URL.

    Returns:
        A list of locally-created Market objects.
    """
    pm_markets = fetch_all_polymarket_markets(host)
    created_markets: list[Market] = []

    for pm_market in pm_markets:
        question = pm_market.get("question", "").strip()
        description = pm_market.get("description", "").strip()
        erc1155_tokens = _polymarket_to_erc1155_tokens(pm_market)

        # Skip markets with missing or invalid data
        if not question:
            logger.warning(
                "Skipping market with condition_id=%s: missing question",
                pm_market.get("condition_id"),
            )
            continue

        if not erc1155_tokens:
            logger.warning(
                "Skipping market '%s': no tokens/outcomes defined", question
            )
            continue

        # Default description if empty
        if not description:
            description = question

        try:
            market = TableWrite.create_market(
                db,
                question=question,
                description=description,
                erc1155_tokens=erc1155_tokens,
            )
            created_markets.append(market)
            logger.debug("Created local market #%d: %s", market.market_id, question)
        except Exception:
            logger.exception("Failed to create market for question: %s", question)

    logger.info(
        "Synced %d/%d Polymarket markets locally",
        len(created_markets),
        len(pm_markets),
    )
    return created_markets

