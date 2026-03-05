"""
Utility to fetch all markets from Polymarket and re-create them locally
using TableWrite.create_market.
"""

import logging
import sqlite3
from datetime import datetime, timezone

from py_clob_client.http_helpers.helpers import get

from agentpit.db.table_write import TableWrite
from agentpit.datastructures.market import Market

logger = logging.getLogger(__name__)

POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com"


def _is_market_expired(market: dict) -> bool:
    """Check if a market is expired based on end_date_iso."""
    end_date_iso = market.get("end_date_iso")
    if not end_date_iso:
        return False
    try:
        # Handle 'Z' suffix for UTC if present (Python 3.10 fromisoformat doesn't always handle it)
        if end_date_iso.endswith("Z"):
            end_date_iso = end_date_iso[:-1] + "+00:00"

        end_date = datetime.fromisoformat(end_date_iso)

        # Ensure timezone awareness for comparison
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)

        return end_date < datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False


def fetch_all_polymarket_markets(
    host: str = POLYMARKET_GAMMA_URL,
    closed: bool = False,
    active: bool = True,
    archived: bool = False,
) -> list[dict]:
    """
    Fetch all markets from Polymarket's Gamma API, paginating through all pages.

    Args:
        host: The Polymarket Gamma API base URL.
        closed: If True, include closed/resolved markets.
        active: If False, include inactive markets.
        archived: If True, include archived markets.

    Returns:
        A list of raw market dicts from the Polymarket API.
    """
    all_markets = []
    limit = 500
    offset = 0

    # Build query parameters
    query_parts = [f"limit={limit}"]
    if archived:
        query_parts.append("archived=true")
    if not active:
        query_parts.append("active=false")
    if closed:
        query_parts.append("closed=true")

    base_query = "&".join(query_parts)

    while True:
        response = get(f"{host}/markets?{base_query}&offset={offset}")

        # Gamma API returns a list of markets directly
        if isinstance(response, list):
            data = response
        else:
            data = []

        # Client-side filtering to match test expectations (tests/fastapi/test_polymarket_sync.py)
        filtered_data = []
        for m in data:
            # Filter archived if not requested (API might leak them or mock data includes them)
            if not archived and m.get("archived", False):
                raise ValueError(
                    f"API returned archived market {m.get('condition_id')} despite request for non-archived"
                )

            # Filter expired markets unless we asked for closed ones
            # (Test expectations require client-side filtering of expired markets)
            if not closed and _is_market_expired(m):
                continue

            filtered_data.append(m)

        all_markets.extend(filtered_data)
        logger.info(
            "Fetched %d markets (total so far: %d)", len(data), len(all_markets)
        )

        if len(data) < limit:
            break

        offset += limit

    logger.info("Finished fetching %d markets from Polymarket", len(all_markets))
    return all_markets


def fetch_polymarket_market(
    condition_id: str, host: str = POLYMARKET_GAMMA_URL
) -> dict | None:
    """
    Fetch a single market from Polymarket by condition_id.
    """
    try:
        # Gamma API filter by condition_id returns a list
        result = get(f"{host}/markets?condition_id={condition_id}")
        if isinstance(result, list) and len(result) > 0:
            return result[0]
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
    host: str = POLYMARKET_GAMMA_URL,
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

