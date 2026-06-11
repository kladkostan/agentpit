# Trending Sync + Decoupled Resolution/Auto-Redeem Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Broaden the synced market universe to the top-N markets by 24h volume, make a re-sync pass do no on-chain work for already-known markets, and move resolution-mirroring + automatic on-chain redeem into their own cheap lifespan loop.

**Architecture:** Four independent changes in the Polymarket sync subsystem. Market discovery (`fetch_and_sync_polymarket_markets`) becomes a cheap, top-N-by-volume fetch that skips on-chain prep for known markets. Resolution mirroring (`mirror_polymarket_resolutions`) + a new `auto_redeem_resolved_markets` run in a new `_resolution_mirror_loop` on their own interval, scanning only candidate markets (ended-unresolved for resolve, resolved-unredeemed for redeem). A new `markets.FULLY_REDEEMED` column bounds the redeem scan.

**Tech Stack:** Python 3, FastAPI lifespan loops, psycopg/Postgres, web3.py + a local CTF/Exchange fork. Tests: pytest; on-chain tests require the anvil fork (`scripts/run_node.sh` + `scripts/deploy_exchange.sh`) + Postgres (`agentpit_test`).

**Reference spec:** `docs/superpowers/specs/2026-06-11-trending-sync-redeem-loop-design.md`

**Conventions:**
- Run tests with `pytest`. Pure tests need only Postgres; tasks marked **[on-chain]** need the fork running.
- Commit after each task. Do **not** add a `Co-Authored-By` trailer to commits.

---

### Task 1: Config knobs

**Files:**
- Modify: `agentpit/config.py`
- Test: `tests/test_config_sync_redeem.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_sync_redeem.py`:

```python
import importlib

from agentpit.config import Settings


def _settings(monkeypatch, **env):
    for k in (
        "SYNC", "SYNC_MAX_MARKETS", "SYNC_LIQUIDITY_MIN",
        "RESOLUTION_MIRROR_ENABLED", "RESOLUTION_MIRROR_INTERVAL_SECONDS",
        "AUTO_REDEEM_ENABLED",
    ):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)


def test_new_knobs_defaults(monkeypatch):
    s = _settings(monkeypatch)
    assert s.sync_max_markets == 300
    assert s.sync_liquidity_min == 0.0
    assert s.resolution_mirror_interval_seconds == 300
    assert s.auto_redeem_enabled is True
    # resolution_mirror_enabled defaults to sync_enabled (False here)
    assert s.resolution_mirror_enabled is False


def test_resolution_mirror_defaults_to_sync(monkeypatch):
    s = _settings(monkeypatch, SYNC="true")
    assert s.sync_enabled is True
    assert s.resolution_mirror_enabled is True


def test_resolution_mirror_explicit_override(monkeypatch):
    s = _settings(monkeypatch, SYNC="true", RESOLUTION_MIRROR_ENABLED="false")
    assert s.resolution_mirror_enabled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_sync_redeem.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'sync_max_markets'`.

- [ ] **Step 3: Implement the config fields**

In `agentpit/config.py`, change the import line `from pydantic import Field` to:

```python
from pydantic import Field, model_validator
```

Add these fields immediately after `sync_interval_seconds` (currently ends at line 27):

```python
    # Trending sync (top-N by 24h volume) + decoupled resolution/redeem loop
    sync_max_markets: int = Field(
        default=300, validation_alias="SYNC_MAX_MARKETS"
    )
    sync_liquidity_min: float = Field(
        default=0.0, validation_alias="SYNC_LIQUIDITY_MIN"
    )
    resolution_mirror_enabled: bool | None = Field(
        default=None, validation_alias="RESOLUTION_MIRROR_ENABLED"
    )
    resolution_mirror_interval_seconds: int = Field(
        default=300, validation_alias="RESOLUTION_MIRROR_INTERVAL_SECONDS"
    )
    auto_redeem_enabled: bool = Field(
        default=True, validation_alias="AUTO_REDEEM_ENABLED"
    )

    @model_validator(mode="after")
    def _default_resolution_mirror_enabled(self) -> "Settings":
        # When RESOLUTION_MIRROR_ENABLED is unset, follow SYNC.
        if self.resolution_mirror_enabled is None:
            self.resolution_mirror_enabled = self.sync_enabled
        return self
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config_sync_redeem.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add agentpit/config.py tests/test_config_sync_redeem.py
git commit -m "feat(config): trending-sync + resolution/redeem loop knobs"
```

---

### Task 2: `FULLY_REDEEMED` column + Market field + read/write

**Files:**
- Modify: `agentpit/db/table_create.py:122-176` (`create_markets_table`)
- Modify: `agentpit/db/table_read.py:16-24` (`_MARKET_COLS`), `:27-48` (`_row_to_market`)
- Modify: `agentpit/db/table_write.py` (add `mark_fully_redeemed`)
- Modify: `agentpit/datastructures/market.py`
- Test: `tests/db/test_fully_redeemed.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/db/test_fully_redeemed.py`:

```python
import json

from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from tests.db_helpers import fresh_test_conn


def _insert_market(conn) -> int:
    row = conn.execute(
        """
        INSERT INTO markets
            (CONDITION_ID, QUESTION, SLUG, DESCRIPTION, ERC1155_TOKENS,
             START_DATE, END_DATE, MARKET_STATE)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'ACTIVE')
        RETURNING MARKET_ID
        """,
        (
            "0x" + "ab" * 32, "Q?", "q", "d",
            json.dumps([["1", "YES"], ["2", "NO"]]),
            1000, 2000,
        ),
    ).fetchone()
    return row["MARKET_ID"]


def test_fully_redeemed_defaults_false_then_marks_true():
    conn = fresh_test_conn()
    mid = _insert_market(conn)

    market = TableRead.read_market(conn, mid)
    assert market is not None
    assert market.fully_redeemed is False

    TableWrite.mark_fully_redeemed(conn, mid)

    market2 = TableRead.read_market(conn, mid)
    assert market2 is not None
    assert market2.fully_redeemed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_fully_redeemed.py -v`
Expected: FAIL — `pydantic ValidationError` / `KeyError: 'FULLY_REDEEMED'` (column/field missing).

- [ ] **Step 3: Add the column to the DDL**

In `agentpit/db/table_create.py`, inside `create_markets_table`, add `FULLY_REDEEMED` to the `CREATE TABLE` body right after the `MARKET_STATE ... CHECK (...)` line (before the closing `)`):

```python
                MARKET_STATE TEXT NOT NULL DEFAULT '{MarketState.DRAFT.value}'
                    CHECK (MARKET_STATE IN ({allowed_states})),
                FULLY_REDEEMED BOOLEAN NOT NULL DEFAULT FALSE
```

Then add an idempotent migration `ALTER` alongside the other `ALTER TABLE markets ADD COLUMN IF NOT EXISTS` statements in the same method:

```python
        conn.execute(
            "ALTER TABLE markets ADD COLUMN IF NOT EXISTS "
            "FULLY_REDEEMED BOOLEAN NOT NULL DEFAULT FALSE"
        )
```

- [ ] **Step 4: Add the field to the Market model**

In `agentpit/datastructures/market.py`, add this field to the `Market` class (after `icon_url`, line 28):

```python
    fully_redeemed: bool = False
```

- [ ] **Step 5: Surface the column in reads**

In `agentpit/db/table_read.py`, extend `_MARKET_COLS` (lines 16-24) by appending the column to the last string fragment:

```python
_MARKET_COLS = (
    "MARKET_ID, POLYMARKET_ID, POLYMARKET_CONDITION_ID, CONDITION_ID, "
    "QUESTION, DESCRIPTION, SLUG, "
    "START_DATE, END_DATE, ERC1155_TOKENS, "
    "COALESCE(MARKET_STATE, 'DRAFT') as MARKET_STATE, "
    "RESOLVED_OUTCOME, "
    "EVENT_ID, OUTCOME_LABEL, ICON_URL, "
    "POLYMARKET_YES_TOKEN_ID, POLYMARKET_NO_TOKEN_ID, "
    "COALESCE(FULLY_REDEEMED, FALSE) as FULLY_REDEEMED"
)
```

In `_row_to_market` (lines 27-48), add the field to the `Market(...)` constructor (after `icon_url=row["ICON_URL"],`):

```python
        fully_redeemed=row["FULLY_REDEEMED"],
```

- [ ] **Step 6: Add the setter**

In `agentpit/db/table_write.py`, add a static method to `TableWrite` (place it next to `resolve_market`):

```python
    @staticmethod
    def mark_fully_redeemed(db: psycopg.Connection, market_id: int) -> None:
        """Flag a resolved market as having no remaining redeemable holders."""
        db.execute(
            "UPDATE markets SET FULLY_REDEEMED = TRUE WHERE MARKET_ID = %s",
            (market_id,),
        )
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/db/test_fully_redeemed.py -v`
Expected: PASS.

- [ ] **Step 8: Run the broader DB/datastructure tests for regressions**

Run: `pytest tests/db tests/polymarket -q`
Expected: PASS (existing market reads still construct `Market` with the new defaulted field).

- [ ] **Step 9: Commit**

```bash
git add agentpit/db/table_create.py agentpit/db/table_read.py agentpit/db/table_write.py agentpit/datastructures/market.py tests/db/test_fully_redeemed.py
git commit -m "feat(db): add markets.FULLY_REDEEMED column + Market field + setter"
```

---

### Task 3: Candidate queries (resolve candidates, redeem candidates, participants)

**Files:**
- Modify: `agentpit/db/table_read.py` (add three static methods to `TableRead`)
- Test: `tests/db/test_resolution_candidates.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/db/test_resolution_candidates.py`:

```python
import json

from agentpit.db.table_read import TableRead
from tests.db_helpers import fresh_test_conn


def _insert_market(conn, *, cid, state, end_date, tokens, fully=False) -> int:
    row = conn.execute(
        """
        INSERT INTO markets
            (CONDITION_ID, QUESTION, SLUG, DESCRIPTION, ERC1155_TOKENS,
             START_DATE, END_DATE, MARKET_STATE, FULLY_REDEEMED)
        VALUES (%s, 'Q?', %s, 'd', %s, 100, %s, %s, %s)
        RETURNING MARKET_ID
        """,
        (cid, cid, json.dumps(tokens), end_date, state, fully),
    ).fetchone()
    return row["MARKET_ID"]


def test_list_unresolved_ended_markets():
    conn = fresh_test_conn()
    ended = _insert_market(conn, cid="0x01", state="ACTIVE", end_date=500,
                           tokens=[["1", "YES"], ["2", "NO"]])
    _insert_market(conn, cid="0x02", state="ACTIVE", end_date=5000,
                   tokens=[["3", "YES"], ["4", "NO"]])  # not ended yet
    _insert_market(conn, cid="0x03", state="RESOLVED", end_date=500,
                   tokens=[["5", "YES"], ["6", "NO"]])  # already resolved

    out = TableRead.list_unresolved_ended_markets(conn, now=1000)
    assert [m.market_id for m in out] == [ended]


def test_list_resolved_unredeemed_markets():
    conn = fresh_test_conn()
    open_resolved = _insert_market(conn, cid="0x11", state="RESOLVED",
                                   end_date=500, tokens=[["1", "YES"], ["2", "NO"]])
    _insert_market(conn, cid="0x12", state="RESOLVED", end_date=500,
                   tokens=[["3", "YES"], ["4", "NO"]], fully=True)  # done
    _insert_market(conn, cid="0x13", state="ACTIVE", end_date=500,
                   tokens=[["5", "YES"], ["6", "NO"]])  # not resolved

    out = TableRead.list_resolved_unredeemed_markets(conn)
    assert [m.market_id for m in out] == [open_resolved]


def test_list_participant_api_keys_for_market():
    conn = fresh_test_conn()
    mid = _insert_market(conn, cid="0x21", state="RESOLVED", end_date=500,
                         tokens=[["100", "YES"], ["200", "NO"]])
    conn.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, TAKER_API_KEY, MAKER_API_KEY, "
        "STATUS, MATCH_TIME) VALUES ('t1', '100', 'alice', 'bob', 'MATCHED', 1)"
    )
    conn.execute(
        "INSERT INTO trades (TRADE_ID, ASSET_ID, TAKER_API_KEY, MAKER_API_KEY, "
        "STATUS, MATCH_TIME) VALUES ('t2', '999', 'carol', 'dave', 'MATCHED', 2)"
    )  # different token -> excluded
    conn.execute(
        "INSERT INTO transactions (API_KEY, TRANSACTION_TYPE, MARKET_ID) "
        "VALUES ('eve', 'SPLIT', %s)", (mid,)
    )

    keys = TableRead.list_participant_api_keys_for_market(
        conn, mid, ["100", "200"]
    )
    assert keys == {"alice", "bob", "eve"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_resolution_candidates.py -v`
Expected: FAIL — `AttributeError: type object 'TableRead' has no attribute 'list_unresolved_ended_markets'`.

- [ ] **Step 3: Implement the three queries**

In `agentpit/db/table_read.py`, add these static methods to `TableRead` (place after `list_active_synced_markets`, ~line 442):

```python
    @staticmethod
    def list_unresolved_ended_markets(
        db: psycopg.Connection, now: int
    ) -> "list[Market]":
        """Resolution candidates: not RESOLVED/CANCELLED and past END_DATE.

        Bounds the resolution mirror to markets that could plausibly be settled
        upstream, instead of every unresolved market.
        """
        rows = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets "
            "WHERE MARKET_STATE NOT IN ('RESOLVED', 'CANCELLED') "
            "AND END_DATE IS NOT NULL AND END_DATE < %s "
            "ORDER BY MARKET_ID",
            (now,),
        ).fetchall()
        return [_row_to_market(row) for row in rows]

    @staticmethod
    def list_resolved_unredeemed_markets(
        db: psycopg.Connection,
    ) -> "list[Market]":
        """Auto-redeem candidates: RESOLVED and not yet fully redeemed."""
        rows = db.execute(
            f"SELECT {_MARKET_COLS} FROM markets "
            "WHERE MARKET_STATE = 'RESOLVED' "
            "AND COALESCE(FULLY_REDEEMED, FALSE) = FALSE "
            "ORDER BY MARKET_ID"
        ).fetchall()
        return [_row_to_market(row) for row in rows]

    @staticmethod
    def list_participant_api_keys_for_market(
        db: psycopg.Connection, market_id: int, token_ids: "list[str]"
    ) -> "set[str]":
        """Distinct api_keys that traded the market's tokens or split/merged it.

        Scopes the auto-redeem holder scan to real participants (including the
        house/mirror bot account, which appears as a trade maker).
        """
        keys: set[str] = set()
        if token_ids:
            placeholders = ",".join("%s" for _ in token_ids)
            rows = db.execute(
                f"SELECT TAKER_API_KEY, MAKER_API_KEY FROM trades "
                f"WHERE ASSET_ID IN ({placeholders})",
                token_ids,
            ).fetchall()
            for r in rows:
                if r["TAKER_API_KEY"]:
                    keys.add(r["TAKER_API_KEY"])
                if r["MAKER_API_KEY"]:
                    keys.add(r["MAKER_API_KEY"])
        rows = db.execute(
            "SELECT DISTINCT API_KEY FROM transactions "
            "WHERE MARKET_ID = %s AND TRANSACTION_TYPE IN ('SPLIT', 'MERGE')",
            (market_id,),
        ).fetchall()
        for r in rows:
            if r["API_KEY"]:
                keys.add(r["API_KEY"])
        return keys
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/db/test_resolution_candidates.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add agentpit/db/table_read.py tests/db/test_resolution_candidates.py
git commit -m "feat(db): resolution/redeem candidate + participant queries"
```

---

### Task 4: Cheap sync — skip on-chain prep for already-synced markets

**Files:**
- Modify: `agentpit/polymarket/polymarket_sync.py:526-560` (`create_polygon_market_if_does_not_exist`)
- Test: `tests/polymarket/test_sync_skips_known.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/polymarket/test_sync_skips_known.py`:

```python
import secrets

import agentpit.polymarket.polymarket_sync as sync
from agentpit.datastructures.condition_id import ConditionId
from agentpit.db.table_read import TableRead
from tests.db_helpers import fresh_test_db


def _pm_market() -> dict:
    return {
        "id": int(secrets.token_hex(4), 16),
        "conditionId": "0x" + secrets.token_hex(32),
        "question": f"Skip-known {secrets.token_hex(4)}?",
        "description": "d",
        "slug": f"skip-known-{secrets.token_hex(4)}",
        "startDate": "2020-01-01T00:00:00Z",
        "endDate": "2020-01-02T00:00:00Z",
        "active": True,
        "closed": False,
        "tokens": [
            {"token_id": str(int(secrets.token_hex(8), 16)), "outcome": "Yes"},
            {"token_id": str(int(secrets.token_hex(8), 16)), "outcome": "No"},
        ],
    }


def test_known_market_skips_on_chain_prepare(monkeypatch):
    db = fresh_test_db()
    pm = _pm_market()

    calls = {"n": 0}
    real_prepare = sync.prepare_market_on_chain

    def spy(admin, question, labels):
        calls["n"] += 1
        # deterministic fake condition/token ids — no chain needed
        cid = ConditionId("0x" + secrets.token_hex(32))
        toks = [(str(int(secrets.token_hex(8), 16)), labels[0]),
                (str(int(secrets.token_hex(8), 16)), labels[1])]
        return cid, toks

    monkeypatch.setattr(sync, "prepare_market_on_chain", spy)

    with db.write() as conn:
        first = sync.create_polygon_market_if_does_not_exist(conn, pm, admin=None)
        assert first is not None
        assert calls["n"] == 1  # new market -> prepared once

        second = sync.create_polygon_market_if_does_not_exist(conn, pm, admin=None)
        assert second is None  # already synced
        assert calls["n"] == 1  # NOT prepared again — no on-chain work

    del real_prepare
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/polymarket/test_sync_skips_known.py -v`
Expected: FAIL — `calls["n"] == 2` (prepare runs again for the known market, because the existence check is currently after the prepare call).

- [ ] **Step 3: Reorder the existence check before the on-chain prepare**

In `agentpit/polymarket/polymarket_sync.py`, replace the body of `create_polygon_market_if_does_not_exist` (lines 526-560) with:

```python
def create_polygon_market_if_does_not_exist(
    db,
    pm_market: dict,
    admin: OnchainAdmin,
) -> Market | None:
    request = build_create_market_request_from_json(pm_market)
    check_state(bool(request.polymarket_id))

    # Cheap path first: a market already synced for this polymarket_id needs no
    # on-chain prepare — just keep its event grouping current and return.
    if TableRead.market_exists_by_polymarket_id(db, request.polymarket_id):
        bind_existing_market_to_upstream_event(
            db, polymarket_id=request.polymarket_id, pm_market=pm_market
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/polymarket/test_sync_skips_known.py -v`
Expected: PASS.

- [ ] **Step 5: Run the existing sync tests for regressions**

Run: `pytest tests/polymarket/test_polymarket_sync.py -q`
Expected: PASS (existing behavior — new markets still created — unchanged).

- [ ] **Step 6: Commit**

```bash
git add agentpit/polymarket/polymarket_sync.py tests/polymarket/test_sync_skips_known.py
git commit -m "perf(sync): skip on-chain prepare for already-synced markets"
```

---

### Task 5: Trending fetch — top-N ordered by 24h volume

**Files:**
- Modify: `agentpit/polymarket/polymarket_sync.py:178-277` (`fetch_all_polymarket_markets`)
- Modify: `agentpit/polymarket/polymarket_sync.py:477-491` (`fetch_and_sync_polymarket_markets` signature)
- Test: `tests/polymarket/test_trending_fetch.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/polymarket/test_trending_fetch.py`:

```python
import agentpit.polymarket.polymarket_sync as sync


def test_fetch_uses_volume_order_and_caps(monkeypatch):
    seen = {"urls": []}

    def fake_get(url):
        seen["urls"].append(url)
        # One full page then stop. Each market clears any floor (high volume).
        return [
            {
                "conditionId": f"0x{i:064x}",
                "question": f"Q{i}",
                "volumeNum": 10_000_000,
                "liquidity": 10_000_000,
                "active": True,
                "closed": False,
                "archived": False,
                "clobTokenIds": '["1","2"]',
                "outcomes": '["Yes","No"]',
            }
            for i in range(5)
        ]

    monkeypatch.setattr(sync, "get", fake_get)

    out = sync.fetch_all_polymarket_markets(
        order="volume_24hr", max_markets=3, liquidity_threshold=0
    )

    assert len(out) == 3  # capped to max_markets
    url = seen["urls"][0]
    assert "order=volume_24hr" in url
    assert "ascending=false" in url
    assert "active=true" in url
    assert "closed=false" in url
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/polymarket/test_trending_fetch.py -v`
Expected: FAIL — `TypeError: fetch_all_polymarket_markets() got an unexpected keyword argument 'order'`.

- [ ] **Step 3: Add ordering + cap to the fetch**

In `agentpit/polymarket/polymarket_sync.py`, change the `fetch_all_polymarket_markets` signature (line 178-184) to add `order` and `max_markets`:

```python
def fetch_all_polymarket_markets(
    host: str = POLYMARKET_GAMMA_URL,
    closed: bool = False,
    active: bool = True,
    archived: bool = False,
    liquidity_threshold: float = 1000000,
    order: str | None = None,
    max_markets: int | None = None,
) -> list[dict]:
```

In the query-building block (after the `closed`/`active`/`archived` parts are appended to `query_parts`, before `base_query = "&".join(query_parts)` at line 218), add:

```python
    if order:
        query_parts.append(f"order={order}")
        query_parts.append("ascending=false")
```

In the pagination loop, after `all_markets.extend(filtered_data)` (line 266) and before the `if len(data) < limit: break` check (line 271), add the cap:

```python
        if max_markets is not None and len(all_markets) >= max_markets:
            break
```

Finally, before `return all_markets` (line 277), truncate:

```python
    if max_markets is not None:
        all_markets = all_markets[:max_markets]
```

- [ ] **Step 4: Thread the knobs through the sync entry point**

Change `fetch_and_sync_polymarket_markets` (lines 477-491) signature + fetch call:

```python
def fetch_and_sync_polymarket_markets(
    db,
    admin: OnchainAdmin,
    host: str = POLYMARKET_GAMMA_URL,
    *,
    max_markets: int = 300,
    liquidity_min: float = 0.0,
) -> list[Market]:
    pm_markets = fetch_all_polymarket_markets(
        host,
        liquidity_threshold=liquidity_min,
        order="volume_24hr",
        max_markets=max_markets,
    )
    created_markets = create_polymarket_markets_if_needed(db, pm_markets, admin)
    return created_markets
```

> NOTE: the `mirror_polymarket_resolutions` call that currently sits here (lines 485-490) is intentionally removed — it moves to the resolution loop in Task 6. After this edit `fetch_and_sync_polymarket_markets` does discovery only.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/polymarket/test_trending_fetch.py -v`
Expected: PASS.

- [ ] **Step 6: Run existing sync tests**

Run: `pytest tests/polymarket/test_polymarket_sync.py -q`
Expected: PASS (the test calls `fetch_and_sync_polymarket_markets(db, admin)` with defaults; `order=volume_24hr` is appended but the fake/mocked Gamma in that test ignores ordering).

> If `tests/polymarket/test_polymarket_sync.py` asserts on the exact fetch URL and now fails, update its expected URL to include `order=volume_24hr&ascending=false`. Do not weaken any assertion about which markets are created.

- [ ] **Step 7: Commit**

```bash
git add agentpit/polymarket/polymarket_sync.py tests/polymarket/test_trending_fetch.py
git commit -m "feat(sync): top-N-by-24h-volume trending fetch; discovery-only sync"
```

---

### Task 6: Resolution mirror scans candidates only (decoupled)

**Files:**
- Modify: `agentpit/polymarket/polymarket_sync.py:592-667` (`mirror_polymarket_resolutions`)
- Modify: `tests/onchain/test_resolution_mirror.py` (update 3 existing call sites)
- Test: `tests/polymarket/test_mirror_candidates.py` (create — pure, no chain)

- [ ] **Step 1: Write the failing test**

Create `tests/polymarket/test_mirror_candidates.py`:

```python
import json

import agentpit.polymarket.polymarket_sync as sync
from tests.db_helpers import fresh_test_conn


def _insert(conn, *, cid, state, end_date):
    conn.execute(
        """
        INSERT INTO markets
            (CONDITION_ID, POLYMARKET_CONDITION_ID, QUESTION, SLUG, DESCRIPTION,
             ERC1155_TOKENS, START_DATE, END_DATE, MARKET_STATE)
        VALUES (%s, %s, 'Q?', %s, 'd', %s, 100, %s, %s)
        """,
        (cid, cid, cid, json.dumps([["1", "YES"], ["2", "NO"]]), end_date, state),
    )


def test_mirror_only_fetches_ended_unresolved(monkeypatch):
    conn = fresh_test_conn()
    _insert(conn, cid="0xaa", state="ACTIVE", end_date=500)   # ended -> candidate
    _insert(conn, cid="0xbb", state="ACTIVE", end_date=9000)  # not ended
    _insert(conn, cid="0xcc", state="RESOLVED", end_date=500)  # resolved

    fetched = []

    def fake_fetcher(polymarket_condition_id):
        fetched.append(polymarket_condition_id)
        return None  # upstream not resolved -> mirror does nothing further

    resolved = sync.mirror_polymarket_resolutions(
        conn, admin=None, fetcher=fake_fetcher, now=1000
    )

    assert resolved == 0
    assert fetched == ["0xaa"]  # only the ended, unresolved market was polled
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/polymarket/test_mirror_candidates.py -v`
Expected: FAIL — `TypeError: mirror_polymarket_resolutions() got an unexpected keyword argument 'now'` (and it currently walks all markets).

- [ ] **Step 3: Switch the mirror to the candidate query + `now`**

In `agentpit/polymarket/polymarket_sync.py`, change the `mirror_polymarket_resolutions` signature (line 592-597) to add `now`:

```python
def mirror_polymarket_resolutions(
    db,
    admin: OnchainAdmin,
    *,
    fetcher=_default_resolution_fetcher,
    now: int,
) -> int:
```

Replace its market-iteration source. Change line 610 from:

```python
    for market in TableRead.list_all_markets(db):
```

to:

```python
    for market in TableRead.list_unresolved_ended_markets(db, now):
```

The two `continue` guards inside the loop (the `polymarket_condition_id is None` check and the `market_state in {RESOLVED, CANCELLED}` check) remain — they are now redundant-but-harmless belt-and-suspenders.

- [ ] **Step 4: Update the existing on-chain mirror tests for the new signature**

In `tests/onchain/test_resolution_mirror.py`, the three calls to `mirror_polymarket_resolutions(conn, admin, fetcher=fetcher)` (lines 109, 142, 169, 172) must pass `now`. Use a far-future `now` so the fixtures (which carry an `endDate`) are always candidates:

```python
        mirror_polymarket_resolutions(conn, admin, fetcher=fetcher, now=9_999_999_999)
```

Apply the same `now=9_999_999_999` keyword to all four call sites.

- [ ] **Step 5: Run the pure candidate test**

Run: `pytest tests/polymarket/test_mirror_candidates.py -v`
Expected: PASS.

- [ ] **Step 6: [on-chain] Run the updated mirror integration tests**

Run: `pytest tests/onchain/test_resolution_mirror.py -v`
Expected: PASS (3 passed) — requires the anvil fork + Postgres.

- [ ] **Step 7: Commit**

```bash
git add agentpit/polymarket/polymarket_sync.py tests/polymarket/test_mirror_candidates.py tests/onchain/test_resolution_mirror.py
git commit -m "feat(sync): resolution mirror scans ended-unresolved candidates only"
```

---

### Task 7: Auto-redeem resolved markets

**Files:**
- Modify: `agentpit/polymarket/polymarket_sync.py` (add `auto_redeem_resolved_markets`)
- Test: `tests/onchain/test_auto_redeem.py` (create — **[on-chain]**)

- [ ] **Step 1: Write the failing test**

Create `tests/onchain/test_auto_redeem.py`:

```python
"""End-to-end auto-redeem on the local CTF.

Sync a binary market, onboard a user, split to give them both outcome tokens,
mirror an upstream resolution (reportPayouts on-chain + RESOLVED), then run
auto-redeem and assert the winner paid out, tokens are burned, and the market
is flagged FULLY_REDEEMED.
"""

import secrets

from agentpit.datastructures.market_state import MarketState
from agentpit.datastructures.split_position_request import SplitPositionRequest
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.polymarket.polymarket_sync import (
    auto_redeem_resolved_markets,
    create_polymarket_markets_if_needed,
    mirror_polymarket_resolutions,
)
from agentpit.services.position_service import PositionService


def _build_admin_and_db():
    from agentpit.config import Settings
    from agentpit.onchain.admin import OnchainAdmin
    from agentpit.onchain.contracts import Contracts
    from agentpit.onchain.deployment import Deployment
    from agentpit.onchain.web3_client import Web3Client
    from tests.db_helpers import fresh_test_db

    s = Settings()
    d = Deployment.load(s.deployment_path)
    w = Web3Client(s, d)
    c = Contracts(w.web3, d)
    return OnchainAdmin(w, c), fresh_test_db()


def _onboard_user(db, admin):
    email = f"redeem-{secrets.token_hex(4)}@example.com"
    with db.write() as conn:
        user_id, acct, _api_key = TableWrite.create_user(
            conn, email=email, password_hash="x", handle=None
        )
    admin.fund_gas(acct.address, 10**18)
    admin.faucet_drip(acct.address)
    admin.grant_user_approvals(acct)
    with db.read() as conn:
        return TableRead.get_user_by_userid(conn, user_id)


def _pm(question_suffix: str) -> dict:
    return {
        "id": int(secrets.token_hex(4), 16),
        "conditionId": "0x" + secrets.token_hex(32),
        "question": f"Auto redeem {question_suffix}?",
        "description": "d",
        "slug": f"auto-redeem-{question_suffix}",
        "startDate": "2020-01-01T00:00:00Z",
        "endDate": "2020-01-02T00:00:00Z",
        "active": True,
        "closed": False,
        "tokens": [
            {"token_id": str(int(secrets.token_hex(8), 16)), "outcome": "Yes"},
            {"token_id": str(int(secrets.token_hex(8), 16)), "outcome": "No"},
        ],
    }


def _resolved(pm: dict, winner_index: int) -> dict:
    out = dict(pm)
    out["closed"] = True
    out["tokens"] = [
        dict(t, winner=(i == winner_index)) for i, t in enumerate(pm["tokens"])
    ]
    return out


def test_auto_redeem_pays_winner_and_flags_market():
    admin, db = _build_admin_and_db()
    pm = _pm(secrets.token_hex(4))

    with db.write() as conn:
        created = create_polymarket_markets_if_needed(conn, [pm], admin)
    market = created[0]
    mid = market.market_id
    yes_token = int(market.erc1155_tokens[0][0])
    no_token = int(market.erc1155_tokens[1][0])

    user = _onboard_user(db, admin)
    split_amount = 100_000_000  # 100 apUSD raw
    PositionService(db, admin).split(user, mid, SplitPositionRequest(amount=split_amount))

    bal_before = admin.usd_balance(user.eth_address)
    assert admin.ctf_balance(user.eth_address, yes_token) == split_amount
    assert admin.ctf_balance(user.eth_address, no_token) == split_amount

    fake = _resolved(pm, winner_index=0)  # YES wins
    with db.write() as conn:
        mirror_polymarket_resolutions(
            conn, admin, fetcher=lambda _cid: fake, now=9_999_999_999
        )

    redeemed = auto_redeem_resolved_markets(db, admin)
    assert redeemed == 1

    bal_after = admin.usd_balance(user.eth_address)
    assert bal_after - bal_before == split_amount  # winner paid, loser 0
    assert admin.ctf_balance(user.eth_address, yes_token) == 0
    assert admin.ctf_balance(user.eth_address, no_token) == 0

    with db.read() as conn:
        row = TableRead.read_market(conn, mid)
    assert row.market_state == MarketState.RESOLVED
    assert row.fully_redeemed is True

    # Idempotent: a second pass redeems nobody.
    assert auto_redeem_resolved_markets(db, admin) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/onchain/test_auto_redeem.py -v`
Expected: FAIL — `ImportError: cannot import name 'auto_redeem_resolved_markets'`.

- [ ] **Step 3: Implement `auto_redeem_resolved_markets`**

In `agentpit/polymarket/polymarket_sync.py`, add this function (place it right after `mirror_polymarket_resolutions`):

```python
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
                        api_key,
                        market.market_id,
                    )
                svc.redeem(user, market.market_id)
                redeemed += 1
            except Exception:
                logger.exception(
                    "auto-redeem failed for %s on market %s",
                    api_key,
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
```

- [ ] **Step 4: [on-chain] Run test to verify it passes**

Run: `pytest tests/onchain/test_auto_redeem.py -v`
Expected: PASS — requires the anvil fork + Postgres.

- [ ] **Step 5: Commit**

```bash
git add agentpit/polymarket/polymarket_sync.py tests/onchain/test_auto_redeem.py
git commit -m "feat(sync): auto-redeem holders of resolved markets"
```

---

### Task 8: Wire the decoupled resolution/redeem loop into the lifespan

**Files:**
- Modify: `agentpit/api/app.py:41` (imports), `:59-76` (sync helper), add resolution loop, `:149-160` (lifespan wiring), `:201` (shutdown)
- Test: `tests/api/test_resolution_loop_wiring.py` (create — pure)

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_resolution_loop_wiring.py`:

```python
import agentpit.api.app as app_mod


def test_run_resolution_cycle_resolves_then_redeems(monkeypatch):
    calls = {"mirror": 0, "redeem": 0, "now": None}

    class FakeSettings:
        auto_redeem_enabled = True

    class FakeDb:
        def write(self):
            from contextlib import contextmanager

            @contextmanager
            def _cm():
                yield "CONN"

            return _cm()

    def fake_mirror(conn, admin, *, now):
        calls["mirror"] += 1
        calls["now"] = now
        assert conn == "CONN"
        return 2

    def fake_redeem(db, admin):
        calls["redeem"] += 1
        return 3

    monkeypatch.setattr(app_mod, "mirror_polymarket_resolutions", fake_mirror)
    monkeypatch.setattr(app_mod, "auto_redeem_resolved_markets", fake_redeem)

    resolved, redeemed = app_mod._run_resolution_cycle(
        FakeDb(), admin="ADMIN", settings=FakeSettings()
    )

    assert (resolved, redeemed) == (2, 3)
    assert calls["mirror"] == 1 and calls["redeem"] == 1
    assert isinstance(calls["now"], int)


def test_run_resolution_cycle_skips_redeem_when_disabled(monkeypatch):
    class FakeSettings:
        auto_redeem_enabled = False

    class FakeDb:
        def write(self):
            from contextlib import contextmanager

            @contextmanager
            def _cm():
                yield "CONN"

            return _cm()

    monkeypatch.setattr(
        app_mod, "mirror_polymarket_resolutions", lambda conn, admin, *, now: 1
    )
    called = {"redeem": False}

    def fake_redeem(db, admin):
        called["redeem"] = True
        return 0

    monkeypatch.setattr(app_mod, "auto_redeem_resolved_markets", fake_redeem)

    resolved, redeemed = app_mod._run_resolution_cycle(
        FakeDb(), admin="ADMIN", settings=FakeSettings()
    )
    assert (resolved, redeemed) == (1, 0)
    assert called["redeem"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_resolution_loop_wiring.py -v`
Expected: FAIL — `AttributeError: module 'agentpit.api.app' has no attribute '_run_resolution_cycle'`.

- [ ] **Step 3: Update imports**

In `agentpit/api/app.py`, change the sync import (line 41) to also bring in the new functions:

```python
from agentpit.polymarket.polymarket_sync import (
    auto_redeem_resolved_markets,
    fetch_and_sync_polymarket_markets,
    mirror_polymarket_resolutions,
)
```

Add `import time` near the top (after `import logging`, line 2):

```python
import time
```

- [ ] **Step 4: Thread settings into the sync helper + add the resolution cycle**

In `agentpit/api/app.py`, replace `_run_polymarket_sync` (lines 59-62) and `_polymarket_sync_loop` (lines 65-76) with versions that carry `settings`, and add the new resolution helpers right after:

```python
def _run_polymarket_sync(db: DbSession, admin: OnchainAdmin, settings: Settings) -> int:
    with db.write() as conn:
        created = fetch_and_sync_polymarket_markets(
            conn,
            admin,
            max_markets=settings.sync_max_markets,
            liquidity_min=settings.sync_liquidity_min,
        )
    return len(created)


async def _polymarket_sync_loop(
    db: DbSession, admin: OnchainAdmin, settings: Settings
) -> None:
    while True:
        try:
            count = await asyncio.to_thread(_run_polymarket_sync, db, admin, settings)
            log.info("Polymarket sync added %d new markets", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Polymarket sync failed")
        await asyncio.sleep(settings.sync_interval_seconds)


def _run_resolution_cycle(
    db: DbSession, admin: OnchainAdmin, settings: Settings
) -> tuple[int, int]:
    now = int(time.time())
    with db.write() as conn:
        resolved = mirror_polymarket_resolutions(conn, admin, now=now)
    redeemed = 0
    if settings.auto_redeem_enabled:
        redeemed = auto_redeem_resolved_markets(db, admin)
    return resolved, redeemed


async def _resolution_mirror_loop(
    db: DbSession, admin: OnchainAdmin, settings: Settings
) -> None:
    while True:
        try:
            resolved, redeemed = await asyncio.to_thread(
                _run_resolution_cycle, db, admin, settings
            )
            log.info(
                "Resolution cycle: %d resolved, %d redeemed", resolved, redeemed
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Resolution cycle failed")
        await asyncio.sleep(settings.resolution_mirror_interval_seconds)
```

- [ ] **Step 5: Update the sync-task creation in the lifespan**

In the lifespan, update the `sync_task` creation (lines 154-158) to pass `settings`:

```python
            sync_task = asyncio.create_task(
                _polymarket_sync_loop(db_session, onchain_admin, settings)
            )
```

- [ ] **Step 6: Start the resolution loop in the lifespan**

Immediately after the sync `if settings.sync_enabled: ... else: ...` block (after line 160), add:

```python
        resolution_task: asyncio.Task | None = None
        if settings.resolution_mirror_enabled:
            log.info(
                "Resolution/redeem loop enabled (interval=%ds, auto_redeem=%s)",
                settings.resolution_mirror_interval_seconds,
                settings.auto_redeem_enabled,
            )
            resolution_task = asyncio.create_task(
                _resolution_mirror_loop(db_session, onchain_admin, settings)
            )
        else:
            log.info(
                "Resolution/redeem loop disabled "
                "(set RESOLUTION_MIRROR_ENABLED=true to enable)"
            )
```

In the shutdown `for task in (...)` tuple (line 201), add `resolution_task`:

```python
            for task in (sync_task, snapshot_task, resolution_task, *mirror_tasks):
```

- [ ] **Step 7: Run the wiring test**

Run: `pytest tests/api/test_resolution_loop_wiring.py -v`
Expected: PASS (2 passed).

- [ ] **Step 8: Sanity-check the app still imports/builds**

Run: `python -c "import agentpit.api.app"`
Expected: no error.

- [ ] **Step 9: Commit**

```bash
git add agentpit/api/app.py tests/api/test_resolution_loop_wiring.py
git commit -m "feat(api): decoupled resolution/auto-redeem lifespan loop"
```

---

### Task 9: Document the new env vars

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Add the new knobs to `.env.example`**

In `.env.example`, under the `# FastAPI server` block (after the `LIQUIDITY_ENGINE=true` line), add:

```bash
# Trending sync: top-N markets by 24h volume (cheap re-sync skips known markets).
SYNC_MAX_MARKETS=300
SYNC_LIQUIDITY_MIN=0
# Decoupled resolution + auto-redeem loop (defaults to SYNC when unset).
RESOLUTION_MIRROR_ENABLED=true
RESOLUTION_MIRROR_INTERVAL_SECONDS=300
AUTO_REDEEM_ENABLED=true
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs(env): document trending-sync + resolution/redeem knobs"
```

---

### Task 10: Full-suite regression pass

- [ ] **Step 1: Run the pure suite**

Run: `pytest tests -q --ignore=tests/onchain`
Expected: PASS (no regressions in config, db, polymarket, api).

- [ ] **Step 2: [on-chain] Run the on-chain suite**

Run: `pytest tests/onchain -q`
Expected: PASS (requires the anvil fork + Postgres) — includes the updated `test_resolution_mirror.py` and new `test_auto_redeem.py`.

- [ ] **Step 3: Commit any incidental fixes**

If a pre-existing test needed a mechanical signature update (e.g. a `fetch_and_sync_polymarket_markets`/`mirror_polymarket_resolutions` call site), commit it:

```bash
git add -A
git commit -m "test: update call sites for new sync/mirror signatures"
```

---

## Self-Review

**Spec coverage:**
- Change 1 (trending universe) → Task 5 (+ Task 8 threads the knobs). ✓
- Change 2 (cheap sync) → Task 4. ✓
- Change 3 (decoupled, candidate-scoped resolution loop) → Task 6 (candidate scope) + Task 8 (own loop). ✓
- Change 4 (auto-redeem, all holders incl. house, idempotent via FULLY_REDEEMED) → Task 7 (+ Task 2 column, Task 3 participant query). ✓
- Data-model change (FULLY_REDEEMED) → Task 2. ✓
- Config knobs → Task 1; `.env.example` → Task 9. ✓
- Cadence (own intervals) → Task 1 defaults + Task 8 loops. ✓

**Type/name consistency:**
- `auto_redeem_resolved_markets(db, admin, *, gas_topup_wei=...)` — defined Task 7, called Task 8 (`auto_redeem_resolved_markets(db, admin)`) and tests. ✓
- `mirror_polymarket_resolutions(db, admin, *, fetcher=..., now=...)` — `now` added Task 6, supplied by Task 8 `_run_resolution_cycle` and all tests. ✓
- `list_unresolved_ended_markets(db, now)`, `list_resolved_unredeemed_markets(db)`, `list_participant_api_keys_for_market(db, market_id, token_ids)` — defined Task 3, used Tasks 6/7. ✓
- `TableWrite.mark_fully_redeemed(db, market_id)` — defined Task 2, used Task 7. ✓
- `Market.fully_redeemed` — defined Task 2, asserted Tasks 2/7. ✓
- `fetch_and_sync_polymarket_markets(..., *, max_markets, liquidity_min)` — defined Task 5, called Task 8. ✓
- Settings fields `sync_max_markets`, `sync_liquidity_min`, `resolution_mirror_enabled`, `resolution_mirror_interval_seconds`, `auto_redeem_enabled` — defined Task 1, used Task 8. ✓

**Placeholder scan:** none — every code step contains complete code; every test step contains real assertions.

**Open item carried from spec:** the Gamma ordering key (`order=volume_24hr`) is asserted in Task 5's test against a fake `get`; if the live Gamma API uses a different spelling, only the literal in Task 5 Step 3 + its test need changing. No other task depends on the exact spelling.
