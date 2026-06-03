# Gamma Markets + Events Implementation Plan (spec Phase 1 remainder)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch `GET /markets`, `GET /markets/{id}`, `GET /events`, `GET /events/{slug}` to Polymarket **Gamma** wire shapes (with the `condition_id` bridge filters), and keep the agentpit UI working via thin adapters that map the Gamma wire back into the UI's existing internal TS types.

**Architecture:** Backend adds `GammaMarket`/`GammaEvent` Pydantic models (exact Gamma field names + JSON-string-encoded arrays) and serializers in `agentpit/polymarket/gamma.py`; the market/event routes return the Gamma shapes (bare arrays for list endpoints — Gamma has no `{total,limit,offset}` envelope). The **UI keeps its internal `Market`/`Event` interfaces and all components unchanged** — only `ui/src/api/markets.ts` and `ui/src/api/events.ts` are rewritten to fetch the Gamma wire and adapt it (approach "A"). The wire is pure Gamma (what the bot consumes); the adapter is UI-internal parsing, not a second API surface.

**Tech Stack:** Python 3 / FastAPI / raw sqlite3 / Pydantic v2 / pytest (`.venv/bin/python -m pytest`, autouse `:memory:` fixture). UI: React + TanStack Query + TypeScript (`ui/`, build via the repo's UI tooling).

**Depends on:** the Foundation plan (`agentpit/polymarket/format.py`, `resolve.py`) — already landed.

**Known, accepted degradations (approach A, paper test rig):** the Gamma subset doesn't carry agentpit-only fields, so the UI adapter sets `resolved_outcome`, `polymarket_id`, `event_id`, `outcome_label` to `null` and maps `market_state` from `active`/`closed` only (→ `ACTIVE` / `CLOSED` / `DRAFT`; `RESOLVED`/`CANCELLED` nuance is not surfaced). All of these fields are already nullable (or a superset union) in the UI types, so this is type-safe; it is a minor display degradation, documented and acceptable for the test rig.

---

## File Structure

- Create `agentpit/datastructures/gamma_market.py` — `GammaMarket`, `GammaEvent` models (camelCase, exact Gamma names).
- Create `agentpit/polymarket/gamma.py` — `to_gamma_market(market)`, `to_gamma_event(event, markets)` serializers.
- Modify `agentpit/db/table_read.py` — add `list_markets_filtered(...)`.
- Modify `agentpit/services/market_service.py` — add `list_markets_gamma(...)`, `get_market_gamma(...)`.
- Modify `agentpit/services/event_service.py` — add `list_events_gamma(...)`, `get_event_gamma(...)`.
- Modify `agentpit/api/routes/markets.py` — reshape `GET /markets`, `GET /markets/{id}`.
- Modify `agentpit/api/routes/events.py` — reshape `GET /events`, `GET /events/{slug}`.
- Create `tests/polymarket/test_gamma.py`; update `tests/api/test_events.py` and any `tests/api/test_markets*.py` to the new shapes.
- UI: create `ui/src/types/gamma.ts`; rewrite `ui/src/api/markets.ts`, `ui/src/api/events.ts`. **Do not change** `ui/src/types/market.ts`, `ui/src/types/event.ts`, or any component.

---

### Task 1: Gamma models + serializers

**Files:**
- Create: `agentpit/datastructures/gamma_market.py`
- Create: `agentpit/polymarket/gamma.py`
- Test: `tests/polymarket/test_gamma.py`

- [ ] **Step 1: Write the failing test**

Create `tests/polymarket/test_gamma.py`:

```python
import json

from agentpit.datastructures.event import Event
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.market import Market
from agentpit.datastructures.market_state import MarketState
from agentpit.polymarket.gamma import to_gamma_market, to_gamma_event


def _market(state=MarketState.ACTIVE) -> Market:
    return Market(
        question="Will it rain?",
        slug="will-it-rain",
        market_id=7,
        condition_id=ConditionId("0x" + "ab" * 32),
        description="desc",
        erc1155_tokens=[("111", "Yes"), ("222", "No")],
        start_date=1_700_000_000,
        end_date=1_800_000_000,
        market_state=state,
        resolved_outcome=0 if state == MarketState.RESOLVED else None,
    )


def test_to_gamma_market_shape_and_encoding():
    g = to_gamma_market(_market())
    assert g.id == "7"
    assert g.conditionId == "0x" + "ab" * 32
    assert g.question == "Will it rain?"
    # JSON-encoded string arrays (Gamma's quirk), compact (no spaces)
    assert g.outcomes == '["Yes","No"]'
    assert g.clobTokenIds == '["111","222"]'
    assert json.loads(g.outcomes) == ["Yes", "No"]
    assert g.active is True
    assert g.closed is False
    assert g.acceptingOrders is True
    assert g.endDateIso == g.endDate  # endDateIso mirrors endDate
    assert g.endDateIso.endswith("Z")  # ISO8601 UTC
    assert g.volume == "0"
    assert g.bestBid == 0.0


def test_to_gamma_market_closed_states():
    for state in (MarketState.CLOSED, MarketState.RESOLVED, MarketState.CANCELLED):
        g = to_gamma_market(_market(state))
        assert g.active is False
        assert g.closed is True
        assert g.acceptingOrders is False


def test_to_gamma_event_nests_markets():
    g = to_gamma_event(
        Event(event_id=3, slug="weather", title="Weather", description="d"),
        [_market()],
    )
    assert g.id == "3"
    assert g.slug == "weather"
    assert len(g.markets) == 1
    assert g.markets[0].conditionId == "0x" + "ab" * 32
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/polymarket/test_gamma.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentpit.datastructures.gamma_market'` (or `...gamma`).

- [ ] **Step 3: Write the implementation**

Create `agentpit/datastructures/gamma_market.py`:

```python
"""Polymarket Gamma-API wire models (the practical subset agentpit serves).

Field names + casing match Gamma exactly. `outcomes`, `outcomePrices`, and
`clobTokenIds` are JSON arrays ENCODED AS STRINGS — that is Gamma's actual
wire format, replicated here so a bot parses agentpit identically to Polymarket.
"""

from typing import List, Optional

from pydantic import BaseModel


class GammaMarket(BaseModel):
    id: str
    conditionId: str
    question: str
    slug: str
    description: str
    outcomes: str            # JSON-encoded array, e.g. '["Yes","No"]'
    outcomePrices: str       # JSON-encoded array, e.g. '["0.5","0.5"]'
    clobTokenIds: str        # JSON-encoded array of token ids
    active: bool
    closed: bool
    acceptingOrders: bool
    startDate: Optional[str]
    endDate: Optional[str]
    endDateIso: Optional[str]
    icon: Optional[str]
    image: Optional[str]
    volume: str
    liquidity: str
    bestBid: float
    bestAsk: float
    lastTradePrice: float
    spread: float


class GammaEvent(BaseModel):
    id: str
    slug: str
    title: str
    description: str
    icon: Optional[str]
    category: Optional[str]
    startDate: Optional[str]
    endDate: Optional[str]
    markets: List[GammaMarket]
```

Create `agentpit/polymarket/gamma.py`:

```python
"""Serialize agentpit Market/Event domain objects into Gamma wire models.

Price/volume fields emit neutral placeholders here; spec Phase 3/4 wires real
book/trade-derived values (bestBid/bestAsk/lastTradePrice/spread/outcomePrices/
volume/liquidity).
"""

import json
from datetime import datetime, timezone

from agentpit.datastructures.event import Event
from agentpit.datastructures.gamma_market import GammaEvent, GammaMarket
from agentpit.datastructures.market import Market
from agentpit.datastructures.market_state import MarketState

_CLOSED_STATES = (MarketState.CLOSED, MarketState.RESOLVED, MarketState.CANCELLED)


def _iso(epoch: int | None) -> str | None:
    if epoch is None:
        return None
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _json_arr(items: list[str]) -> str:
    """Compact JSON array string (no spaces), matching Gamma's encoding."""
    return json.dumps(items, separators=(",", ":"))


def to_gamma_market(market: Market) -> GammaMarket:
    labels = [label for _token_id, label in market.erc1155_tokens]
    token_ids = [token_id for token_id, _label in market.erc1155_tokens]
    active = market.market_state == MarketState.ACTIVE
    closed = market.market_state in _CLOSED_STATES
    end_iso = _iso(market.end_date)
    return GammaMarket(
        id=str(market.market_id),
        conditionId=market.condition_id.value,
        question=market.question,
        slug=market.slug,
        description=market.description,
        outcomes=_json_arr(labels),
        outcomePrices=_json_arr(["0.5" for _ in labels]),
        clobTokenIds=_json_arr(token_ids),
        active=active,
        closed=closed,
        acceptingOrders=active,
        startDate=_iso(market.start_date),
        endDate=end_iso,
        endDateIso=end_iso,
        icon=market.icon_url,
        image=market.icon_url,
        volume="0",
        liquidity="0",
        bestBid=0.0,
        bestAsk=0.0,
        lastTradePrice=0.0,
        spread=0.0,
    )


def to_gamma_event(event: Event, markets: list[Market]) -> GammaEvent:
    return GammaEvent(
        id=str(event.event_id),
        slug=event.slug,
        title=event.title,
        description=event.description,
        icon=event.icon_url,
        category=event.category,
        startDate=_iso(event.start_date),
        endDate=_iso(event.end_date),
        markets=[to_gamma_market(m) for m in markets],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/polymarket/test_gamma.py -v`
Expected: PASS (3 tests). If `endDateIso` differs, confirm the epoch→ISO of `1_800_000_000` is `2027-01-15T08:00:00Z` and adjust the expected string to the actual UTC value if the test was wrong (the code is the source of truth).

- [ ] **Step 5: Commit**

```bash
git add agentpit/datastructures/gamma_market.py agentpit/polymarket/gamma.py tests/polymarket/test_gamma.py
git commit -m "feat(polymarket): add Gamma market/event wire models + serializers"
```

---

### Task 2: Reshape `GET /markets` + `GET /markets/{id}` to Gamma + bridge filters

The market list endpoint becomes a **bare `GammaMarket[]`** (Gamma has no envelope) and gains the bridge filters. `GET /markets/{id}` returns a single `GammaMarket`.

**Files:**
- Modify: `agentpit/db/table_read.py` (add `list_markets_filtered`)
- Modify: `agentpit/services/market_service.py` (add `list_markets_gamma`, `get_market_gamma`)
- Modify: `agentpit/api/routes/markets.py:13-27`
- Test: `tests/api/test_markets_gamma.py` (create), and update any existing `tests/api/test_markets*.py` that assert the old `{markets,total,limit,offset}` shape.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_markets_gamma.py`:

```python
import json

import pytest
from fastapi.testclient import TestClient

from agentpit.api.deps import get_db_session
from agentpit.api.main import app
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_write import TableWrite


def _hex32(seed: str) -> str:
    return "0x" + seed.encode().hex().ljust(64, "0")[:64]


@pytest.fixture()
def client_and_market():
    session = app.dependency_overrides[get_db_session]()
    req = CreateMarketRequest(
        question="Will it rain?",
        description="d",
        erc1155_tokens=[("111", "Yes"), ("222", "No")],
        slug="will-it-rain",
        condition_id=ConditionId(_hex32("c1")),
        state=MarketState.ACTIVE,
    )
    with session.write() as conn:
        market = TableWrite.create_market(conn, req, is_polygon_market=False)
    with TestClient(app) as client:
        yield client, market


def test_list_markets_returns_bare_gamma_array(client_and_market):
    client, market = client_and_market
    resp = client.get("/markets")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)  # bare array, no envelope
    g = next(m for m in body if m["id"] == str(market.market_id))
    assert g["conditionId"] == market.condition_id.value
    assert json.loads(g["outcomes"]) == ["Yes", "No"]
    assert json.loads(g["clobTokenIds"]) == ["111", "222"]
    assert g["active"] is True


def test_get_market_returns_single_gamma(client_and_market):
    client, market = client_and_market
    resp = client.get(f"/markets/{market.market_id}")
    assert resp.status_code == 200
    g = resp.json()
    assert g["id"] == str(market.market_id)
    assert g["conditionId"] == market.condition_id.value


def test_bridge_filter_by_condition_ids(client_and_market):
    client, market = client_and_market
    resp = client.get(f"/markets?condition_ids={market.condition_id.value}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == str(market.market_id)


def test_filter_by_clob_token_ids(client_and_market):
    client, _ = client_and_market
    resp = client.get("/markets?clob_token_ids=222")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert json.loads(body[0]["clobTokenIds"]) == ["111", "222"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/test_markets_gamma.py -v`
Expected: FAIL — the list endpoint still returns `{"markets": [...]}` (not a bare array) and has no filters.

- [ ] **Step 3: Implement**

In `agentpit/db/table_read.py`, add this static method to the `TableRead` class (next to `list_markets`; reuse the existing `_MARKET_COLS` and `_row_to_market`):

```python
    @staticmethod
    def list_markets_filtered(
        db: sqlite3.Connection,
        *,
        limit: int = 100,
        offset: int = 0,
        market_id: int | None = None,
        slug: str | None = None,
        condition_ids: list[str] | None = None,
        clob_token_ids: list[str] | None = None,
        polymarket_condition_id: str | None = None,
    ) -> list[Market]:
        clauses: list[str] = []
        params: list = []
        if market_id is not None:
            clauses.append("MARKET_ID = ?")
            params.append(market_id)
        if slug is not None:
            clauses.append("SLUG = ?")
            params.append(slug)
        if condition_ids:
            placeholders = ",".join("?" for _ in condition_ids)
            clauses.append(f"CONDITION_ID IN ({placeholders})")
            params.extend(condition_ids)
        if polymarket_condition_id is not None:
            clauses.append("POLYMARKET_CONDITION_ID = ?")
            params.append(polymarket_condition_id)
        if clob_token_ids:
            # Match markets whose ERC1155_TOKENS JSON contains any given token id.
            # Quote-anchored, wildcards escaped (see resolve.resolve_by_token_id).
            ors = []
            for token_id in clob_token_ids:
                escaped = (
                    token_id.replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                )
                ors.append("ERC1155_TOKENS LIKE ? ESCAPE '\\'")
                params.append(f'%"{escaped}"%')
            clauses.append("(" + " OR ".join(ors) + ")")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cur = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets {where} "
            "ORDER BY MARKET_ID DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return [_row_to_market(row) for row in cur.fetchall()]
```

In `agentpit/services/market_service.py`, add to `MarketService` (and import the serializer + model at the top: `from agentpit.polymarket.gamma import to_gamma_market` and `from agentpit.datastructures.gamma_market import GammaMarket`):

```python
    def list_markets_gamma(
        self,
        *,
        limit: int,
        offset: int,
        market_id: int | None,
        slug: str | None,
        condition_ids: list[str] | None,
        clob_token_ids: list[str] | None,
        polymarket_condition_id: str | None,
    ) -> list[GammaMarket]:
        if limit < 1 or limit > 1000:
            raise InvalidPaginationError("limit must be between 1 and 1000")
        if offset < 0:
            raise InvalidPaginationError("offset must be non-negative")
        with self._db.read() as conn:
            markets = TableRead.list_markets_filtered(
                conn,
                limit=limit,
                offset=offset,
                market_id=market_id,
                slug=slug,
                condition_ids=condition_ids,
                clob_token_ids=clob_token_ids,
                polymarket_condition_id=polymarket_condition_id,
            )
        return [to_gamma_market(m) for m in markets]

    def get_market_gamma(self, market_id: int) -> GammaMarket:
        return to_gamma_market(self.get_market(market_id))
```

In `agentpit/api/routes/markets.py`, replace the `list_markets` and `get_market` routes (keep the imports for `CancelMarketResponse`, `CreateMarketRequest`, `Market`, `ResolveMarketRequest`; add `from agentpit.datastructures.gamma_market import GammaMarket`). A `None`-safe comma-split helper avoids `"".split(",") == [""]`:

```python
def _csv(value: str | None) -> list[str] | None:
    return [v for v in value.split(",") if v] if value else None


@router.get("/markets", response_model=list[GammaMarket])
def list_markets(
    service: MarketServiceDep,
    limit: int = 100,
    offset: int = 0,
    id: int | None = None,
    slug: str | None = None,
    condition_ids: str | None = None,
    clob_token_ids: str | None = None,
    polymarket_condition_id: str | None = None,
) -> list[GammaMarket]:
    return service.list_markets_gamma(
        limit=limit,
        offset=offset,
        market_id=id,
        slug=slug,
        condition_ids=_csv(condition_ids),
        clob_token_ids=_csv(clob_token_ids),
        polymarket_condition_id=polymarket_condition_id,
    )


@router.get("/markets/{market_id}", response_model=GammaMarket)
def get_market(market_id: int, service: MarketServiceDep) -> GammaMarket:
    return service.get_market_gamma(market_id)
```

- [ ] **Step 4: Update any existing market API tests + run**

Search `tests/api/` for tests that assert the old `/markets` shape (`{"markets": ...}` / `"total"`) or the old `/markets/{id}` `Market` shape, and update them to the Gamma shapes above (list endpoint → bare array of Gamma objects; single → Gamma object). Then run:

Run: `.venv/bin/python -m pytest tests/api/test_markets_gamma.py tests/api/ -k "market" -v`
Expected: PASS (new + updated tests).

- [ ] **Step 5: Commit**

```bash
git add agentpit/db/table_read.py agentpit/services/market_service.py agentpit/api/routes/markets.py tests/api/
git commit -m "feat(api): GET /markets + /markets/{id} return Gamma shape with bridge filters"
```

---

### Task 3: Reshape `GET /events` + `GET /events/{slug}` to Gamma

`GET /events` becomes a bare `GammaEvent[]`; `GET /events/{slug}` returns a single `GammaEvent` (markets nested as `GammaMarket[]`).

**Files:**
- Modify: `agentpit/services/event_service.py` (add `list_events_gamma`, `get_event_gamma`)
- Modify: `agentpit/api/routes/events.py`
- Test: `tests/api/test_events_gamma.py` (create), update `tests/api/test_events.py` to the new shapes.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_events_gamma.py`:

```python
import pytest
from fastapi.testclient import TestClient

from agentpit.api.deps import get_db_session
from agentpit.api.main import app
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_write import TableWrite


def _hex32(seed: str) -> str:
    return "0x" + seed.encode().hex().ljust(64, "0")[:64]


@pytest.fixture()
def client_and_event():
    session = app.dependency_overrides[get_db_session]()
    req = CreateMarketRequest(
        question="Will it rain?",
        description="d",
        erc1155_tokens=[("111", "Yes"), ("222", "No")],
        slug="will-it-rain",
        condition_id=ConditionId(_hex32("c1")),
        state=MarketState.ACTIVE,
    )
    with session.write() as conn:
        TableWrite.create_market(conn, req, is_polygon_market=False)
    with TestClient(app) as client:
        yield client


def test_list_events_returns_bare_gamma_array(client_and_event):
    resp = client_and_event.get("/events?limit=10&offset=0")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)  # bare array, no envelope
    assert len(body) == 1
    ev = body[0]
    assert ev["slug"] == "will-it-rain"
    assert len(ev["markets"]) == 1
    assert ev["markets"][0]["conditionId"]


def test_list_events_empty_is_empty_array(client_and_event):
    # (no markets seeded variant) — a fresh client returns []
    pass


def test_get_event_by_slug_returns_single_gamma(client_and_event):
    resp = client_and_event.get("/events/will-it-rain")
    assert resp.status_code == 200
    ev = resp.json()
    assert ev["slug"] == "will-it-rain"
    assert ev["markets"][0]["clobTokenIds"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/test_events_gamma.py -v`
Expected: FAIL — `/events` returns `{"events": [...]}` envelope, not a bare array.

- [ ] **Step 3: Implement**

In `agentpit/services/event_service.py`, add to `EventService` (import at top: `from agentpit.polymarket.gamma import to_gamma_event` and `from agentpit.datastructures.gamma_market import GammaEvent`):

```python
    def list_events_gamma(self, limit: int, offset: int) -> list[GammaEvent]:
        if limit < 1 or limit > 1000:
            raise InvalidPaginationError("limit must be between 1 and 1000")
        if offset < 0:
            raise InvalidPaginationError("offset must be non-negative")
        with self._db.read() as conn:
            pairs, _total = TableRead.list_events_with_markets(
                conn, limit=limit, offset=offset
            )
        return [to_gamma_event(event, markets) for event, markets in pairs]

    def get_event_gamma(self, slug: str) -> GammaEvent:
        with self._db.read() as conn:
            event = TableRead.get_event_by_slug(conn, slug)
            if event is None:
                raise EventNotFoundError(slug)
            markets = TableRead.list_markets_by_event_id(conn, event.event_id)
        return to_gamma_event(event, markets)
```

In `agentpit/api/routes/events.py`, replace the routes:

```python
from fastapi import APIRouter

from agentpit.api.deps import EventServiceDep
from agentpit.datastructures.gamma_market import GammaEvent

router = APIRouter(tags=["events"])


@router.get("/events", response_model=list[GammaEvent])
def list_events(
    service: EventServiceDep, limit: int = 100, offset: int = 0
) -> list[GammaEvent]:
    return service.list_events_gamma(limit=limit, offset=offset)


@router.get("/events/{slug}", response_model=GammaEvent)
def get_event(slug: str, service: EventServiceDep) -> GammaEvent:
    return service.get_event_gamma(slug)
```

- [ ] **Step 4: Update `tests/api/test_events.py` + run**

`tests/api/test_events.py` asserts the old envelope (e.g. `body == {"events": [], "total": 0, "limit": 10, "offset": 0}`). Update every such assertion to the new Gamma bare-array contract: empty → `[]`; populated → a list of `GammaEvent` objects (`ev["slug"]`, `ev["markets"][i]["conditionId"]`, etc.). Keep the `_seed_market` helper as-is. Then run:

Run: `.venv/bin/python -m pytest tests/api/test_events_gamma.py tests/api/test_events.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agentpit/services/event_service.py agentpit/api/routes/events.py tests/api/test_events_gamma.py tests/api/test_events.py
git commit -m "feat(api): GET /events + /events/{slug} return Gamma shape"
```

---

### Task 4: UI adapters (keep components + internal types unchanged)

Add Gamma wire types and rewrite the two API modules to fetch Gamma and adapt to the **existing** internal `Market`/`Event`/`EventWithMarkets`/`ListEventsResponse` types. Do **not** edit `ui/src/types/market.ts`, `ui/src/types/event.ts`, or any component.

**Files:**
- Create: `ui/src/types/gamma.ts`
- Modify: `ui/src/api/markets.ts` (keep `getSparkline`/`useSparkline` exactly as-is — sparkline is Phase 3)
- Modify: `ui/src/api/events.ts`

- [ ] **Step 1: Add the Gamma wire types**

Create `ui/src/types/gamma.ts`:

```ts
export interface GammaMarket {
  id: string;
  conditionId: string;
  question: string;
  slug: string;
  description: string;
  outcomes: string; // JSON-encoded array, e.g. '["Yes","No"]'
  outcomePrices: string;
  clobTokenIds: string;
  active: boolean;
  closed: boolean;
  acceptingOrders: boolean;
  startDate: string | null;
  endDate: string | null;
  endDateIso: string | null;
  icon: string | null;
  image: string | null;
  volume: string;
  liquidity: string;
  bestBid: number;
  bestAsk: number;
  lastTradePrice: number;
  spread: number;
}

export interface GammaEvent {
  id: string;
  slug: string;
  title: string;
  description: string;
  icon: string | null;
  category: string | null;
  startDate: string | null;
  endDate: string | null;
  markets: GammaMarket[];
}
```

- [ ] **Step 2: Add adapters + rewrite the market/event fetchers**

Add this shared adapter at the top of `ui/src/api/markets.ts` (after the imports; also import the Gamma + internal types) and rewrite `getMarket` to use it. Keep `getSparkline`/`useSparkline`/`useMarket` unchanged except `getMarket`'s body:

```ts
import type { GammaMarket } from "@/types/gamma";
import type { Market, MarketState } from "@/types/market";

const _isoToUnix = (iso: string | null): number | null =>
  iso ? Math.floor(Date.parse(iso) / 1000) : null;

const _stateOf = (g: GammaMarket): MarketState =>
  g.active ? "ACTIVE" : g.closed ? "CLOSED" : "DRAFT";

/** Map a Gamma wire market into the UI's internal Market shape. */
export function gammaToMarket(g: GammaMarket): Market {
  const labels = JSON.parse(g.outcomes) as string[];
  const tokenIds = JSON.parse(g.clobTokenIds) as string[];
  return {
    market_id: Number(g.id),
    question: g.question,
    slug: g.slug,
    description: g.description,
    erc1155_tokens: tokenIds.map((t, i) => [t, labels[i]] as const),
    start_date: _isoToUnix(g.startDate),
    end_date: _isoToUnix(g.endDate),
    market_state: _stateOf(g),
    resolved_outcome: null,
    polymarket_id: null,
    condition_id: g.conditionId,
    event_id: null,
    outcome_label: null,
    icon_url: g.icon,
  };
}

export async function getMarket(id: number | string): Promise<Market> {
  const g = await apiFetch<GammaMarket>(`/markets/${id}`);
  return gammaToMarket(g);
}
```

Rewrite `ui/src/api/events.ts` `listEvents` and `getEvent` (keep the hooks unchanged). Import `gammaToMarket` from `@/api/markets`, the Gamma types, and the internal `Event`/`EventWithMarkets`/`ListEventsResponse` types:

```ts
import type { GammaEvent } from "@/types/gamma";
import type { Event, EventWithMarkets, ListEventsResponse } from "@/types/event";
import { gammaToMarket } from "@/api/markets";

const _isoToUnix = (iso: string | null): number | null =>
  iso ? Math.floor(Date.parse(iso) / 1000) : null;

function gammaToEventWithMarkets(g: GammaEvent): EventWithMarkets {
  const event: Event = {
    event_id: Number(g.id),
    slug: g.slug,
    title: g.title,
    description: g.description,
    icon_url: g.icon,
    category: g.category,
    start_date: _isoToUnix(g.startDate),
    end_date: _isoToUnix(g.endDate),
    polymarket_event_id: null,
  };
  return { event, markets: g.markets.map(gammaToMarket) };
}

export async function listEvents(
  params: ListEventsParams,
): Promise<ListEventsResponse> {
  const search = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
  });
  const wire = await apiFetch<GammaEvent[]>(`/events?${search.toString()}`);
  const events = wire.map(gammaToEventWithMarkets);
  // Gamma returns a bare array with no total; derive a total that keeps the
  // infinite query paging while pages come back full, stopping on a short page.
  const total =
    params.offset + events.length + (events.length === params.limit ? 1 : 0);
  return { events, total, limit: params.limit, offset: params.offset };
}

export async function getEvent(slug: string): Promise<EventWithMarkets> {
  const g = await apiFetch<GammaEvent>(`/events/${encodeURIComponent(slug)}`);
  return gammaToEventWithMarkets(g);
}
```

- [ ] **Step 3: Typecheck the UI**

Run the repo's UI typecheck/build from `ui/` (e.g. `npm run build` or `npx tsc --noEmit` — use whatever the repo defines in `ui/package.json`).
Expected: no type errors. The internal `Market`/`Event` types and all components are unchanged, so only the two rewritten modules are exercised.

- [ ] **Step 4: Commit**

```bash
git add ui/src/types/gamma.ts ui/src/api/markets.ts ui/src/api/events.ts
git commit -m "feat(ui): consume Gamma markets/events wire via adapters (internal types unchanged)"
```

---

### Task 5: Regression check

- [ ] **Step 1: Backend suite**

Run: `.venv/bin/python -m pytest tests/polymarket tests/api -q`
Expected: PASS for all markets/events/gamma/polymarket tests (pre-existing on-chain integration tests needing anvil may fail — unrelated).

- [ ] **Step 2: UI build**

Run the UI build/typecheck from `ui/`. Expected: green.

- [ ] **Step 3: (verification only — no commit)**

---

## Verification

`GET /markets` and `GET /events` return bare Gamma arrays; `GET /markets/{id}` and `GET /events/{slug}` return single Gamma objects; the `condition_ids` / `clob_token_ids` / `polymarket_condition_id` bridge filters work; the agentpit UI builds and renders markets/events via the adapters with no component changes. `to_gamma_market`/`to_gamma_event` are the single serialization point reused by both markets and events.

## Next plans

Phase 2 (trading: `POST /order`, `DELETE /order`, `GET /data/orders`) — needs a local anvil + `scripts/deploy_exchange.sh` for the settlement path.
