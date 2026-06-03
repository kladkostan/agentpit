# Polymarket Foundation (Converters + Resolver) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the two shared building blocks every Polymarket-shaped endpoint depends on — value converters (agentpit scaled-ints ↔ Polymarket decimal-strings/floats) and a bidirectional market/token identifier resolver.

**Architecture:** Pure additive code in the existing `agentpit/polymarket/` domain package. `format.py` holds stateless conversion functions (no I/O). `resolve.py` holds connection-taking lookup functions that mirror the existing `TableRead` static-method idiom. No existing endpoint, route, model, or behavior changes — this plan only *adds* modules + tests, so it is risk-free to land first.

**Tech Stack:** Python 3, Pydantic v2, raw `sqlite3` (no ORM), `pytest` with the repo's autouse `:memory:` DB fixture (`tests/conftest.py`).

**Phase context:** This is the first of several plans implementing `docs/superpowers/specs/2026-06-03-agentpit-polymarket-api-migration-design.md`. It covers §3 (converters + resolver) only. Subsequent plans (Gamma markets/events, then trading/market-data/fills phases) consume these modules.

---

### Task 1: Value converters (`agentpit/polymarket/format.py`)

agentpit stores prices and sizes as integers scaled by 10⁶ (`_PRICE_ONE = 10**6` = $1.00; 1 outcome token = 10⁶ units). Polymarket's CLOB family uses **decimal strings** (`"0.36"`, `"30"`) and its Data-API / prices-history family uses **floats** (`0.36`, `30.0`). These functions convert at the serialization boundary; internal storage is untouched.

**Files:**
- Create: `agentpit/polymarket/format.py`
- Test: `tests/polymarket/test_format.py`

- [ ] **Step 1: Write the failing test**

Create `tests/polymarket/test_format.py`:

```python
from agentpit.polymarket.format import (
    price_to_decimal_str,
    price_to_float,
    size_to_decimal_str,
    size_to_float,
    decimal_str_to_price_int,
    decimal_str_to_size_micro,
)


def test_price_to_decimal_str_trims_trailing_zeros():
    assert price_to_decimal_str(360000) == "0.36"
    assert price_to_decimal_str(500000) == "0.5"
    assert price_to_decimal_str(1000000) == "1"
    assert price_to_decimal_str(1000) == "0.001"


def test_size_to_decimal_str_whole_and_fractional():
    assert size_to_decimal_str(30000000) == "30"
    assert size_to_decimal_str(30500000) == "30.5"
    assert size_to_decimal_str(0) == "0"


def test_price_to_float():
    assert price_to_float(360000) == 0.36
    assert price_to_float(1000000) == 1.0


def test_size_to_float():
    assert size_to_float(30000000) == 30.0


def test_inverses_round_trip():
    assert decimal_str_to_price_int("0.36") == 360000
    assert decimal_str_to_price_int("0.5") == 500000
    assert decimal_str_to_size_micro("30") == 30000000
    assert decimal_str_to_size_micro("30.5") == 30500000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/polymarket/test_format.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentpit.polymarket.format'`

- [ ] **Step 3: Write minimal implementation**

Create `agentpit/polymarket/format.py`:

```python
"""Convert agentpit's internal scaled-integer money values to/from the
Polymarket wire representations.

agentpit stores prices and sizes as integers scaled by 10**6
(10**6 == $1.00, and 1 outcome token == 10**6 base units). Polymarket's
CLOB family uses decimal STRINGS ("0.36", "30"); its Data-API and
prices-history families use JSON floats (0.36, 30.0).
"""

from decimal import ROUND_HALF_UP, Decimal

_SCALE = Decimal(10**6)


def _trim(d: Decimal) -> str:
    """Fixed-point string with no exponent and no trailing zeros.

    Decimal.normalize() would render 30 as '3E+1', so format with 'f'
    and strip trailing zeros manually.
    """
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def price_to_decimal_str(price_int: int) -> str:
    """360000 -> '0.36' (USDC-per-share decimal string, 0..1)."""
    return _trim(Decimal(price_int) / _SCALE)


def price_to_float(price_int: int) -> float:
    """360000 -> 0.36 (for the Data-API / prices-history families)."""
    return float(Decimal(price_int) / _SCALE)


def size_to_decimal_str(micro: int) -> str:
    """30000000 -> '30' (whole-share decimal string)."""
    return _trim(Decimal(micro) / _SCALE)


def size_to_float(micro: int) -> float:
    """30000000 -> 30.0 (for the Data-API family)."""
    return float(Decimal(micro) / _SCALE)


def decimal_str_to_price_int(value: str) -> int:
    """'0.36' -> 360000 (parse an inbound decimal price to scaled int)."""
    return int((Decimal(value) * _SCALE).to_integral_value(rounding=ROUND_HALF_UP))


def decimal_str_to_size_micro(value: str) -> int:
    """'30' -> 30000000 (parse an inbound decimal share size to base units)."""
    return int((Decimal(value) * _SCALE).to_integral_value(rounding=ROUND_HALF_UP))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/polymarket/test_format.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add agentpit/polymarket/format.py tests/polymarket/test_format.py
git commit -m "feat(polymarket): add value converters (scaled-int <-> decimal-string/float)"
```

---

### Task 2: Resolver — forward lookup `resolve_by_market_outcome`

Lifts the outcome-label lookup logic from `OrderService._resolve_market_lookup` ([order_service.py:217-225](../../../agentpit/services/order_service.py#L217-L225)) into a reusable, connection-taking function returning a structured result. Matching stays **case-insensitive** (per spec §8.13). `OrderService` is *not* refactored to delegate here yet — that happens in the trading phase, so this plan stays purely additive.

**Files:**
- Create: `agentpit/polymarket/resolve.py`
- Test: `tests/polymarket/test_resolve.py`

- [ ] **Step 1: Write the failing test**

Create `tests/polymarket/test_resolve.py`:

```python
import pytest

from agentpit.api.deps import get_db_session
from agentpit.api.main import app
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market_state import MarketState
from agentpit.db.table_write import TableWrite
from agentpit.domain.exceptions import MarketNotFoundError, MarketStateError
from agentpit.polymarket.resolve import resolve_by_market_outcome


def _hex32(seed: str) -> str:
    return "0x" + seed.encode().hex().ljust(64, "0")[:64]


@pytest.fixture()
def seeded():
    """Fresh in-memory DB (autouse conftest fixture) with one binary market.

    Tokens: "111"->Yes (index 0), "222"->No (index 1).
    """
    session = app.dependency_overrides[get_db_session]()
    req = CreateMarketRequest(
        question="Will it rain?",
        description="d",
        erc1155_tokens=[("111", "Yes"), ("222", "No")],
        slug="will-it-rain",
        condition_id=ConditionId(_hex32("m1")),
        state=MarketState.ACTIVE,
    )
    with session.write() as conn:
        market = TableWrite.create_market(conn, req, is_polygon_market=False)
    return session, market


def test_resolve_by_market_outcome_is_case_insensitive(seeded):
    session, market = seeded
    with session.read() as conn:
        r = resolve_by_market_outcome(conn, market.market_id, "yes")
    assert r.token_id == "111"
    assert r.outcome_index == 0
    assert r.condition_id == market.condition_id.value
    assert r.market.market_id == market.market_id


def test_resolve_by_market_outcome_second_outcome(seeded):
    session, market = seeded
    with session.read() as conn:
        r = resolve_by_market_outcome(conn, market.market_id, "No")
    assert r.token_id == "222"
    assert r.outcome_index == 1


def test_resolve_by_market_outcome_unknown_market_raises():
    session = app.dependency_overrides[get_db_session]()
    with session.read() as conn:
        with pytest.raises(MarketNotFoundError):
            resolve_by_market_outcome(conn, 999, "Yes")


def test_resolve_by_market_outcome_unknown_outcome_raises(seeded):
    session, market = seeded
    with session.read() as conn:
        with pytest.raises(MarketStateError):
            resolve_by_market_outcome(conn, market.market_id, "Maybe")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/polymarket/test_resolve.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentpit.polymarket.resolve'`

- [ ] **Step 3: Write minimal implementation**

Create `agentpit/polymarket/resolve.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/polymarket/test_resolve.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add agentpit/polymarket/resolve.py tests/polymarket/test_resolve.py
git commit -m "feat(polymarket): add resolve_by_market_outcome forward resolver"
```

---

### Task 3: Resolver — reverse lookup `resolve_by_token_id`

The bot addresses agentpit by `token_id` (Polymarket `asset_id`). This reverse lookup finds the market + outcome for a token id, generalizing the `ERC1155_TOKENS LIKE` query already used by `OrderService._complement_token_id` ([order_service.py:356-377](../../../agentpit/services/order_service.py#L356-L377)). Returns `None` for an unknown token (callers decide whether that's a 404).

**Files:**
- Modify: `agentpit/polymarket/resolve.py`
- Test: `tests/polymarket/test_resolve.py:` (add to the existing file)

- [ ] **Step 1: Write the failing test**

Append to `tests/polymarket/test_resolve.py`:

```python
def test_resolve_by_token_id_first_outcome(seeded):
    from agentpit.polymarket.resolve import resolve_by_token_id

    session, market = seeded
    with session.read() as conn:
        r = resolve_by_token_id(conn, "111")
    assert r is not None
    assert r.token_id == "111"
    assert r.outcome_index == 0
    assert r.market.market_id == market.market_id
    assert r.condition_id == market.condition_id.value


def test_resolve_by_token_id_second_outcome(seeded):
    from agentpit.polymarket.resolve import resolve_by_token_id

    session, _ = seeded
    with session.read() as conn:
        r = resolve_by_token_id(conn, "222")
    assert r is not None
    assert r.outcome_index == 1


def test_resolve_by_token_id_unknown_returns_none(seeded):
    from agentpit.polymarket.resolve import resolve_by_token_id

    session, _ = seeded
    with session.read() as conn:
        assert resolve_by_token_id(conn, "999") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/polymarket/test_resolve.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_by_token_id'`

- [ ] **Step 3: Write minimal implementation**

Append to `agentpit/polymarket/resolve.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/polymarket/test_resolve.py -v`
Expected: PASS (7 tests total)

- [ ] **Step 5: Commit**

```bash
git add agentpit/polymarket/resolve.py tests/polymarket/test_resolve.py
git commit -m "feat(polymarket): add resolve_by_token_id reverse resolver"
```

---

### Task 4: Full-suite regression check

This plan is purely additive (new modules + tests, no edits to existing code), so the existing suite must remain green.

- [ ] **Step 1: Run the whole suite**

Run: `pytest -q`
Expected: PASS — all pre-existing tests plus the 13 new ones (6 format + 7 resolve). No failures, no new warnings in the new files.

- [ ] **Step 2: (no commit — verification only)**

If anything fails, it indicates an import cycle or a name clash introduced by the new modules; fix before proceeding to the next plan.

---

## Verification

After all tasks: `pytest tests/polymarket/ -v` is green (13 tests), `pytest -q` is green overall, and `agentpit/polymarket/format.py` + `agentpit/polymarket/resolve.py` exist with the exact public functions consumed by later plans: `price_to_decimal_str`, `price_to_float`, `size_to_decimal_str`, `size_to_float`, `decimal_str_to_price_int`, `decimal_str_to_size_micro`, `resolve_by_market_outcome`, `resolve_by_token_id`, and the `ResolvedOutcome` dataclass.

## Next plans (not in scope here)

1. **Gamma markets/events** — reshape `GET /markets` (+`/markets/{id}`) and `GET /events` to the Gamma subset (§8.11) with the condition_id bridge filters (§6); migrate UI `api/markets.ts`/`api/events.ts` + components.
2. **Trading core** (spec Phase 2), **Market data** (Phase 3), **Fills/positions/balance/activity** (Phase 4) — each its own plan, authored once its predecessor lands.
