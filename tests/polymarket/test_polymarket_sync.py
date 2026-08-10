from unittest.mock import patch

import pytest

from agentpit.common import check_state
from agentpit.datastructures.condition_id import ConditionId
from agentpit.db.table_read import TableRead
from agentpit.polymarket.conditional_token_framework import ConditionalTokenFramework
from agentpit.polymarket import polymarket_sync
from agentpit.polymarket.polymarket_sync import (
    POLYMARKET_GAMMA_URL,
    _is_market_over,
    _normalize_market_fields,
    _polymarket_to_erc1155_tokens,
    build_create_market_request_from_json,
    create_polymarket_markets_if_needed,
    fetch_all_polymarket_markets,
    fetch_polymarket_market,
)
from tests.db_helpers import fresh_test_conn


@pytest.fixture()
def db():
    """Postgres test database connection with all tables created."""
    conn = fresh_test_conn()
    yield conn
    conn.close()


def test_sync_polymarket_markets_syncs_real_markets_to_db(db):
    """Test syncing live Polymarket markets into a local DB.

    Hits the real Polymarket API and mirrors each market onto the local
    CTF + Exchange — so anvil and the deployed exchange must be up.
    """
    from agentpit.config import Settings
    from agentpit.onchain.admin import OnchainAdmin
    from agentpit.onchain.contracts import Contracts
    from agentpit.onchain.deployment import Deployment
    from agentpit.onchain.web3_client import Web3Client

    settings = Settings()
    deployment = Deployment.load(settings.deployment_path)
    client = Web3Client(settings, deployment)
    admin = OnchainAdmin(client, Contracts(client.web3, deployment))

    # Capture a small, single-page trending set ONCE. `order=volume24hr` is a
    # live, churning feed, so re-fetching between syncs is non-deterministic
    # (the top-N shifts) — capture the upstream set and reuse it so the
    # idempotency check below is stable. A small cap also keeps the on-chain
    # prepareCondition work fast.
    pm_markets = fetch_all_polymarket_markets(
        order="volume24hr", max_markets=25, liquidity_threshold=0
    )
    created_markets = create_polymarket_markets_if_needed(db, pm_markets, admin)

    # We expect many markets to be created, but the exact number varies.
    assert len(created_markets) > 5

    db_markets, total = TableRead.list_markets(db, limit=len(created_markets) + 1)
    assert total == len(created_markets)
    assert len(db_markets) == len(created_markets)

    # list_markets returns newest-first (MARKET_ID DESC), which need not match
    # creation order, so match the synced row by id rather than by position.
    first_synced = created_markets[0]
    first_db = next(m for m in db_markets if m.market_id == first_synced.market_id)

    assert first_db.question == first_synced.question
    assert first_db.description == first_synced.description
    assert len(first_db.erc1155_tokens) > 0

    # Idempotent: re-syncing the SAME captured upstream set adds nothing.
    assert create_polymarket_markets_if_needed(db, pm_markets, admin) == []


def test_build_request_extracts_upstream_token_ids():
    pm_market = {
        "question": "Q",
        "description": "D",
        "id": 99,
        "conditionId": "0xcond",
        "slug": "q",
        "startDate": "2026-01-01T00:00:00Z",
        "endDate": "2026-12-31T00:00:00Z",
        "active": True,
        "closed": False,
        "tokens": [
            {"token_id": "777", "outcome": "Yes"},
            {"token_id": "888", "outcome": "No"},
        ],
    }
    req = build_create_market_request_from_json(pm_market)
    assert req.polymarket_yes_token_id == "777"
    assert req.polymarket_no_token_id == "888"


def test_fetch_all_polymarket_markets_requests_tags(monkeypatch):
    """Without include_tag=true every market comes back with `tags: null`."""
    from agentpit.polymarket import polymarket_sync

    seen: list[str] = []

    def fake_get(url: str):
        seen.append(url)
        return []

    monkeypatch.setattr(polymarket_sync, "get", fake_get)
    polymarket_sync.fetch_all_polymarket_markets(host="https://gamma.test")

    assert seen
    assert "include_tag=true" in seen[0]


# ----- a lapsed deadline is not the same as a finished market ----------------


def _overdue(**over):
    """A market whose stated end date passed two months ago."""
    m = {
        "conditionId": "0x" + "ab" * 32,
        "question": "Will the deadline slip again?",
        "endDate": "2026-06-01T00:00:00Z",
        "liquidity": "19002",
        "volumeNum": "76722445",
        "closed": False,
        "active": True,
        "archived": False,
        "acceptingOrders": True,
    }
    m.update(over)
    return m


def test_an_overdue_market_still_taking_orders_is_kept():
    """The Ethiopia case: endDate 2026-06-01, and $678k traded in the last 24
    hours. The deadline lapsed; the question did not."""
    m = _normalize_market_fields(_overdue())
    assert _is_market_over(m) is False


def test_an_overdue_market_no_longer_taking_orders_is_dropped():
    m = _normalize_market_fields(_overdue(acceptingOrders=False))
    assert _is_market_over(m) is True


def test_without_the_upstream_signal_the_date_still_decides():
    """Older Gamma shapes and fixtures carry no acceptingOrders. Falling back
    to the date keeps their behaviour rather than silently admitting them."""
    m = _overdue()
    del m["acceptingOrders"]
    m = _normalize_market_fields(m)
    assert _is_market_over(m) is True


def test_a_future_deadline_is_never_over_whatever_upstream_says():
    m = _normalize_market_fields(
        _overdue(endDate="2099-01-01T00:00:00Z", acceptingOrders=False)
    )
    assert _is_market_over(m) is False


def test_accepting_orders_is_coerced_from_its_string_forms():
    for raw, expected in (("true", True), ("false", False), (1, True), (0, False)):
        m = _normalize_market_fields(_overdue(acceptingOrders=raw))
        assert m["accepting_orders"] is expected, raw


# ----- an event is one question; half an answer is worse than none ----------


def _sib(name, *, v24, liq=20_000, closed=False, vol=1_000_000):
    """One outcome of a multi-outcome event.

    `vol` (cumulative volumeNum) defaults high so tests that only care about
    the `liq` knob aren't accidentally tripped by the filter's "stronger of
    liquidity or volume" rule. The illiquid-placeholder case below overrides
    it to 0 — a `Person C` nobody has ever traded has zero of both.
    """
    return {
        "conditionId": "0x" + name.encode().hex().ljust(64, "0")[:64],
        "question": f"Will {name} win?",
        "groupItemTitle": name,
        "volume24hr": v24,
        "volumeNum": vol,
        "liquidity": liq,
        "closed": closed,
        "active": True,
        "archived": False,
        "acceptingOrders": True,
        "endDate": "2099-01-01T00:00:00Z",
    }


def _event(*markets):
    return {"id": "77", "slug": "who-wins", "markets": list(markets)}


def _primary(name):
    """The market that qualified in the top-1000 window on its own merit."""
    m = _sib(name, v24=678_000)
    m["events"] = [{"id": "77"}]
    return m


def _fetcher_for(event):
    def fetch(ids, host):
        assert ids == ["77"], ids
        return [event]
    return fetch


def test_the_siblings_of_a_qualifying_market_come_with_it():
    favourite = _primary("Adanech")
    event = _event(favourite, _sib("Abiy", v24=328), _sib("Demeke", v24=1033))
    extra = polymarket_sync.fetch_event_siblings(
        [favourite], cap=12, liquidity_threshold=5000,
        fetcher=_fetcher_for(event),
    )
    assert sorted(m["groupItemTitle"] for m in extra) == ["Abiy", "Demeke"]


def test_the_market_that_already_qualified_is_not_returned_twice():
    favourite = _primary("Adanech")
    event = _event(favourite, _sib("Abiy", v24=328))
    extra = polymarket_sync.fetch_event_siblings(
        [favourite], cap=12, liquidity_threshold=5000,
        fetcher=_fetcher_for(event),
    )
    assert [m["groupItemTitle"] for m in extra] == ["Abiy"]


def test_the_cap_keeps_the_busiest_outcomes():
    favourite = _primary("Adanech")
    others = [_sib(f"P{i}", v24=100 - i) for i in range(10)]
    event = _event(favourite, *others)
    extra = polymarket_sync.fetch_event_siblings(
        [favourite], cap=3, liquidity_threshold=5000,
        fetcher=_fetcher_for(event),
    )
    # cap 3 covers the favourite plus the two busiest siblings.
    assert [m["groupItemTitle"] for m in extra] == ["P0", "P1"]


def test_an_illiquid_placeholder_sibling_is_dropped():
    """Upstream keeps zero-liquidity placeholders for unnamed candidates —
    `Person C`, `Person D`. Four of the Ethiopia event's 33 are exactly that."""
    favourite = _primary("Adanech")
    event = _event(favourite, _sib("Person C", v24=0, liq=0, vol=0))
    extra = polymarket_sync.fetch_event_siblings(
        [favourite], cap=12, liquidity_threshold=5000,
        fetcher=_fetcher_for(event),
    )
    assert extra == []


def test_a_closed_sibling_is_never_pulled():
    favourite = _primary("Adanech")
    event = _event(favourite, _sib("Gone", v24=5000, closed=True))
    extra = polymarket_sync.fetch_event_siblings(
        [favourite], cap=12, liquidity_threshold=5000,
        fetcher=_fetcher_for(event),
    )
    assert extra == []


def test_a_market_with_no_event_contributes_nothing():
    lone = _sib("Solo", v24=678_000)      # no "events" key at all
    assert polymarket_sync.fetch_event_siblings(
        [lone], cap=12, liquidity_threshold=5000,
        fetcher=lambda ids, host: pytest.fail("must not fetch"),
    ) == []
