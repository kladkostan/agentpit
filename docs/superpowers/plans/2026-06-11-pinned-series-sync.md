# Pinned-Series Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Force-sync the current live window of each configured recurring Polymarket series (e.g. *BTC Up or Down 5m*) on a phase-aligned schedule, grouping all windows under one agentpit event, so a high-frequency market is always tradeable regardless of volume rank.

**Architecture:** A new pure module `agentpit/polymarket/pinned.py` resolves the current window slug by grid math, fetches that window's event from Gamma, normalizes its market(s), injects the **series** (not per-window) event metadata so all windows bind to one agentpit event via the existing `bind_market_to_upstream_event`, and reuses `create_polymarket_markets_if_needed` for on-chain prepare + dedup. A phase-aligned lifespan loop in `agentpit/api/app.py` wakes shortly after each window boundary. Resolution + auto-redeem are already handled by the existing resolution-mirror loop — no new code there.

**Tech Stack:** Python 3.13, FastAPI lifespan tasks, pydantic-settings, psycopg (Postgres), local anvil + CTF/Exchange contracts, pytest. Spec: `docs/superpowers/specs/2026-06-11-pinned-series-sync-design.md`.

---

## Background the implementer needs (verified against live Gamma 2026-06-11)

- `GET https://gamma-api.polymarket.com/events?slug={window_slug}` returns a **list** of 0-or-1 event. Use the project's HTTP helper `from py_clob_client.http_helpers.helpers import get` (it sets the UA Gamma requires; raw `urllib` gets 403).
- The current window slug is `f"{base}-{now - (now % interval)}"`. For `base="btc-updown-5m"`, `interval=300`, this yields e.g. `btc-updown-5m-1781193600`.
- The returned event has:
  - `event["markets"]` — a list (1 binary up/down market). **Each market dict carries `clobTokenIds` + `outcomes` as JSON-string fields, NOT a `tokens` field, and has NO `events` field.** Outcomes are `["Up","Down"]`.
  - `event["series"]` — a list with one series dict: `{"id":"10684","slug":"btc-up-or-down-5m","title":"BTC Up or Down 5m","recurrence":"5m","image":"","icon":"","category":null,...}`.
  - top-level event fields: `id` (per-window, e.g. `"580480"`), `slug` (= window slug), `title` (per-window, e.g. `"Bitcoin Up or Down - June 11, 12:00PM-12:05PM ET"`).
- **Why inject the series, not the event:** the per-window event `id` changes every window (`580480`, …), so binding to it makes a new homepage card per window. The series `id` (`10684`) is stable, so binding to it groups every window under one card. `bind_market_to_upstream_event` matches on `polymarket_event_id` (immutable), so a series-shaped events-array entry collapses all windows onto one agentpit event.
- **Why normalize first:** `build_create_market_request_from_json` reads `pm_market["tokens"]` directly and does NOT call `_normalize_market_fields`. The trending path normalizes inside `fetch_all_polymarket_markets`; the pinned path bypasses that, so `sync_pinned_series` must call `_normalize_market_fields` on each window market to build `tokens` from `clobTokenIds`. (Verified: after normalize, `tokens` becomes `[{"token_id":"4769…","outcome":"Up"},{"token_id":"8034…","outcome":"Down"}]`.)
- The `"Up"/"Down"` outcomes mean `_extract_yes_no_token_ids` returns `(None, None)` — harmless. Resolution mirroring keys off `tokens[i].winner` by index, not the yes/no convenience ids.
- Resolution + redeem are already wired: the existing `_resolution_mirror_loop` (every `RESOLUTION_MIRROR_INTERVAL_SECONDS`) calls `mirror_polymarket_resolutions` (by `polymarket_condition_id` via CLOB) + `auto_redeem_resolved_markets`. A closed window is picked up automatically. **This plan adds NO resolution code.**

## File structure

- **Create** `agentpit/polymarket/pinned.py` — all pinned-series logic: parsing, grid math, scheduling math, Gamma fetch, series-entry extraction, and the `sync_pinned_series` orchestrator. One file, one responsibility.
- **Modify** `agentpit/config.py` — add `pinned_series_raw` (+ a `pinned_series` parsed property), `pin_sync_enabled` (validator-defaulted to `sync_enabled`), `pin_sync_offset_seconds`.
- **Modify** `agentpit/api/app.py` — add `_run_pin_sync`, `_pin_sync_loop`, and lifespan wiring + shutdown cancellation.
- **Modify** `.env.example` — document the new knobs.
- **Create** `tests/polymarket/test_pinned.py` — unit tests for the pure functions + the orchestrator (monkeypatched).
- **Create** `tests/polymarket/test_pinned_grouping.py` — DB-level test: two windows of one series → one event.
- **Create** `tests/polymarket/test_pinned_onchain.py` — on-chain integration: fake window event → real prepare → attached to series event.
- **Create** `tests/test_config_pinned.py` — config defaults + parsing.
- **Create** `tests/api/test_pin_sync_wiring.py` — `_run_pin_sync` wiring test.

**Test command:** `.venv/bin/pytest <path> -v` (Postgres `agentpit_test`, anvil `31337`, and deployed contracts must be up for the on-chain test; the pure/DB/config/wiring tests need only Postgres).

**Commit convention:** Do NOT add a `Co-Authored-By` trailer (user preference).

---

## Task 1: Pure module `pinned.py` — parsing, grid math, scheduling, fetch, series extraction

**Files:**
- Create: `agentpit/polymarket/pinned.py`
- Create: `tests/polymarket/test_pinned.py`

- [ ] **Step 1: Write failing unit tests for the pure functions**

Create `tests/polymarket/test_pinned.py`:

```python
import agentpit.polymarket.pinned as pinned
from agentpit.polymarket.pinned import (
    current_window_slug,
    fetch_event_by_slug,
    next_wake_delay,
    parse_pinned_series,
    series_event_metadata,
)


# ----- parse_pinned_series ----------------------------------------------------

def test_parse_pinned_series_single():
    assert parse_pinned_series("btc-updown-5m:300") == [("btc-updown-5m", 300)]


def test_parse_pinned_series_multiple_and_whitespace():
    raw = " btc-updown-5m:300 , eth-updown-5m:900 "
    assert parse_pinned_series(raw) == [
        ("btc-updown-5m", 300),
        ("eth-updown-5m", 900),
    ]


def test_parse_pinned_series_skips_malformed():
    # missing colon, non-int interval, non-positive interval, empty entries
    raw = "btc-updown-5m:300,no-colon,eth-updown-5m:abc,x:0,,sol-updown-15m:900"
    assert parse_pinned_series(raw) == [
        ("btc-updown-5m", 300),
        ("sol-updown-15m", 900),
    ]


def test_parse_pinned_series_empty():
    assert parse_pinned_series("") == []
    assert parse_pinned_series("   ") == []


# ----- current_window_slug ----------------------------------------------------

def test_current_window_slug_grid_math():
    # 1781193601 is 1s past the 1781193600 boundary (a multiple of 300).
    assert (
        current_window_slug("btc-updown-5m", 300, 1781193601)
        == "btc-updown-5m-1781193600"
    )


def test_current_window_slug_exact_boundary():
    assert (
        current_window_slug("btc-updown-5m", 300, 1781193600)
        == "btc-updown-5m-1781193600"
    )


# ----- next_wake_delay --------------------------------------------------------

def test_next_wake_delay_mid_window():
    # 5s past a boundary, align 300, offset 10 -> wake at next boundary + 10.
    assert next_wake_delay(1781193605, 300, 10) == 305.0


def test_next_wake_delay_on_boundary_waits_full_interval():
    # Exactly on a boundary -> next boundary is a full interval away (+offset).
    assert next_wake_delay(1781193600, 300, 10) == 310.0


def test_next_wake_delay_recomputes_no_drift():
    # An overrun that lands just before the next boundary still schedules the
    # NEXT boundary, not a negative/zero delay.
    assert next_wake_delay(1781193899, 300, 10) == 11.0


# ----- series_event_metadata --------------------------------------------------

def test_series_event_metadata_extracts_series_entry():
    event = {
        "id": "580480",
        "slug": "btc-updown-5m-1781193600",
        "title": "Bitcoin Up or Down - June 11, 12:00PM-12:05PM ET",
        "series": [
            {
                "id": "10684",
                "slug": "btc-up-or-down-5m",
                "title": "BTC Up or Down 5m",
                "image": "",
                "icon": "",
                "category": None,
            }
        ],
    }
    meta = series_event_metadata(event)
    assert meta is not None
    # Series id/slug/title — NOT the per-window 580480 / window slug.
    assert meta["id"] == "10684"
    assert meta["slug"] == "btc-up-or-down-5m"
    assert meta["title"] == "BTC Up or Down 5m"


def test_series_event_metadata_none_when_no_series():
    assert series_event_metadata({"id": "1", "slug": "s", "title": "T"}) is None
    assert series_event_metadata({"series": []}) is None


# ----- fetch_event_by_slug ----------------------------------------------------

def test_fetch_event_by_slug_returns_first(monkeypatch):
    monkeypatch.setattr(pinned, "get", lambda url: [{"slug": "s", "title": "T"}])
    assert fetch_event_by_slug("s") == {"slug": "s", "title": "T"}


def test_fetch_event_by_slug_none_on_empty(monkeypatch):
    monkeypatch.setattr(pinned, "get", lambda url: [])
    assert fetch_event_by_slug("s") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/polymarket/test_pinned.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentpit.polymarket.pinned'`.

- [ ] **Step 3: Create `agentpit/polymarket/pinned.py` with the pure functions**

(Leave `sync_pinned_series` for Task 2 — it depends on the orchestration helpers and is tested separately.)

```python
"""Pinned recurring-series sync.

Top-N-by-volume sync cannot capture high-frequency recurring markets (e.g.
*BTC Up or Down 5m*): a single live window has tiny volume while tradeable and
only accumulates volume after it closes. This module pins such series by config
and force-syncs the CURRENT live window of each, grouping every window under one
agentpit event (the series), reusing the existing creation + event-binding path.

See docs/superpowers/specs/2026-06-11-pinned-series-sync-design.md.
"""

import logging

from py_clob_client.http_helpers.helpers import get

from agentpit.datastructures.market import Market
from agentpit.polymarket.polymarket_sync import (
    POLYMARKET_GAMMA_URL,
    _normalize_market_fields,
    create_polymarket_markets_if_needed,
)

logger = logging.getLogger(__name__)


def parse_pinned_series(raw: str) -> list[tuple[str, int]]:
    """Parse ``"base:interval,base:interval"`` into ``[(base, interval), ...]``.

    Malformed entries (missing colon, non-int or non-positive interval, empty)
    are skipped with a warning rather than failing the whole config.
    """
    out: list[tuple[str, int]] = []
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        base, sep, interval_raw = entry.rpartition(":")
        base = base.strip()
        if not sep or not base:
            logger.warning("pinned-series: skipping malformed entry %r", entry)
            continue
        try:
            interval = int(interval_raw.strip())
        except ValueError:
            logger.warning("pinned-series: skipping non-int interval in %r", entry)
            continue
        if interval <= 0:
            logger.warning("pinned-series: skipping non-positive interval in %r", entry)
            continue
        out.append((base, interval))
    return out


def current_window_slug(base: str, interval: int, now: int) -> str:
    """Exact event slug of the window live at ``now`` (grid-aligned)."""
    return f"{base}-{now - (now % interval)}"


def next_wake_delay(now: int, align_interval: int, offset: int) -> float:
    """Seconds until the next ``align_interval`` boundary plus ``offset``.

    Recomputed from the current time each call, so a slow cycle that overruns a
    boundary simply targets the next one — no drift, never negative.
    """
    return float(((now // align_interval + 1) * align_interval + offset) - now)


def fetch_event_by_slug(slug: str) -> dict | None:
    """Fetch a single Gamma event by slug; first element or ``None``."""
    result = get(f"{POLYMARKET_GAMMA_URL}/events?slug={slug}")
    if isinstance(result, list) and result and isinstance(result[0], dict):
        return result[0]
    return None


def _event_entry(src: dict) -> dict | None:
    """Build an ``events[]``-array entry (the shape `_extract_event_metadata`
    consumes) from an event-or-series dict. ``None`` if slug/title are missing.
    """
    slug = src.get("slug")
    title = src.get("title") or src.get("name")
    if not slug or not title:
        return None
    return {
        "id": src.get("id"),
        "slug": str(slug),
        "title": str(title),
        "description": src.get("description") or "",
        "image": src.get("image") or src.get("icon") or None,
        "icon": src.get("icon") or src.get("image") or None,
        "category": src.get("category"),
        "startDate": src.get("startDate") or src.get("startDateIso"),
        "endDate": src.get("endDate") or src.get("endDateIso"),
    }


def series_event_metadata(event: dict) -> dict | None:
    """Build a series-level ``events[]`` entry from ``event["series"][0]``.

    Using the SERIES id/slug/title (stable across windows) — not the per-window
    event — is what groups every window under one agentpit event. ``None`` when
    the event has no usable ``series``.
    """
    series = event.get("series")
    if not isinstance(series, list) or not series or not isinstance(series[0], dict):
        return None
    return _event_entry(series[0])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/polymarket/test_pinned.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Report any new LSP/pyright diagnostics in the changed files, fix in your own lines only, then commit**

```bash
git add agentpit/polymarket/pinned.py tests/polymarket/test_pinned.py
git commit -m "feat(pinned): pure parsing, grid, scheduling + series-entry helpers"
```

---

## Task 2: `sync_pinned_series` orchestrator (+ unit and DB-grouping tests)

**Files:**
- Modify: `agentpit/polymarket/pinned.py`
- Modify: `tests/polymarket/test_pinned.py`
- Create: `tests/polymarket/test_pinned_grouping.py`

- [ ] **Step 1: Append the orchestrator unit test to `tests/polymarket/test_pinned.py`**

```python
# ----- sync_pinned_series (unit, monkeypatched) -------------------------------

def _fake_window_event(window_ts: int, *, pmid: int, cond: str) -> dict:
    """A window event shaped like live Gamma: market carries clobTokenIds (not
    `tokens`) and no `events`; the event carries a `series`."""
    return {
        "id": f"win-{window_ts}",
        "slug": f"btc-updown-5m-{window_ts}",
        "title": f"Bitcoin Up or Down - window {window_ts}",
        "series": [
            {
                "id": "10684",
                "slug": "btc-up-or-down-5m",
                "title": "BTC Up or Down 5m",
            }
        ],
        "markets": [
            {
                "id": pmid,
                "conditionId": cond,
                "question": f"Bitcoin Up or Down - window {window_ts}",
                "description": "d",
                "slug": f"btc-updown-5m-{window_ts}",
                "active": True,
                "closed": False,
                "startDate": "2026-06-11T16:00:00Z",
                "endDate": "2026-06-11T16:05:00Z",
                "clobTokenIds": '["111","222"]',
                "outcomes": '["Up","Down"]',
            }
        ],
    }


def test_sync_pinned_series_injects_series_and_normalizes_tokens(monkeypatch):
    captured = {}

    def fake_fetch(slug):
        return _fake_window_event(1781193600, pmid=42, cond="0x" + "ab" * 32)

    def fake_create(conn, prepared, admin):
        captured["prepared"] = prepared
        return [f"market-{i}" for i in range(len(prepared))]

    monkeypatch.setattr(pinned, "fetch_event_by_slug", fake_fetch)
    monkeypatch.setattr(pinned, "create_polymarket_markets_if_needed", fake_create)

    created = pinned.sync_pinned_series(
        conn="CONN", admin="ADMIN", pinned=[("btc-updown-5m", 300)], now=1781193601
    )

    assert created == ["market-0"]
    prepared = captured["prepared"]
    assert len(prepared) == 1
    # Series grouping injected (id 10684 — NOT the per-window win-... id).
    assert prepared[0]["events"][0]["id"] == "10684"
    # clobTokenIds normalized into a tokens list.
    assert [t["token_id"] for t in prepared[0]["tokens"]] == ["111", "222"]
    assert [t["outcome"] for t in prepared[0]["tokens"]] == ["Up", "Down"]


def test_sync_pinned_series_skips_missing_event(monkeypatch):
    monkeypatch.setattr(pinned, "fetch_event_by_slug", lambda slug: None)
    spy = {"n": 0}
    monkeypatch.setattr(
        pinned,
        "create_polymarket_markets_if_needed",
        lambda *a, **k: spy.__setitem__("n", spy["n"] + 1) or [],
    )
    out = pinned.sync_pinned_series("CONN", "ADMIN", [("btc-updown-5m", 300)], 1)
    assert out == []
    assert spy["n"] == 0  # never reached creation


def test_sync_pinned_series_isolates_failing_series(monkeypatch):
    def fake_fetch(slug):
        if slug.startswith("bad"):
            raise RuntimeError("boom")
        return _fake_window_event(1781193600, pmid=7, cond="0x" + "cd" * 32)

    monkeypatch.setattr(pinned, "fetch_event_by_slug", fake_fetch)
    monkeypatch.setattr(
        pinned, "create_polymarket_markets_if_needed", lambda c, p, a: ["ok"]
    )
    out = pinned.sync_pinned_series(
        "CONN", "ADMIN", [("bad-series", 300), ("btc-updown-5m", 300)], 1781193601
    )
    assert out == ["ok"]  # bad series swallowed, good one still synced
```

- [ ] **Step 2: Run the new unit tests to verify they fail**

Run: `.venv/bin/pytest tests/polymarket/test_pinned.py -k sync_pinned_series -v`
Expected: FAIL — `AttributeError: module 'agentpit.polymarket.pinned' has no attribute 'sync_pinned_series'`.

- [ ] **Step 3: Implement `sync_pinned_series` in `agentpit/polymarket/pinned.py`**

Append to the module:

```python
def sync_pinned_series(
    conn,
    admin,
    pinned: list[tuple[str, int]],
    now: int,
) -> list[Market]:
    """Force-sync the current live window of each pinned series.

    For each ``(base, interval)``: resolve the current window slug, fetch its
    event, normalize the window market(s) (build ``tokens`` from ``clobTokenIds``),
    inject the SERIES event metadata so all windows group under one agentpit event,
    then reuse ``create_polymarket_markets_if_needed`` (on-chain prepare + dedup +
    event binding). Per-series try/except so one bad series never blocks the rest.
    """
    created: list[Market] = []
    for base, interval in pinned:
        try:
            slug = current_window_slug(base, interval, now)
            event = fetch_event_by_slug(slug)
            if event is None:
                logger.info("pin-sync: no event for slug %s (skip)", slug)
                continue
            raw_markets = event.get("markets") or []
            if not raw_markets:
                logger.info("pin-sync: event %s has no markets (skip)", slug)
                continue
            # Series entry groups windows under one card; fall back to the
            # per-window event entry if the series is absent.
            group = series_event_metadata(event) or _event_entry(event)
            if group is None:
                logger.warning("pin-sync: event %s has no bindable metadata", slug)
            prepared: list[dict] = []
            for raw in raw_markets:
                market = _normalize_market_fields(dict(raw))
                if group is not None:
                    market["events"] = [group]
                prepared.append(market)
            created.extend(
                create_polymarket_markets_if_needed(conn, prepared, admin)
            )
        except Exception:
            logger.exception("pin-sync: series %s failed", base)
    return created
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `.venv/bin/pytest tests/polymarket/test_pinned.py -v`
Expected: PASS (all, including the 3 new `sync_pinned_series` tests).

- [ ] **Step 5: Write the DB-grouping test (real Postgres, on-chain prepare faked)**

Create `tests/polymarket/test_pinned_grouping.py`:

```python
"""DB-level: two different windows of one series bind to the SAME agentpit
event (one homepage card). On-chain prepare is faked, so no anvil needed.
"""

import secrets

import agentpit.polymarket.pinned as pinned
import agentpit.polymarket.polymarket_sync as sync
from agentpit.datastructures.condition_id import ConditionId
from agentpit.db.table_read import TableRead
from tests.db_helpers import fresh_test_conn


def _window_event(window_ts: int) -> dict:
    """Two distinct windows of the SAME series (id 10684) — unique market
    id/conditionId/question per window so they don't collide on dedup."""
    nonce = secrets.token_hex(4)
    return {
        "id": f"win-{window_ts}",
        "slug": f"btc-updown-5m-{window_ts}",
        "title": f"Bitcoin Up or Down - {window_ts}",
        "series": [
            {"id": "10684", "slug": "btc-up-or-down-5m", "title": "BTC Up or Down 5m"}
        ],
        "markets": [
            {
                "id": int(secrets.token_hex(4), 16),
                "conditionId": "0x" + secrets.token_hex(32),
                "question": f"Bitcoin Up or Down - {window_ts}-{nonce}",
                "description": "d",
                "slug": f"btc-updown-5m-{window_ts}",
                "active": True,
                "closed": False,
                "startDate": "2026-06-11T16:00:00Z",
                "endDate": "2026-06-11T16:05:00Z",
                "clobTokenIds": '["111","222"]',
                "outcomes": '["Up","Down"]',
            }
        ],
    }


def test_two_windows_of_one_series_share_event(monkeypatch):
    conn = fresh_test_conn()

    # Fake on-chain prepare: deterministic local condition/token ids, no anvil.
    def fake_prepare(admin, question, labels):
        cid = ConditionId("0x" + secrets.token_hex(32))
        toks = [
            (str(int(secrets.token_hex(8), 16)), labels[0]),
            (str(int(secrets.token_hex(8), 16)), labels[1]),
        ]
        return cid, toks

    monkeypatch.setattr(sync, "prepare_market_on_chain", fake_prepare)

    events = iter([_window_event(1781193600), _window_event(1781193900)])
    monkeypatch.setattr(pinned, "fetch_event_by_slug", lambda slug: next(events))

    first = pinned.sync_pinned_series(
        conn, admin=None, pinned=[("btc-updown-5m", 300)], now=1781193601
    )
    second = pinned.sync_pinned_series(
        conn, admin=None, pinned=[("btc-updown-5m", 300)], now=1781193901
    )

    assert len(first) == 1 and len(second) == 1

    m1 = TableRead.read_market(conn, first[0].market_id)
    m2 = TableRead.read_market(conn, second[0].market_id)
    assert m1 is not None and m2 is not None
    assert m1.event_id is not None
    assert m1.event_id == m2.event_id  # one card for both windows

    event = TableRead.get_event_by_slug(conn, "btc-up-or-down-5m")
    assert event is not None
    assert event.polymarket_event_id == "10684"

    conn.close()
```

- [ ] **Step 6: Run the DB-grouping test to verify it passes**

Run: `.venv/bin/pytest tests/polymarket/test_pinned_grouping.py -v`
Expected: PASS.

- [ ] **Step 7: Report any new diagnostics in changed files, fix your own lines, then commit**

```bash
git add agentpit/polymarket/pinned.py tests/polymarket/test_pinned.py tests/polymarket/test_pinned_grouping.py
git commit -m "feat(pinned): sync_pinned_series orchestrator with series grouping"
```

---

## Task 3: Config knobs

**Files:**
- Modify: `agentpit/config.py`
- Create: `tests/test_config_pinned.py`

- [ ] **Step 1: Write the failing config test**

Create `tests/test_config_pinned.py`:

```python
from agentpit.config import Settings


def _settings(monkeypatch, **env):
    for k in (
        "SYNC", "PINNED_SERIES", "PIN_SYNC_ENABLED", "PIN_SYNC_OFFSET_SECONDS",
    ):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)


def test_pin_defaults(monkeypatch):
    s = _settings(monkeypatch)
    assert s.pin_sync_offset_seconds == 10
    assert s.pinned_series == [("btc-updown-5m", 300)]
    # pin_sync_enabled follows SYNC (False by default here).
    assert s.pin_sync_enabled is False


def test_pin_enabled_follows_sync(monkeypatch):
    s = _settings(monkeypatch, SYNC="true")
    assert s.pin_sync_enabled is True


def test_pin_enabled_explicit_override(monkeypatch):
    s = _settings(monkeypatch, SYNC="true", PIN_SYNC_ENABLED="false")
    assert s.pin_sync_enabled is False


def test_pinned_series_parsed_from_env(monkeypatch):
    s = _settings(monkeypatch, PINNED_SERIES="btc-updown-5m:300,eth-updown-5m:900")
    assert s.pinned_series == [("btc-updown-5m", 300), ("eth-updown-5m", 900)]


def test_pinned_series_empty_when_blank(monkeypatch):
    s = _settings(monkeypatch, PINNED_SERIES="")
    assert s.pinned_series == []
```

- [ ] **Step 2: Run the config test to verify it fails**

Run: `.venv/bin/pytest tests/test_config_pinned.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'pin_sync_offset_seconds'`.

- [ ] **Step 3: Add the fields, validator default, and parsed property to `agentpit/config.py`**

Add these fields immediately after the `auto_redeem_enabled` field (around line 43), before the existing `@model_validator`:

```python
    # Pinned-series sync (force-sync the current window of recurring markets).
    pinned_series_raw: str = Field(
        default="btc-updown-5m:300", validation_alias="PINNED_SERIES"
    )
    pin_sync_enabled: bool | None = Field(
        default=None, validation_alias="PIN_SYNC_ENABLED"
    )
    pin_sync_offset_seconds: int = Field(
        default=10, validation_alias="PIN_SYNC_OFFSET_SECONDS"
    )
```

Add this validator method right after the existing `_default_resolution_mirror_enabled` validator (after line 50):

```python
    @model_validator(mode="after")
    def _default_pin_sync_enabled(self) -> "Settings":
        # When PIN_SYNC_ENABLED is unset, follow SYNC.
        if self.pin_sync_enabled is None:
            self.pin_sync_enabled = self.sync_enabled
        return self

    @property
    def pinned_series(self) -> list[tuple[str, int]]:
        """Parsed ``[(base, interval), ...]`` from ``PINNED_SERIES``.

        Imported lazily to avoid a config<->polymarket import cycle.
        """
        from agentpit.polymarket.pinned import parse_pinned_series

        return parse_pinned_series(self.pinned_series_raw)
```

- [ ] **Step 4: Run the config test to verify it passes**

Run: `.venv/bin/pytest tests/test_config_pinned.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Verify the existing config suite still passes**

Run: `.venv/bin/pytest tests/test_config_sync_redeem.py tests/test_config_liquidity.py -v`
Expected: PASS (no regressions).

- [ ] **Step 6: Report diagnostics in changed files, fix your own lines, then commit**

```bash
git add agentpit/config.py tests/test_config_pinned.py
git commit -m "feat(config): pinned-series knobs (PINNED_SERIES, PIN_SYNC_*)"
```

---

## Task 4: App lifespan wiring

**Files:**
- Modify: `agentpit/api/app.py`
- Create: `tests/api/test_pin_sync_wiring.py`

- [ ] **Step 1: Write the failing wiring test**

Create `tests/api/test_pin_sync_wiring.py`:

```python
import agentpit.api.app as app_mod


def test_run_pin_sync_calls_sync_inside_write(monkeypatch):
    calls = {"n": 0, "conn": None, "pinned": None, "now": None}

    class FakeSettings:
        pinned_series = [("btc-updown-5m", 300)]

    class FakeDb:
        def write(self):
            from contextlib import contextmanager

            @contextmanager
            def _cm():
                yield "CONN"

            return _cm()

    def fake_sync(conn, admin, pinned, now):
        calls["n"] += 1
        calls["conn"] = conn
        calls["pinned"] = pinned
        calls["now"] = now
        return ["m1", "m2", "m3"]

    monkeypatch.setattr(app_mod, "sync_pinned_series", fake_sync)

    count = app_mod._run_pin_sync(
        FakeDb(), admin="ADMIN", settings=FakeSettings()  # type: ignore[arg-type]
    )

    assert count == 3
    assert calls["n"] == 1
    assert calls["conn"] == "CONN"
    assert calls["pinned"] == [("btc-updown-5m", 300)]
    assert isinstance(calls["now"], int)
```

- [ ] **Step 2: Run the wiring test to verify it fails**

Run: `.venv/bin/pytest tests/api/test_pin_sync_wiring.py -v`
Expected: FAIL — `AttributeError: module 'agentpit.api.app' has no attribute 'sync_pinned_series'` (and `_run_pin_sync`).

- [ ] **Step 3: Add the import to `agentpit/api/app.py`**

Replace the existing `pinned`-less polymarket import block (lines 42-46):

```python
from agentpit.polymarket.polymarket_sync import (
    auto_redeem_resolved_markets,
    fetch_and_sync_polymarket_markets,
    mirror_polymarket_resolutions,
)
```

with:

```python
from agentpit.polymarket.pinned import next_wake_delay, sync_pinned_series
from agentpit.polymarket.polymarket_sync import (
    auto_redeem_resolved_markets,
    fetch_and_sync_polymarket_markets,
    mirror_polymarket_resolutions,
)
```

- [ ] **Step 4: Add `_run_pin_sync` and `_pin_sync_loop` after `_resolution_mirror_loop` (after line 116)**

```python
def _run_pin_sync(db: DbSession, admin: OnchainAdmin, settings: Settings) -> int:
    now = int(time.time())
    with db.write() as conn:
        created = sync_pinned_series(conn, admin, settings.pinned_series, now)
    return len(created)


async def _pin_sync_loop(
    db: DbSession, admin: OnchainAdmin, settings: Settings
) -> None:
    # Align to the smallest configured interval; wake `offset` seconds after
    # each boundary so the now-live window is synced promptly.
    align = min(interval for _, interval in settings.pinned_series)
    while True:
        try:
            count = await asyncio.to_thread(_run_pin_sync, db, admin, settings)
            log.info("Pin-sync: synced %d current window(s)", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Pin-sync failed")
        await asyncio.sleep(
            next_wake_delay(int(time.time()), align, settings.pin_sync_offset_seconds)
        )
```

- [ ] **Step 5: Wire the lifespan task — add after the `resolution_task` block (after line 250), before `try: yield`**

```python
        pin_task: asyncio.Task | None = None
        if settings.pin_sync_enabled and settings.pinned_series:
            align = min(i for _, i in settings.pinned_series)
            log.info(
                "Pin-sync enabled (%d series, align=%ds, offset=%ds)",
                len(settings.pinned_series),
                align,
                settings.pin_sync_offset_seconds,
            )
            pin_task = asyncio.create_task(
                _pin_sync_loop(db_session, onchain_admin, settings)
            )
        else:
            log.info(
                "Pin-sync disabled (set PIN_SYNC_ENABLED=true/SYNC and PINNED_SERIES)"
            )
```

- [ ] **Step 6: Add `pin_task` to the shutdown cancellation tuple**

Change the `finally` loop (line 255) from:

```python
            for task in (sync_task, snapshot_task, resolution_task, *mirror_tasks):
```

to:

```python
            for task in (
                sync_task,
                snapshot_task,
                resolution_task,
                pin_task,
                *mirror_tasks,
            ):
```

- [ ] **Step 7: Run the wiring test to verify it passes**

Run: `.venv/bin/pytest tests/api/test_pin_sync_wiring.py -v`
Expected: PASS.

- [ ] **Step 8: Verify the app still imports and the resolution-loop wiring test still passes**

Run: `.venv/bin/pytest tests/api/test_resolution_loop_wiring.py tests/api/test_pin_sync_wiring.py -v`
Expected: PASS (no regressions; app module imports cleanly).

- [ ] **Step 9: Report diagnostics in changed files, fix your own lines, then commit**

```bash
git add agentpit/api/app.py tests/api/test_pin_sync_wiring.py
git commit -m "feat(app): phase-aligned pin-sync lifespan loop"
```

---

## Task 5: On-chain integration test

**Files:**
- Create: `tests/polymarket/test_pinned_onchain.py`

(Requires anvil `31337` + deployed CTF/Exchange + Postgres `agentpit_test`. Mirrors the real-admin setup in `tests/polymarket/test_polymarket_sync.py`, but the Gamma fetch is faked for determinism.)

- [ ] **Step 1: Write the on-chain integration test**

Create `tests/polymarket/test_pinned_onchain.py`:

```python
"""On-chain: a pinned current-window event is created, prepared on the local
CTF, and attached to its series event. Real anvil + deployed contracts.
The Gamma fetch is faked so the test is deterministic (no live Polymarket).
"""

import secrets

import agentpit.polymarket.pinned as pinned
from agentpit.config import Settings
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_read import TableRead
from agentpit.onchain.admin import OnchainAdmin
from agentpit.onchain.contracts import Contracts
from agentpit.onchain.deployment import Deployment
from agentpit.onchain.web3_client import Web3Client
from tests.db_helpers import fresh_test_conn


def _admin() -> OnchainAdmin:
    settings = Settings()
    deployment = Deployment.load(settings.deployment_path)
    client = Web3Client(settings, deployment)
    return OnchainAdmin(client, Contracts(client.web3, deployment))


def _fake_window_event() -> dict:
    nonce = secrets.token_hex(6)
    return {
        "id": "win-1",
        "slug": "btc-updown-5m-1781193600",
        "title": "Bitcoin Up or Down - window",
        "series": [
            {"id": "10684", "slug": "btc-up-or-down-5m", "title": "BTC Up or Down 5m"}
        ],
        "markets": [
            {
                "id": int(secrets.token_hex(4), 16),
                "conditionId": "0x" + secrets.token_hex(32),
                "question": f"Bitcoin Up or Down - {nonce}?",
                "description": "d",
                "slug": "btc-updown-5m-1781193600",
                "active": True,
                "closed": False,
                "startDate": "2026-06-11T16:00:00Z",
                "endDate": "2026-06-11T16:05:00Z",
                "clobTokenIds": '["111","222"]',
                "outcomes": '["Up","Down"]',
            }
        ],
    }


def test_pin_sync_prepares_window_and_groups_under_series(monkeypatch):
    conn = fresh_test_conn()
    admin = _admin()

    # Capture the upstream conditionId from the SAME event the sync consumes,
    # so the "local prepare overrode it" assertion is meaningful.
    event = _fake_window_event()
    upstream_cond = event["markets"][0]["conditionId"]
    monkeypatch.setattr(pinned, "fetch_event_by_slug", lambda slug: event)

    created = pinned.sync_pinned_series(
        conn, admin, pinned=[("btc-updown-5m", 300)], now=1781193601
    )

    assert len(created) == 1
    market = created[0]
    # On-chain prepare overrode the upstream conditionId with a locally-derived
    # one; the market is ACTIVE and tradeable.
    assert market.condition_id.value != upstream_cond
    assert market.market_state == MarketState.ACTIVE
    assert len(market.erc1155_tokens) == 2

    re = TableRead.read_market(conn, market.market_id)
    assert re is not None and re.event_id is not None

    event_row = TableRead.get_event_by_slug(conn, "btc-up-or-down-5m")
    assert event_row is not None
    assert event_row.event_id == re.event_id
    assert event_row.polymarket_event_id == "10684"

    conn.close()
```

- [ ] **Step 2: Run the on-chain test to verify it passes**

Run: `.venv/bin/pytest tests/polymarket/test_pinned_onchain.py -v`
Expected: PASS (anvil performs a real `prepareCondition` + `registerToken`).

If it fails with `condition not prepared`/balance/RPC errors, the local chain/DB are out of sync — run `scripts/db_reset.sh` and restart anvil + contracts, then re-run. (Documented operational fix; not a code bug.)

- [ ] **Step 3: Commit**

```bash
git add tests/polymarket/test_pinned_onchain.py
git commit -m "test(pinned): on-chain prepare + series grouping integration"
```

---

## Task 6: Document the knobs and run the full pinned suite

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Add the pinned-series knobs to `.env.example`**

Insert after the `AUTO_REDEEM_ENABLED=true` line (after line 12):

```bash
# Pinned-series sync: force-sync the current window of recurring markets
# (e.g. BTC Up or Down 5m) on a phase-aligned schedule, regardless of volume
# rank. Comma-separated `event_slug_base:interval_seconds`. Enabled-gate
# defaults to SYNC when unset.
PINNED_SERIES=btc-updown-5m:300
PIN_SYNC_ENABLED=true
PIN_SYNC_OFFSET_SECONDS=10
```

- [ ] **Step 2: Run the entire pinned-series test set plus the touched neighbors**

Run:
```bash
.venv/bin/pytest \
  tests/polymarket/test_pinned.py \
  tests/polymarket/test_pinned_grouping.py \
  tests/polymarket/test_pinned_onchain.py \
  tests/test_config_pinned.py \
  tests/api/test_pin_sync_wiring.py \
  tests/test_config_sync_redeem.py \
  tests/api/test_resolution_loop_wiring.py \
  -v
```
Expected: PASS (all).

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "docs(env): document pinned-series sync knobs"
```

---

## Final verification (after all tasks)

- [ ] **Run the full suite to confirm no regressions**

Run: `.venv/bin/pytest -q`
Expected: PASS (existing green count + the new pinned tests). Investigate any failure before finishing the branch.

- [ ] **Dispatch a final code review of the whole pinned-series change, then use superpowers:finishing-a-development-branch.**

---

## Spec-coverage map (self-review)

| Spec §                            | Covered by |
|-----------------------------------|------------|
| §3 `PINNED_SERIES`/`PIN_SYNC_ENABLED`/`PIN_SYNC_OFFSET_SECONDS` | Task 3 |
| §4 `parse_pinned_series`          | Task 1 |
| §4 `current_window_slug`          | Task 1 |
| §4 `fetch_event_by_slug`          | Task 1 |
| §4 `series_event_metadata`        | Task 1 |
| §4 `next_wake_delay` (no drift)   | Task 1 |
| §4 `sync_pinned_series` (+ normalize, series injection, per-series isolation, fallback) | Task 2 |
| §5 `_run_pin_sync` / `_pin_sync_loop` / lifespan wiring + shutdown | Task 4 |
| §6 series-event grouping (one card) | Task 2 (DB), Task 5 (on-chain) |
| §7 lifecycle via existing resolution+redeem loop | No new code (existing loop); verified design in §Background |
| §8 failure modes (missing slug, isolation, overrun, no-series fallback) | Tasks 1–2 tests |
| §9 testing (unit, DB, on-chain, wiring) | Tasks 1–5 |
| §11 deferred follow-ups           | Out of scope (documented) |
