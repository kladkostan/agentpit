"""
Utility to fetch all markets from Polymarket and re-create them locally
using TableWrite.create_market.
"""

import logging
import sqlite3
import json
import re
from datetime import datetime, timezone
from sqlite3 import Connection
from typing import Any

from agentpit.common import check_state
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.utils.parse import _iso_to_unix
from py_clob_client.http_helpers.helpers import get

from agentpit.db.table_write import TableWrite
from agentpit.db.table_read import TableRead
from agentpit.datastructures.market import Market

logger = logging.getLogger(__name__)


# Silence noisy per-request INFO logs like:
# "httpx:_client.py:1026 HTTP Request: GET ... 'HTTP/2 200 OK'"
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com"






def _coalesce_key(market: dict, target: str, source_keys: list[str]) -> None:
    """Set market[target] from the first non-None source key if target is missing/None."""
    if market.get(target) is not None:
        return
    for key in source_keys:
        if market.get(key) is not None:
            market[target] = market[key]
            return


def _parse_list_field(raw: object) -> list:
    """Parse list-like API fields that may arrive as JSON strings."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    return []


def _ensure_tokens(market: dict) -> None:
    """
    Ensure market['tokens'] is present.
    Build it from clobTokenIds + outcomes when Gamma doesn't provide tokens.
    """
    if isinstance(market.get("tokens"), list) and len(market["tokens"]) > 0:
        return

    token_ids = _parse_list_field(
        market.get("clobTokenIds") if market.get("clobTokenIds") is not None else market.get("clobTokenids")
    )
    outcomes = _parse_list_field(market.get("outcomes"))

    if not token_ids:
        market["tokens"] = []
        return

    tokens = []
    for idx, token_id in enumerate(token_ids):
        if token_id is None:
            continue
        label = outcomes[idx] if idx < len(outcomes) else f"Outcome {idx + 1}"
        tokens.append({"token_id": str(token_id), "outcome": str(label)})
    market["tokens"] = tokens


def _to_bool(value: object) -> bool | None:
    """Coerce common bool-like values; return None if unknown."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes"}:
            return True
        if text in {"false", "0", "no"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _normalize_market_fields(market: dict) -> dict:
    """
    Normalize common Gamma market fields to the snake_case keys used by this module.
    """
    _coalesce_key(market, "condition_id", ["conditionId"])
    _coalesce_key(market, "question", ["title", "name"])
    _coalesce_key(market, "description", ["descriptionText"])
    _coalesce_key(market, "polymarket_id", ["id", "marketId"])
    _coalesce_key(
        market,
        "end_date_iso",
        ["endDateIso", "endDateISO", "endDate", "endTimeIso", "endTime"],
    )
    _coalesce_key(market, "active", ["isActive"])
    _coalesce_key(market, "closed", ["isClosed"])
    _coalesce_key(market, "archived", ["isArchived"])
    _coalesce_key(market, "liquidity", ["liquidityNum", "liquidityClob"])

    # Normalize bool-ish fields that may arrive as strings.
    for key in ("active", "closed", "archived"):
        coerced = _to_bool(market.get(key))
        if coerced is not None:
            market[key] = coerced

    # Ensure normalized source id is either int-like or None.
    pmid = market.get("polymarket_id")
    if pmid is not None:
        try:
            market["polymarket_id"] = int(pmid)
        except (TypeError, ValueError):
            market["polymarket_id"] = None

    _ensure_tokens(market)
    return market


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
    liquidity_threshold: float = 1000000
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

    logger.info("Started fetching markets from Polymarket")

    # Build query parameters
    query_parts = [f"limit={limit}"]
    if archived:
        query_parts.append("archived=true")
    else:
        query_parts.append("archived=false")
    if not active:
        query_parts.append("active=false")
    else:
        query_parts.append("active=true")
    if closed:
        query_parts.append("closed=true")
    else:
        query_parts.append("closed=false")

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
            m = _normalize_market_fields(m)

            if not m.get("condition_id"):
                continue

            try:
                liquidity = float(m.get("liquidity") or 0)
            except (TypeError, ValueError):
                liquidity = 0.0

            if liquidity < liquidity_threshold:
                continue

            # Filter archived if not requested (API might leak them or mock data includes them)
            if not archived and m.get("archived", False):
                raise ValueError(
                    f"API returned archived market {m.get('condition_id')} despite request for non-archived"
                )

            # Gamma can still leak closed markets when closed=false.
            if not closed and m.get("closed", False):
                continue

            # Filter expired markets unless we asked for closed ones
            # (Test expectations require client-side filtering of expired markets)
            if not closed and _is_market_expired(m):
                continue
            filtered_data.append(m)

        all_markets.extend(filtered_data)
        logger.debug(
            "Fetched %d markets (total so far: %d)", len(data), len(all_markets)
        )

        if len(data) < limit:
            break

        offset += limit

    logger.info("Finished fetching %d markets from Polymarket", len(all_markets))
    return all_markets


def fetch_polymarket_market(
    condition_id: ConditionId, host: str = POLYMARKET_GAMMA_URL
) -> dict | None:
    """
    Fetch a single market from Polymarket by condition_id.
    """

    # Gamma API filter may return empty/multiple results depending on deployment.
    result = get(f"{host}/markets?condition_id={condition_id.value}")
    logger.info("Polymarket market fetch result: %s", result)
    if not isinstance(result, list) or len(result) == 0:
        result = get(f"{host}/markets?conditionId={condition_id.value}")
        logger.info("Polymarket market fetch result (fallback): %s", result)

    if isinstance(result, list):
        target = condition_id.value.lower()
        for raw_market in result:
            market = _normalize_market_fields(raw_market)
            if (market.get("condition_id") or "").lower() == target:
                return market

    return None


def _polymarket_to_erc1155_tokens(pm_market: dict) -> list[tuple[str, str]]:
    """
    Convert a Polymarket market's token list into erc1155_tokens format:
    list of [token_id, label] pairs.

    Polymarket markets have a ``tokens`` field that is a list of dicts like:
        [{"token_id": "123...", "outcome": "Yes"}, ...]
    """
    tokens = pm_market.get("tokens", [])
    result = []
    for t in tokens:
        # Handle both snake_case (CLOB) and camelCase (Gamma) for token_id
        tid = t.get("token_id") or t.get("tokenId")
        outcome = t.get("outcome") or t.get("label") or "Unknown"
        if tid:
            result.append((tid, outcome))
    return result


def fetch_and_sync_polymarket_markets(
    db: sqlite3.Connection,
    host: str = POLYMARKET_GAMMA_URL,
) -> list[Market]:
    pm_markets = fetch_all_polymarket_markets(host)
    return sync_polymarket_markets(db, pm_markets)

def sync_polymarket_markets(db: Connection, pm_markets: list[dict]) -> list[Any]:

    created_markets : list[Market] = []
    for pm_market in pm_markets:

        request = build_create_market_request_from_json(pm_market)
        check_state(bool(request.polymarket_id))

        existing_market_id = TableRead.read_market_id_by_polymarket_id(
            db, request.polymarket_id
        )

        if existing_market_id is None:
            market = TableWrite.create_market(
                db,
                request
            )
            logger.info("Added market: %s", pm_market)
            created_markets.append(market)


    logger.info(
        "Synced %d/%d Polymarket markets locally",
        len(created_markets),
        len(pm_markets),
    )
    return created_markets


def build_create_market_request_from_json(pm_market: dict) -> CreateMarketRequest:
    question = pm_market.get("question", "").strip()
    description = pm_market.get("description", "").strip()
    polymarket_id = pm_market.get("id")
    erc1155_tokens = _polymarket_to_erc1155_tokens(pm_market)
    slug = pm_market.get("slug")
    start_date = pm_market.get("startDate")
    end_date = pm_market.get("endDate")
    active = pm_market.get("active")
    closed = pm_market.get("closed")

    if active and not closed:
        state = MarketState.ACTIVE
    else:
        state = MarketState.CLOSED

    request = CreateMarketRequest(
        question=question,
        description=description,
        polymarket_id=polymarket_id,
        erc1155_tokens=erc1155_tokens,
        slug=slug,
        start_date=_iso_to_unix(start_date),
        end_date=_iso_to_unix(end_date) if end_date is not None else None,
        state=state
    )
    return request


@staticmethod
def update_market_outcomes(db: sqlite3.Connection) -> None:
    markets = TableRead.list_markets()
    for market in markets:
        if market.market_id == market_id:
            market.market_state = state
            db.execute(
                """
                UPDATE markets
                SET MARKET_STATE = ?
                WHERE MARKET_ID = ?
                """,
                (state.value, market_id)
            )
            return

