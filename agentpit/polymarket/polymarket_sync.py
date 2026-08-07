"""
Utility to fetch all markets from Polymarket and re-create them locally
using TableWrite.create_market.
"""

import logging
import json
from datetime import datetime, timezone
from typing import Any

from agentpit.common import check_state
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.onchain.admin import OnchainAdmin
from agentpit.polymarket.category_resolver import category_rank, resolve_category
from agentpit.polymarket.tag_taxonomy import normalize_slug
from agentpit.datastructures.event import Event
from agentpit.polymarket.conditional_token_framework import ConditionalTokenFramework
from agentpit.services.market_service import prepare_market_on_chain
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
CLOB_MARKET_URL = "https://clob.polymarket.com/markets"


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
        market.get("clobTokenIds")
        if market.get("clobTokenIds") is not None
        else market.get("clobTokenids")
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


def _as_float(value: object) -> float:
    """Coerce a Gamma numeric field (which arrives as int, float, str, or None) to float; 0.0 on failure."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _as_optional_float(value: object) -> float | None:
    """A number, or None when upstream sent nothing usable.

    Distinct from `_as_float`, which answers 0.0: for a volume that is honest,
    but a liquidity of 0.0 asserts an empty order book and a competitive of
    0.0 asserts a settled market. None is the signal `update_event_metrics`
    skips on, so an unparseable payload leaves whatever was already stored.
    """
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


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
    liquidity_threshold: float = 1000000,
    order: str | None = None,
    max_markets: int | None = None,
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

    if order:
        query_parts.append(f"order={order}")
        query_parts.append("ascending=false")

    # Tags are the only live source of category on Gamma: the `category` field
    # is null for every market, and the nested `events[]` objects carry no tags
    # at all. Without this parameter each market comes back with `tags: null`.
    query_parts.append("include_tag=true")

    base_query = "&".join(query_parts)

    while True:
        response = get(f"{host}/markets?{base_query}&offset={offset}")

        # Gamma API returns a list of markets directly
        if isinstance(response, list):
            data = response
        else:
            data = []

        # Gamma caps each response at ~100 rows regardless of the requested
        # `limit`, so we paginate by the ACTUAL page size and stop on the first
        # empty page. (The old `len(data) < limit` check broke after one page
        # because 100 < 500 is always true.)
        if not data:
            break

        # Client-side filtering to match test expectations (tests/api/test_polymarket_sync.py)
        filtered_data = []
        for m in data:
            m = _normalize_market_fields(m)

            if not m.get("condition_id"):
                continue

            # Use the stronger of orderbook depth ("liquidity") and cumulative
            # trade volume ("volumeNum"). Multi-outcome favorites (e.g. France
            # in a World Cup event) have shallow books on the cheap side even
            # though they're heavily traded — filtering on liquidity alone
            # silently drops exactly the markets users care about.
            liquidity = _as_float(m.get("liquidity"))
            volume = _as_float(m.get("volumeNum"))
            if volume == 0.0:
                volume = _as_float(m.get("volume"))

            if max(liquidity, volume) < liquidity_threshold:
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

        if max_markets is not None and len(all_markets) >= max_markets:
            break

        offset += len(data)

    if max_markets is not None:
        all_markets = all_markets[:max_markets]

    logger.info("Finished fetching %d markets from Polymarket", len(all_markets))
    return all_markets


def fetch_is_polymarket_market_closed(condition_id: ConditionId) -> bool:

    url = f"{CLOB_MARKET_URL}/{condition_id.value}"
    raw = get(url)
    logger.debug("CLOB single-market fetch raw result: %s", raw)

    # Normalize shape.
    market_raw: dict | None
    if isinstance(raw, dict):
        market_raw = raw
    elif isinstance(raw, list):
        # Pick the first dict whose conditionId/condition_id matches.
        market_raw = None
        for item in raw:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_market_fields(item)
            cid = normalized.get("condition_id")
            if cid is not None and str(cid).lower() == condition_id.value.lower():
                market_raw = item
                break

    check_state(bool(market_raw))

    market = _normalize_market_fields(market_raw)

    cid = market.get("condition_id")
    check_state(cid is not None)
    check_state((cid).lower() == condition_id.value.lower())
    coerced = _to_bool(market.get("closed"))
    check_state(coerced is not None)
    return coerced


def fetch_polymarket_market(
    condition_id: ConditionId, host: str = POLYMARKET_GAMMA_URL
) -> dict | None:
    """
    Fetch a single market from Polymarket by condition_id using the Gamma API.

    Gamma API returns a list; we pick the first matching entry.
    """
    # Gamma expects the bare conditionId string
    url = f"{host}/markets?conditionId={condition_id.value}"
    result = get(url)
    logger.debug("Polymarket market fetch raw result: %s", result)

    # Gamma returns a list; guard for unexpected shapes
    markets: list[dict]
    if isinstance(result, list):
        markets = result
    elif isinstance(result, dict):
        # Some helpers might already unwrap a single result
        markets = [result]
    else:
        return None

    # Gamma *should* return one market, but in practice can return multiple.
    # We choose the first exact condition_id match after normalization.
    for raw in markets:
        if not isinstance(raw, dict):
            continue
        m = _normalize_market_fields(raw)
        cid = m.get("condition_id")
        if cid is None:
            continue
        if str(cid).lower() == condition_id.value.lower():
            return m

    # No matching market found
    if len(markets) > 1:
        logger.warning(
            "Gamma returned %d markets for conditionId=%s but none matched exactly",
            len(markets),
            condition_id.value,
        )
    return None


def _extract_event_metadata(pm_market: dict) -> dict | None:
    """Pull event fields from the upstream `events` array.

    Polymarket's Gamma response has ``events: [{id, slug, title, image, ...}]``.
    We take the first entry — markets that belong to more than one event are
    rare and we treat the first as canonical.

    The category is derived from the *market's* ``tags`` rather than from the
    nested event: Gamma's ``category`` field is null everywhere, and the nested
    event objects carry no tags.
    """
    events = pm_market.get("events")
    if not isinstance(events, list) or len(events) == 0:
        return None
    raw = events[0]
    if not isinstance(raw, dict):
        return None
    pm_event_id = raw.get("id")
    slug = raw.get("slug")
    title = raw.get("title") or raw.get("name")
    if not slug or not title:
        return None
    start_iso = raw.get("startDate") or raw.get("startDateIso")
    end_iso = raw.get("endDate") or raw.get("endDateIso")
    volume24hr = raw.get("volume24hr")
    volume = raw.get("volume")
    liquidity = raw.get("liquidity")
    competitive = raw.get("competitive")
    return {
        "polymarket_event_id": str(pm_event_id) if pm_event_id is not None else None,
        "slug": str(slug),
        "title": str(title),
        "description": str(raw.get("description") or ""),
        "icon_url": raw.get("image") or raw.get("icon"),
        # NOT raw.get("category") — that field is null on every Gamma response.
        # Tags live on the market, not on the nested event object. The slug
        # type check matters: a truthy non-str slug would reach .strip() inside
        # resolve_category and raise, permanently skipping this market on every
        # future sync pass.
        "category": resolve_category(
            t.get("slug")
            for t in (pm_market.get("tags") or [])
            if isinstance(t, dict)
            and isinstance(t.get("slug"), (str, type(None)))
        ),
        "start_date": _iso_to_unix(start_iso) if start_iso else None,
        "end_date": _iso_to_unix(end_iso) if end_iso else None,
        "volume_24hr": _as_float(volume24hr) if volume24hr is not None else None,
        "volume": _as_float(volume) if volume is not None else None,
        "liquidity": _as_optional_float(liquidity),
        "competitive": _as_optional_float(competitive),
    }


def _extract_outcome_metadata(pm_market: dict) -> tuple[str | None, str | None]:
    """Return ``(outcome_label, icon_url)`` for a single sub-market.

    Polymarket uses ``groupItemTitle`` for the short name shown inside an
    event (e.g. "France") and ``image`` for the per-outcome icon.
    """
    label = pm_market.get("groupItemTitle")
    icon = pm_market.get("image")
    return (str(label) if label else None, str(icon) if icon else None)


def _sync_event_category(db, event: Event, category: str | None) -> None:
    """Raise an event's category when ``category`` is stricter than what's stored.

    An event owns many markets and the sync's order across them isn't
    guaranteed, so last-writer-wins would let the category oscillate between
    passes. Comparing ranks makes the result order-independent: the event
    converges on the strictest category any member market resolves to.

    Never clears — a market whose tags resolve to nothing (~0.4% of the feed)
    must not undo a good categorization contributed by a sibling market.
    """
    if category is None:
        return
    if category_rank(category) >= category_rank(event.category):
        return
    TableWrite.update_event_category(db, event_id=event.event_id, category=category)


def bind_existing_market_to_upstream_event(
    db, *, polymarket_id: int, pm_market: dict
) -> bool:
    """Rebind an already-synced market to its upstream event.

    Used on every sync pass so markets created before this feature shipped
    (or markets whose upstream event was renamed/recategorized) get their
    event grouping refreshed. Returns True if a rebind happened.
    """
    cid = TableRead.read_condition_id_by_polymarket_id(db, polymarket_id)
    if cid is None:
        return False
    market = TableRead.read_market_by_condition_id(db, cid)
    if market is None:
        return False
    bind_market_to_upstream_event(db, market, pm_market)
    return True


def extract_tags(pm_market: dict) -> list[tuple[str, str]] | None:
    """Pull ``(slug, label)`` pairs off an upstream market.

    Returns ``None`` — meaning "upstream said nothing, keep what is stored" —
    when ``tags`` is absent, null, or not a list. That distinction is the whole
    point: a Gamma request without ``include_tag=true`` returns ``tags: null``
    for every market, and treating that as an empty set would wipe good rows on
    every pass through such a code path. An empty LIST is different: upstream
    positively says this market has no tags, and the stored set should clear.

    Malformed entries are skipped individually rather than raised on. Raising
    here would abort this market's binding on every future pass, permanently.

    The label is only ever a display string, so a missing or non-string one
    falls back to the slug rather than dropping an otherwise good tag.
    """
    raw = pm_market.get("tags")
    if not isinstance(raw, list):
        return None
    out: list[tuple[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        slug = normalize_slug(entry.get("slug"))
        if slug is None:
            continue
        label = entry.get("label")
        out.append((slug, label if isinstance(label, str) and label.strip() else slug))
    return out


def bind_market_to_upstream_event(
    db, market: "Market", pm_market: dict
) -> None:
    """Idempotently upsert the upstream event and attach this market to it.

    No-op when the upstream market has no event metadata.
    """
    meta = _extract_event_metadata(pm_market)
    if meta is None:
        return
    # Prefer matching by polymarket_event_id (immutable) over slug (mutable).
    existing = None
    if meta["polymarket_event_id"]:
        existing = TableRead.get_event_by_polymarket_event_id(
            db, meta["polymarket_event_id"]
        )
    if existing is not None:
        # The upsert is skipped for known events (it matches on SLUG, which
        # upstream can rename), so the category is refreshed on its own.
        event = existing
        _sync_event_category(db, event, meta["category"])
    else:
        event = TableWrite.upsert_event(
            db,
            slug=meta["slug"],
            title=meta["title"],
            description=meta["description"],
            icon_url=meta["icon_url"],
            category=meta["category"],
            start_date=meta["start_date"],
            end_date=meta["end_date"],
            polymarket_event_id=meta["polymarket_event_id"],
        )
    # Refresh upstream 24h volume on every pass (drives homepage order). No-op
    # when the upstream entry carried no volume, so a good value is never
    # clobbered with null.
    TableWrite.update_event_volume(
        db, event.event_id, meta["volume_24hr"], meta.get("volume")
    )
    TableWrite.update_event_metrics(
        db, event.event_id, meta["liquidity"], meta["competitive"]
    )
    outcome_label, icon_url = _extract_outcome_metadata(pm_market)
    TableWrite.attach_market_to_event(
        db,
        market_id=market.market_id,
        event_id=event.event_id,
        outcome_label=outcome_label,
        icon_url=icon_url,
    )
    # Mirror the upstream tag list. This is the same payload `resolve_category`
    # above collapses into one CATEGORY; storing it whole is what lets the
    # sidebar offer real subcategories. Skipped entirely when upstream carried
    # no tags list, so a caller without include_tag=true cannot clear good rows.
    tags = extract_tags(pm_market)
    if tags is not None:
        TableWrite.replace_market_tags(db, market_id=market.market_id, tags=tags)


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
    db,
    admin: OnchainAdmin,
    host: str = POLYMARKET_GAMMA_URL,
    *,
    max_markets: int = 300,
    liquidity_min: float = 0.0,
) -> list[Market]:
    """Discover + locally create the trending Polymarket markets.

    Fetches the top markets by 24h volume (descending) from Gamma and syncs any
    not already present onto the local CTF. Discovery only — resolution
    mirroring + auto-redeem run in their own loop.

    Args:
        max_markets: cap on how many top-by-volume markets to consider per pass.
        liquidity_min: minimum max(liquidity, volume) floor; 0 = no floor.
    """
    pm_markets = fetch_all_polymarket_markets(
        host,
        liquidity_threshold=liquidity_min,
        # Gamma's sort key is `volume24hr` (no underscore); `volume_24hr` is
        # rejected with HTTP 422 "order fields are not valid".
        order="volume24hr",
        max_markets=max_markets,
    )
    created_markets = create_polymarket_markets_if_needed(db, pm_markets, admin)
    return created_markets


def create_polymarket_markets_if_needed(
    db,
    pm_markets: list[dict],
    admin: OnchainAdmin,
) -> list[Any]:

    created_markets: list[Market] = []
    failed = 0
    for pm_market in pm_markets:
        question = pm_market.get("question") or "<no question>"
        try:
            # SAVEPOINT per market: the batch shares one transaction (the
            # caller's db.write()), and without it a single failed INSERT
            # (e.g. duplicate question -> same derived CONDITION_ID) aborts
            # the transaction — every later market dies with
            # InFailedSqlTransaction and the closing COMMIT silently becomes
            # a ROLLBACK, losing the entire batch.
            with db.transaction():
                market = create_polygon_market_if_does_not_exist(
                    db, pm_market, admin
                )
        except Exception as exc:
            # One bad market (e.g. RPC blip on getOutcomeSlotCount) shouldn't
            # kill the whole sync batch. Keep the message single-line; the
            # stack trace lives at debug level for when you actually want it.
            failed += 1
            logger.warning("Skip %r (%s)", question, exc.__class__.__name__)
            logger.debug("Skip %r details", question, exc_info=True)
            continue
        if market is not None:
            created_markets.append(market)

    logger.info(
        "Synced %d/%d Polymarket markets locally (%d failed)",
        len(created_markets),
        len(pm_markets),
        failed,
    )
    return created_markets


def create_polygon_market_if_does_not_exist(
    db,
    pm_market: dict,
    admin: OnchainAdmin,
) -> Market | None:
    request = build_create_market_request_from_json(pm_market)
    check_state(bool(request.polymarket_id))
    assert request.polymarket_id is not None  # narrowed by check_state above

    # Cheap path first: a market already synced for this polymarket_id needs no
    # on-chain prepare — just keep its event grouping current and return.
    if TableRead.market_exists_by_polymarket_id(db, request.polymarket_id):
        bind_existing_market_to_upstream_event(
            db, polymarket_id=request.polymarket_id, pm_market=pm_market
        )
        # Backfill the upstream token-id cross-reference for markets synced
        # before positional capture existed (Up/Down windows had null ids), so
        # the book mirror can resolve them. No-op once populated.
        TableWrite.update_market_polymarket_tokens(
            db,
            polymarket_id=request.polymarket_id,
            yes_token_id=request.polymarket_yes_token_id,
            no_token_id=request.polymarket_no_token_id,
        )
        return None

    # New market: mirror onto the local CTF + Exchange so it's tradeable. This
    # overrides the upstream conditionId/tokenIds with locally-derived ones;
    # polymarket_id stays as the cross-reference.
    outcome_labels = [label for _, label in request.erc1155_tokens]
    local_condition_id, local_tokens = prepare_market_on_chain(
        admin, request.question, outcome_labels
    )
    request.condition_id = local_condition_id
    request.erc1155_tokens = local_tokens

    market = TableWrite.create_market(db, request, True)
    bind_market_to_upstream_event(db, market, pm_market)
    logger.info("Added market: %s", request.question)
    return market


def _default_resolution_fetcher(polymarket_condition_id: str) -> dict | None:
    """Look up upstream Polymarket market by conditionId via the CLOB API.

    CLOB is the canonical single-document endpoint and uses Polymarket's
    immutable Polygon-mainnet conditionId — not Gamma's mutable integer id.
    """
    url = f"{CLOB_MARKET_URL}/{polymarket_condition_id}"
    raw = get(url)
    if isinstance(raw, list):
        return raw[0] if raw else None
    if isinstance(raw, dict):
        return raw
    return None


def _winner_index_if_resolved(pm_response: dict) -> int | None:
    """Return the resolved outcome index, or None if upstream isn't settled."""
    if not pm_response.get("closed"):
        return None
    # umaResolutionStatus is the canonical "UMA has settled" flag, but some
    # markets close via CLOB-only resolution. We require closed + a winner
    # marker on a token; we don't insist on UMA settlement specifically.
    tokens = pm_response.get("tokens") or []
    for idx, t in enumerate(tokens):
        if isinstance(t, dict) and t.get("winner") is True:
            return idx
    return None


def list_scan_candidates(db, *, after_market_id: int, limit: int) -> list:
    """One slice of the rotating resolution scan. See TableRead.list_unresolved_markets_after."""
    return TableRead.list_unresolved_markets_after(db, after_market_id, limit)


def mirror_polymarket_resolutions(
    db,
    admin: OnchainAdmin,
    *,
    fetcher=_default_resolution_fetcher,
    now: int,
    market_ids: "set[int] | None" = None,
    candidates: "list | None" = None,
) -> int:
    """Walk synced markets and mirror upstream resolutions onto the local CTF.

    For each ACTIVE/CLOSED market with a `polymarket_id`, fetches upstream
    state. When upstream is settled with a clear winner, calls
    `admin.report_payouts` against the local CTF, then flips the local row
    to RESOLVED. Idempotent on subsequent runs.

    `market_ids`, when given, restricts the pass to those market ids — used by
    the fast per-window resolve loop to check only a couple of just-ended
    pinned windows instead of scanning (and upstream-fetching) every market.

    `candidates`, when given, replaces the end-date query entirely — that is how
    the rotating scan feeds in markets whose stated end date has not arrived but
    which upstream has already closed. Widening the candidate set cannot resolve
    anything extra on its own: `_winner_index_if_resolved` still requires the
    upstream document to say `closed` with a winning token.

    Returns the count of markets newly resolved this pass.
    """
    from eth_utils.crypto import keccak  # local import: avoid circulars at module load

    resolved_count = 0
    if candidates is None:
        candidates = TableRead.list_unresolved_ended_markets(db, now)
    if market_ids is not None:
        candidates = [m for m in candidates if m.market_id in market_ids]
    for market in candidates:
        if market.polymarket_condition_id is None:
            # Synced before the upstream-conditionId column existed, or a
            # locally-authored market with no Polymarket linkage. Either way,
            # nothing for the upstream mirror to do.
            continue
        if market.market_state in {MarketState.RESOLVED, MarketState.CANCELLED}:
            continue
        try:
            pm_response = fetcher(market.polymarket_condition_id)
        except Exception as exc:
            logger.warning(
                "resolution fetch failed for %s (%s)",
                market.market_id,
                exc.__class__.__name__,
            )
            continue
        if pm_response is None:
            continue
        winner_idx = _winner_index_if_resolved(pm_response)
        if winner_idx is None:
            continue

        # Binary YES/NO payout vector. partition is [1<<i for i in range(2)],
        # so payouts align: index 0 = YES, index 1 = NO.
        payouts = [
            1 if i == winner_idx else 0 for i in range(len(market.erc1155_tokens))
        ]
        question_id = keccak(text=market.question)
        cond_bytes = bytes.fromhex(market.condition_id.value[2:])

        # Check on-chain idempotency: if the CTF already has payouts, skip
        # the tx but still flip the DB row so local state catches up.
        denom = admin._contracts.ctf.functions.payoutDenominator(
            cond_bytes
        ).call()  # noqa: SLF001
        if denom == 0:
            try:
                admin.report_payouts(question_id, payouts)
            except Exception as exc:
                logger.warning(
                    "reportPayouts failed for market %s: %s",
                    market.market_id,
                    exc,
                )
                continue

        try:
            TableWrite.resolve_market(
                db,
                market_id=market.market_id,
                winning_outcome_index=winner_idx,
            )
            resolved_count += 1
        except ValueError as exc:
            # Race: another caller flipped the row between our read and write.
            logger.info("resolve_market noop for %s: %s", market.market_id, exc)
    return resolved_count


def auto_redeem_resolved_markets(
    db, admin: OnchainAdmin, *, gas_topup_wei: int = 10**18
) -> int:
    """Redeem every holder of each RESOLVED, not-yet-fully-redeemed market.

    `db` is a DbSession (not a raw connection) because PositionService manages
    its own read/write connections. For each candidate market, scans the
    participant accounts (trades + split/merge, including the house bot),
    redeems any with a nonzero on-chain token balance using their custodial
    key, and flags the market FULLY_REDEEMED once no holder remains.

    Returns the number of holder redemptions performed.
    """
    from agentpit.services.position_service import PositionService

    svc = PositionService(db, admin)
    redeemed = 0
    with db.read() as conn:
        markets = TableRead.list_resolved_unredeemed_markets(conn)

    for market in markets:
        token_strs = [t for t, _ in market.erc1155_tokens]
        token_ints = [int(t) for t in token_strs]
        with db.read() as conn:
            api_keys = TableRead.list_participant_api_keys_for_market(
                conn, market.market_id, token_strs
            )

        any_error = False
        for api_key in api_keys:
            with db.read() as conn:
                user = TableRead.get_user_by_api_key(conn, api_key)
            if user is None:
                continue
            if not any(
                admin.ctf_balance(user.eth_address, tid) > 0 for tid in token_ints
            ):
                continue
            try:
                try:
                    admin.fund_gas(user.eth_address, gas_topup_wei)
                except Exception:
                    logger.warning(
                        "gas top-up failed for %s on market %s (continuing)",
                        user.eth_address,
                        market.market_id,
                    )
                svc.redeem(user, market.market_id)
                redeemed += 1
            except Exception:
                logger.exception(
                    "auto-redeem failed for %s on market %s",
                    user.eth_address,
                    market.market_id,
                )
                any_error = True

        if any_error:
            continue  # leave FULLY_REDEEMED unset; retried next pass

        still_held = False
        for api_key in api_keys:
            with db.read() as conn:
                user = TableRead.get_user_by_api_key(conn, api_key)
            if user is None:
                continue
            if any(
                admin.ctf_balance(user.eth_address, tid) > 0 for tid in token_ints
            ):
                still_held = True
                break
        if not still_held:
            with db.write() as conn:
                TableWrite.mark_fully_redeemed(conn, market.market_id)

    return redeemed


def sync_market_state(db, condition_id: ConditionId) -> None:
    """Placeholder until upstream→local resolution mirroring is built.

    The original implementation queried Polymarket's CLOB for "is closed"
    and the CTF for resolution payouts. After the local-mirror change,
    `condition_id` here is the *local* one — Polymarket has never seen it,
    so the CLOB call 404s. Resolution propagation needs its own design:
    fetch upstream state by `polymarket_id`, then have the local admin
    `reportPayouts` against the local CTF before flipping the row to
    RESOLVED.
    """
    return None


def _token_id_of(t: object) -> str | None:
    """Pull a token id from a Polymarket tokens-list entry (snake or camel)."""
    if not isinstance(t, dict):
        return None
    tid = t.get("token_id") or t.get("tokenId")
    return str(tid) if tid is not None else None


def _extract_yes_no_token_ids(pm_market: dict) -> tuple[str | None, str | None]:
    """Return (yes_token_id, no_token_id) from a Polymarket market's tokens list.

    Polymarket binary markets list two tokens. Yes/No markets are matched by
    label (case-insensitive). For binary markets whose outcomes aren't literally
    Yes/No (e.g. *Up/Down*), fall back to **positional** mapping — slot 0 is the
    yes-side, slot 1 the no-side — which is the same index convention used by the
    erc1155 token order and the resolution payout vector. This positional id is
    what lets the book mirror resolve an upstream token for these markets
    (the mirror skips any market with a null yes-token). Returns (None, None)
    for non-binary markets.
    """
    tokens = pm_market.get("tokens") or []
    yes_id: str | None = None
    no_id: str | None = None
    for t in tokens:
        if not isinstance(t, dict):
            continue
        tid = _token_id_of(t)
        outcome = (t.get("outcome") or t.get("label") or "").strip().lower()
        if tid is None:
            continue
        if outcome == "yes":
            yes_id = tid
        elif outcome == "no":
            no_id = tid

    if (yes_id is None or no_id is None) and len(tokens) == 2:
        if yes_id is None:
            yes_id = _token_id_of(tokens[0])
        if no_id is None:
            no_id = _token_id_of(tokens[1])
    return yes_id, no_id


def build_create_market_request_from_json(pm_market: dict) -> CreateMarketRequest:
    question = pm_market.get("question", "").strip()
    description = pm_market.get("description", "").strip()
    polymarket_id = pm_market.get("id")
    erc1155_tokens = _polymarket_to_erc1155_tokens(pm_market)
    yes_tok, no_tok = _extract_yes_no_token_ids(pm_market)
    slug = pm_market.get("slug")
    start_date = pm_market.get("startDate")
    end_date = pm_market.get("endDate")
    active = pm_market.get("active")
    closed = pm_market.get("closed")
    condition_id = pm_market.get("conditionId")
    outcome_label, icon_url = _extract_outcome_metadata(pm_market)

    if active and not closed:
        state = MarketState.ACTIVE
    else:
        state = MarketState.CLOSED

    request = CreateMarketRequest(
        question=question,
        description=description,
        polymarket_id=polymarket_id,
        polymarket_condition_id=condition_id,
        polymarket_yes_token_id=yes_tok,
        polymarket_no_token_id=no_tok,
        erc1155_tokens=erc1155_tokens,
        slug=slug,
        start_date=_iso_to_unix(start_date),
        end_date=_iso_to_unix(end_date) if end_date is not None else None,
        state=state,
        condition_id=ConditionId(condition_id),
        outcome_label=outcome_label,
        icon_url=icon_url,
    )
    return request


@staticmethod
def update_market_outcomes(db) -> None:
    markets = TableRead.list_markets()
    for market in markets:
        if market.market_id == market_id:
            market.market_state = state
            db.execute(
                """
                UPDATE markets
                SET MARKET_STATE = %s
                WHERE MARKET_ID = %s
                """,
                (state.value, market_id),
            )
            return
