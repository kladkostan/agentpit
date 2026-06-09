"""Fetch the live Polymarket CLOB midpoint and convert to micro-USDC."""
import logging

from py_clob_client.http_helpers.helpers import get

log = logging.getLogger(__name__)

CLOB_MIDPOINT_URL = "https://clob.polymarket.com/midpoint"
CLOB_BOOK_URL = "https://clob.polymarket.com/book"
MICRO = 1_000_000


def fetch_mid_micro(polymarket_token_id: str, *, getter=get) -> int | None:
    """Real Polymarket mid for one CLOB token id, as micro-USDC in [0, MICRO].

    Returns None on any network/parse error or one-sided/empty book — callers
    must skip that market this tick (never peg agentpit to a missing mid).
    """
    if not polymarket_token_id:
        return None
    try:
        resp = getter(f"{CLOB_MIDPOINT_URL}?token_id={polymarket_token_id}")
    except Exception as exc:  # PolyApiException, httpx errors, etc.
        log.warning("polymarket midpoint fetch failed for %s: %s", polymarket_token_id, exc)
        return None
    mid = resp.get("mid") if isinstance(resp, dict) else None
    if mid is None:
        return None
    try:
        return max(0, min(MICRO, round(float(mid) * MICRO)))
    except (TypeError, ValueError):
        return None


def _best_level_micro(levels, choose) -> int | None:
    """Best price (micro-USDC) from a list of {price,size} levels; `choose` is
    max for bids, min for asks. None if empty/unparseable."""
    if not levels:
        return None
    prices = []
    for lvl in levels:
        try:
            prices.append(float(lvl["price"]))
        except (TypeError, ValueError, KeyError):
            continue
    if not prices:
        return None
    return max(0, min(MICRO, round(choose(prices) * MICRO)))


def fetch_bid_ask_micro(polymarket_token_id: str, *, getter=None) -> tuple[int | None, int | None]:
    """Real Polymarket (best_bid, best_ask) in micro-USDC for one CLOB token id.

    Either element is None on network/parse error or a one-sided/empty book —
    the caller must handle a missing side (skip or fall back to mid). Resolves
    the HTTP helper at call time so tests can monkeypatch `price_oracle.get`.
    """
    g = getter or get
    if not polymarket_token_id:
        return (None, None)
    try:
        resp = g(f"{CLOB_BOOK_URL}?token_id={polymarket_token_id}")
    except Exception as exc:
        log.warning("polymarket book fetch failed for %s: %s", polymarket_token_id, exc)
        return (None, None)
    if not isinstance(resp, dict):
        return (None, None)
    bid = _best_level_micro(resp.get("bids"), max)
    ask = _best_level_micro(resp.get("asks"), min)
    return (bid, ask)


def fetch_mids_for_markets(markets, *, getter=get) -> dict[int, int]:
    """market_id -> mid_micro for every market with a usable Polymarket mid."""
    out: dict[int, int] = {}
    for m in markets:
        mid = fetch_mid_micro(m.polymarket_yes_token_id, getter=getter)
        if mid is not None:
            out[m.market_id] = mid
    return out
