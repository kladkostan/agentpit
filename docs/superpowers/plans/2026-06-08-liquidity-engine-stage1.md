# Liquidity Engine — Stage 1 (MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An in-process background engine that provisions ~100 house accounts and rests a U-shaped, Polymarket-pegged, strictly **non-crossing** order book on every active synced market — zero real trades.

**Architecture:** A third asyncio loop in the FastAPI `lifespan` (sibling of `_polymarket_sync_loop`), calling the service layer directly with the shared `db_session`/`onchain_admin` singletons. New package `agentpit/liquidity/`. See `docs/superpowers/specs/2026-06-08-liquidity-engine-design.md`.

**Tech Stack:** Python, psycopg 3 pool, FastAPI lifespan asyncio tasks, web3/eth-account, `py_clob_client.http_helpers.get` for the Polymarket midpoint, pytest on real Postgres + forked Anvil.

**Conventions (load-bearing):**
- Money/price/size are **micro** units: `MICRO = 1_000_000` = $1.00 = 1 share. Price space `0…1_000_000`, snapped to `TICK = 1_000` (0.1¢).
- Two id namespaces per market: read the real mid with `POLYMARKET_YES_TOKEN_ID`; quote/trade with the **local** `market.erc1155_tokens[0][0]` (YES) and `market.condition_id.value`.
- All quotes are **non-marketable** (every bid `< mid <` every ask), so `place_order`'s matcher returns no fills and nothing settles on-chain.
- Never `dict(row)` a CI row. All DB access via `db.read()/.write()`.
- Test DB helpers: `tests/db_helpers.py` → `fresh_test_db()`, `fresh_test_conn()`. Onchain tests need `scripts/run_node.sh` + `scripts/deploy_exchange.sh` running.

---

## File Structure

| File | Responsibility |
|---|---|
| `agentpit/config.py` (modify) | New `liquidity_*` Settings fields. |
| `agentpit/db/table_read.py` (modify) | `list_bot_users`, `list_active_synced_markets`. |
| `agentpit/onchain/admin.py` (modify) | `mint_usd` (deep funding via `usd.mint`). |
| `agentpit/liquidity/__init__.py` (create) | Package marker. |
| `agentpit/liquidity/ladder.py` (create) | Pure U-shape ladder builder (`Rung`, `build_ladder`). |
| `agentpit/liquidity/price_oracle.py` (create) | Real Polymarket mid fetch → micro. |
| `agentpit/liquidity/house_accounts.py` (create) | Idempotent provision + re-onboard; returns `User`s. |
| `agentpit/liquidity/engine.py` (create) | `LiquidityEngine.tick()` — enumerate, peg, inventory, quote. |
| `agentpit/api/app.py` (modify) | Provision at startup + sibling loop wiring. |
| `tests/liquidity/test_ladder.py` (create) | Pure unit tests. |
| `tests/liquidity/test_price_oracle.py` (create) | Fetch + conversion + error isolation. |
| `tests/db/test_liquidity_reads.py` (create) | `list_bot_users` / `list_active_synced_markets`. |
| `tests/onchain/test_mint_usd.py` (create) | `mint_usd` against Anvil. |
| `tests/onchain/test_house_accounts.py` (create) | Provisioning idempotency. |
| `tests/onchain/test_liquidity_tick.py` (create) | One tick → two-sided book, zero trades. |

---

## Task 1: Config fields

**Files:**
- Modify: `agentpit/config.py`
- Test: `tests/test_config_liquidity.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_liquidity.py
import os
from agentpit.config import Settings


def test_liquidity_defaults():
    s = Settings()
    assert s.liquidity_engine_enabled is False
    assert s.liquidity_house_account_count == 100
    assert s.liquidity_wallet_funding_usdc == 1_000_000_000
    assert s.liquidity_split_per_market_usdc == 10_000
    assert s.liquidity_makers_per_market == 16
    assert s.liquidity_ladder_rungs_per_side == 8
    assert abs(s.liquidity_wall_fraction - 0.6) < 1e-9


def test_liquidity_env_override(monkeypatch):
    monkeypatch.setenv("LIQUIDITY_ENGINE", "true")
    monkeypatch.setenv("AGENTPIT_LIQUIDITY_HOUSE_ACCOUNTS", "5")
    s = Settings()
    assert s.liquidity_engine_enabled is True
    assert s.liquidity_house_account_count == 5
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_config_liquidity.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'liquidity_engine_enabled'`.

- [ ] **Step 3: Add the fields**

Append inside `class Settings` (after the Admin block, `agentpit/config.py`). Note the enable flag is prefix-less (matching `SYNC`/`SNAPSHOT_ENABLED`); everything else uses the `AGENTPIT_LIQUIDITY_*` prefix.

```python
    # Liquidity Engine
    liquidity_engine_enabled: bool = Field(
        default=False, validation_alias="LIQUIDITY_ENGINE"
    )
    liquidity_interval_seconds: float = Field(
        default=2.0, validation_alias="AGENTPIT_LIQUIDITY_INTERVAL_SECONDS"
    )
    liquidity_house_account_count: int = Field(
        default=100, validation_alias="AGENTPIT_LIQUIDITY_HOUSE_ACCOUNTS"
    )
    liquidity_wallet_funding_usdc: int = Field(
        default=1_000_000_000, validation_alias="AGENTPIT_LIQUIDITY_WALLET_FUNDING_USDC"
    )
    liquidity_split_per_market_usdc: int = Field(
        default=10_000, validation_alias="AGENTPIT_LIQUIDITY_SPLIT_PER_MARKET_USDC"
    )
    liquidity_makers_per_market: int = Field(
        default=16, validation_alias="AGENTPIT_LIQUIDITY_MAKERS_PER_MARKET"
    )
    liquidity_ladder_rungs_per_side: int = Field(
        default=8, validation_alias="AGENTPIT_LIQUIDITY_LADDER_RUNGS"
    )
    liquidity_wall_fraction: float = Field(
        default=0.6, validation_alias="AGENTPIT_LIQUIDITY_WALL_FRACTION"
    )
    liquidity_requote_threshold_micro: int = Field(
        default=2_000, validation_alias="AGENTPIT_LIQUIDITY_REQUOTE_THRESHOLD"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config_liquidity.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add agentpit/config.py tests/test_config_liquidity.py
git commit -m "feat(liquidity): add liquidity-engine Settings fields"
```

---

## Task 2: `ladder.py` — pure U-shape builder

**Files:**
- Create: `agentpit/liquidity/__init__.py` (empty), `agentpit/liquidity/ladder.py`
- Test: `tests/liquidity/test_ladder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/liquidity/test_ladder.py
from agentpit.liquidity.ladder import MICRO, TICK, build_ladder


def _build(mid=500_000, **kw):
    kw.setdefault("rungs_per_side", 8)
    kw.setdefault("wall_fraction", 0.6)
    kw.setdefault("size_per_side_micro", 10_000 * MICRO)
    return build_ladder(mid, **kw)


def test_count_and_sides():
    rungs = _build()
    bids = [r for r in rungs if r.side == "BUY"]
    asks = [r for r in rungs if r.side == "SELL"]
    assert len(bids) == 8 and len(asks) == 8


def test_strictly_non_crossing():
    mid = 500_000
    rungs = _build(mid=mid)
    bids = [r.price_micro for r in rungs if r.side == "BUY"]
    asks = [r.price_micro for r in rungs if r.side == "SELL"]
    assert max(bids) < mid < min(asks)        # straddles mid
    assert max(bids) < min(asks)              # no cross


def test_prices_on_tick_and_in_bounds():
    for r in _build():
        assert 0 < r.price_micro < MICRO
        assert r.price_micro % TICK == 0


def test_wall_carries_wall_fraction_of_size():
    size = 10_000 * MICRO
    rungs = _build(size_per_side_micro=size, wall_fraction=0.6)
    bids = [r for r in rungs if r.side == "BUY"]
    wall = min(bids, key=lambda r: r.price_micro)        # outermost (near 0)
    assert abs(wall.size_micro - round(0.6 * size)) <= TICK


def test_respects_existing_touch():
    # An existing best_ask below mid must still keep bids under it.
    rungs = build_ladder(
        500_000, rungs_per_side=4, wall_fraction=0.5,
        size_per_side_micro=MICRO, best_ask_micro=490_000, best_bid_micro=480_000,
    )
    bids = [r.price_micro for r in rungs if r.side == "BUY"]
    asks = [r.price_micro for r in rungs if r.side == "SELL"]
    assert max(bids) < 490_000
    assert min(asks) > 480_000
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/liquidity/test_ladder.py -v`
Expected: FAIL (`ModuleNotFoundError: agentpit.liquidity.ladder`).

- [ ] **Step 3: Implement**

```python
# agentpit/liquidity/ladder.py
"""Pure U-shaped, non-crossing ladder construction. No DB / chain / RNG."""
from dataclasses import dataclass

MICRO = 1_000_000          # $1.00 / 1 share
TICK = 1_000              # 0.001 = 0.1 cent

# Wall band: outermost rung sits this far from the 0 / 1 edge.
_WALL_BID_PRICE = 20_000          # ~2 cents
_WALL_ASK_PRICE = MICRO - 20_000  # ~98 cents


@dataclass(frozen=True)
class Rung:
    side: str          # "BUY" | "SELL"
    price_micro: int   # on TICK grid, 0 < p < MICRO
    size_micro: int    # outcome-token micro units


def _snap(price_micro: int) -> int:
    snapped = round(price_micro / TICK) * TICK
    return max(TICK, min(MICRO - TICK, snapped))


def _side_rungs(side, *, ceiling, wall_price, rungs_per_side, wall_size, spread_size):
    """Build one side. `ceiling` is the price closest to mid (inclusive);
    rungs march away from mid toward `wall_price`. The wall rung carries
    `wall_size`; the remaining near-spread rungs split `spread_size` evenly."""
    near_count = rungs_per_side - 1
    prices = [ceiling]
    if near_count > 1:
        # linear steps from `ceiling` toward the wall for the near-spread cluster
        step = max(TICK, (abs(ceiling - wall_price)) // (rungs_per_side * 2))
        sign = -1 if side == "BUY" else 1
        for k in range(1, near_count):
            prices.append(_snap(ceiling + sign * step * k))
    each = spread_size // max(1, near_count)
    rungs = [Rung(side, _snap(p), each) for p in prices[:near_count]]
    rungs.append(Rung(side, _snap(wall_price), wall_size))
    return rungs


def build_ladder(
    mid_micro: int,
    *,
    rungs_per_side: int,
    wall_fraction: float,
    size_per_side_micro: int,
    best_bid_micro: int | None = None,
    best_ask_micro: int | None = None,
) -> list[Rung]:
    """U-shaped, strictly non-crossing ladder straddling `mid_micro`.

    Bids occupy (0, bid_ceiling], asks [ask_floor, MICRO); bid_ceiling is one
    tick below the lower of mid and any existing best_ask, ask_floor one tick
    above the higher of mid and any existing best_bid. `wall_fraction` of each
    side's size piles into the outer wall rung; the rest spreads near the touch.
    """
    wall_size = round(wall_fraction * size_per_side_micro)
    spread_size = size_per_side_micro - wall_size

    bid_ceiling = _snap(min(mid_micro, best_ask_micro or mid_micro) - TICK)
    ask_floor = _snap(max(mid_micro, best_bid_micro or mid_micro) + TICK)

    bids = _side_rungs(
        "BUY", ceiling=bid_ceiling, wall_price=_WALL_BID_PRICE,
        rungs_per_side=rungs_per_side, wall_size=wall_size, spread_size=spread_size,
    )
    asks = _side_rungs(
        "SELL", ceiling=ask_floor, wall_price=_WALL_ASK_PRICE,
        rungs_per_side=rungs_per_side, wall_size=wall_size, spread_size=spread_size,
    )
    return bids + asks
```

> Note: if any test reveals a rung lands on/over the opposite touch (e.g. tiny mid), clamp `bid_ceiling >= 2*TICK` and `ask_floor <= MICRO - 2*TICK`. Keep the non-crossing invariant test green.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/liquidity/test_ladder.py -v`
Expected: PASS (5 passed). Fix `_side_rungs` step math if `test_strictly_non_crossing` or `test_respects_existing_touch` fails.

- [ ] **Step 5: Commit**

```bash
git add agentpit/liquidity/__init__.py agentpit/liquidity/ladder.py tests/liquidity/test_ladder.py
git commit -m "feat(liquidity): pure U-shaped non-crossing ladder builder"
```

---

## Task 3: `price_oracle.py` — real Polymarket mid

**Files:**
- Create: `agentpit/liquidity/price_oracle.py`
- Test: `tests/liquidity/test_price_oracle.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/liquidity/test_price_oracle.py
from agentpit.liquidity import price_oracle


def test_mid_to_micro():
    got = price_oracle.fetch_mid_micro("TID", getter=lambda url: {"mid": "0.55"})
    assert got == 550_000


def test_bad_payload_returns_none():
    assert price_oracle.fetch_mid_micro("TID", getter=lambda url: {}) is None
    assert price_oracle.fetch_mid_micro("TID", getter=lambda url: {"mid": "x"}) is None


def test_fetch_error_isolated():
    def boom(url):
        raise RuntimeError("clob down")
    assert price_oracle.fetch_mid_micro("TID", getter=boom) is None


def test_uses_yes_token_id_in_url():
    seen = {}
    def getter(url):
        seen["url"] = url
        return {"mid": "0.42"}
    price_oracle.fetch_mid_micro("YESTOKEN", getter=getter)
    assert "token_id=YESTOKEN" in seen["url"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/liquidity/test_price_oracle.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

```python
# agentpit/liquidity/price_oracle.py
"""Fetch the live Polymarket CLOB midpoint and convert to micro-USDC."""
import logging

from py_clob_client.http_helpers.helpers import get

log = logging.getLogger(__name__)

CLOB_MIDPOINT_URL = "https://clob.polymarket.com/midpoint"
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


def fetch_mids_for_markets(markets, *, getter=get) -> dict[int, int]:
    """market_id -> mid_micro for every market with a usable Polymarket mid."""
    out: dict[int, int] = {}
    for m in markets:
        mid = fetch_mid_micro(m.polymarket_yes_token_id, getter=getter)
        if mid is not None:
            out[m.market_id] = mid
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/liquidity/test_price_oracle.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add agentpit/liquidity/price_oracle.py tests/liquidity/test_price_oracle.py
git commit -m "feat(liquidity): Polymarket CLOB midpoint oracle (micro-USDC)"
```

---

## Task 4: `TableRead.list_bot_users` + `list_active_synced_markets`

**Files:**
- Modify: `agentpit/db/table_read.py`
- Test: `tests/db/test_liquidity_reads.py`

Context: reuse the EXACT column list + row-mapper the existing readers use. `list_bot_users` mirrors `get_user_by_api_key` (same `_USER_COLS` + `_row_to_user`); `list_active_synced_markets` mirrors `list_all_markets` (table_read.py:259 — same market column list + `_row_to_market`). `IS_BOT` is INTEGER 0/1 → compare `= 1`.

- [ ] **Step 1: Write the failing test**

```python
# tests/db/test_liquidity_reads.py
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.auth.passwords import hash_password
from tests.db_helpers import fresh_test_conn


def _make_user(conn, email):
    uid, acct, api_key = TableWrite.create_user(
        conn, email=email, password_hash=hash_password("pw12pw12pw12"), handle=None
    )
    return uid, api_key


def test_list_bot_users_only_bots():
    conn = fresh_test_conn()
    _make_user(conn, "human@x.com")
    _uid, bot_key = _make_user(conn, "bot@x.com")
    TableWrite.mark_user_as_bot(conn, bot_key)

    bots = TableRead.list_bot_users(conn)
    assert [u.email for u in bots] == ["bot@x.com"]
    assert bots[0].is_bot is True
    assert bots[0].eth_key is not None  # reconstructed signer


def test_list_active_synced_markets_filters(make_market):
    # make_market is a helper that inserts a market row with given state +
    # polymarket_condition_id; see the existing market-insert fixtures.
    conn = fresh_test_conn()
    active_synced = make_market(conn, state="ACTIVE", pm_condition="0xpm1")
    make_market(conn, state="ACTIVE", pm_condition=None)      # not synced
    make_market(conn, state="RESOLVED", pm_condition="0xpm2") # not active

    got = TableRead.list_active_synced_markets(conn)
    assert [m.market_id for m in got] == [active_synced]
```

> If no `make_market` fixture exists, insert directly with `TableWrite.create_market(...)` (see how `tests/db/test_events_dal.py` / polymarket sync tests build market rows) and set `POLYMARKET_CONDITION_ID` / `MARKET_STATE` to the needed values. Keep the three-row filter assertion.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/db/test_liquidity_reads.py -v`
Expected: FAIL (`AttributeError: type object 'TableRead' has no attribute 'list_bot_users'`).

- [ ] **Step 3: Implement** (add two staticmethods to `TableRead`)

```python
    @staticmethod
    def list_bot_users(db) -> "list[User]":
        rows = db.execute(
            f"SELECT {TableRead._USER_COLS} FROM users WHERE IS_BOT = 1 "
            "ORDER BY CREATED_AT, USER_ID"
        ).fetchall()
        return [TableRead._row_to_user(r) for r in rows]

    @staticmethod
    def list_active_synced_markets(db) -> "list[Market]":
        rows = db.execute(
            f"SELECT {TableRead._MARKET_COLS} FROM markets "
            "WHERE MARKET_STATE = 'ACTIVE' AND POLYMARKET_CONDITION_ID IS NOT NULL "
            "ORDER BY MARKET_ID"
        ).fetchall()
        return [TableRead._row_to_market(r) for r in rows]
```

> Use the ACTUAL constant names already in the file (e.g. `_USER_COLS`, `_MARKET_COLS`) and the actual `_row_to_user` / `_row_to_market` mappers — confirm by reading `get_user_by_api_key` and `list_all_markets`. Do NOT `dict(row)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/db/test_liquidity_reads.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agentpit/db/table_read.py tests/db/test_liquidity_reads.py
git commit -m "feat(db): list_bot_users + list_active_synced_markets readers"
```

---

## Task 5: ~~`OnchainAdmin.mint_usd`~~ — DROPPED

**DROPPED (infra discovery, commit `d9b01c2`).** The apUSD token's `mint`/`setMinter` are `onlyMinter`, and the minter is the **faucet** contract, not the admin — so the admin cannot mint directly. Instead the faucet's drip grant was raised to **$1B/drip** (`SIGNUP_GRANT_RAW=1e15`, now the default in `scripts/deploy_exchange.sh`; chain redeployed). House funding therefore reuses the existing `faucet_drip` onboarding path (`liquidity_funding_drips` drips, default 1 = $1B). No new admin method, no `mint_usd`, no `test_mint_usd.py`. Proceed straight to Task 6.

- [ ] **Step 1: Write the failing test** (needs Anvil + deployment)

```python
# tests/onchain/test_mint_usd.py
from eth_account import Account

from agentpit.config import Settings
from agentpit.onchain.admin import OnchainAdmin
from agentpit.onchain.contracts import Contracts
from agentpit.onchain.deployment import Deployment
from agentpit.onchain.web3_client import Web3Client


def _admin():
    s = Settings()
    d = Deployment.load(s.deployment_path)
    w = Web3Client(s, d)
    return OnchainAdmin(w, Contracts(w.web3, d))


def test_mint_usd_credits_balance():
    admin = _admin()
    acct = Account.create()
    before = admin.usd_balance(acct.address)
    admin.mint_usd(acct.address, 5_000_000)  # 5 apUSD in micro
    assert admin.usd_balance(acct.address) == before + 5_000_000
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/onchain/test_mint_usd.py -v`
Expected: FAIL (`AttributeError: 'OnchainAdmin' object has no attribute 'mint_usd'`).

- [ ] **Step 3: Implement** (add to `OnchainAdmin`, near `faucet_drip`)

```python
    def mint_usd(self, recipient: str, amount_raw: int, *, timeout: int = 30) -> TxReceipt:
        """Admin-mint `amount_raw` (micro-USDC) apUSD to `recipient`.

        The admin key is the apUSD minter; one mint replaces ~1000 faucet drips
        when seeding deep house-account balances.
        """
        fn = self._contracts.usd.functions.mint(
            Web3.to_checksum_address(recipient), amount_raw
        )
        return send_admin_tx(self._client, fn, timeout=timeout)
```

> If `usd.functions.mint` doesn't exist in the ABI, check `agentpit/onchain/abi/usd.json` for the actual mint method name (the recon noted `mint`/`minter`/`setMinter`); use the real one. If minting is restricted, call `setMinter(admin)` once is NOT needed — the deployer/admin is already the minter.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/onchain/test_mint_usd.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agentpit/onchain/admin.py tests/onchain/test_mint_usd.py
git commit -m "feat(onchain): admin mint_usd for deep house-account funding"
```

---

## Task 6: `house_accounts.py` — idempotent provisioning + re-onboard

**Files:**
- Create: `agentpit/liquidity/house_accounts.py`
- Test: `tests/onchain/test_house_accounts.py`

Context: reuse the registration custody path. Create via `TableWrite.create_user`; onboard via `mint_usd` + `fund_gas` + `grant_user_approvals` (NOT inside the DB txn); then `mark_user_onboarded` + `mark_user_as_bot`. Detect existing accounts via `list_bot_users` AND deterministic emails `house-bot-{i}@agentpit.local` (EMAIL is UNIQUE → idempotency key). Re-onboard any existing account whose `native_balance == 0` (Anvil wipe), mirroring `AuthService._maybe_reonboard`.

- [ ] **Step 1: Write the failing test** (Anvil + PG; use a SMALL count)

```python
# tests/onchain/test_house_accounts.py
from agentpit.config import Settings
from agentpit.liquidity.house_accounts import HouseAccountProvisioner
from agentpit.onchain.admin import OnchainAdmin
from agentpit.onchain.contracts import Contracts
from agentpit.onchain.deployment import Deployment
from agentpit.onchain.web3_client import Web3Client
from tests.db_helpers import fresh_test_db


def _provisioner(count=3):
    s = Settings(liquidity_house_account_count=count, liquidity_funding_drips=1)
    d = Deployment.load(s.deployment_path)
    w = Web3Client(s, d)
    admin = OnchainAdmin(w, Contracts(w.web3, d))
    return HouseAccountProvisioner(fresh_test_db(), admin, s), admin, d


def test_provision_creates_and_funds():
    prov, admin, d = _provisioner(count=3)
    users = prov.ensure_provisioned()
    assert len(users) == 3
    for u in users:
        assert u.is_bot is True
        assert u.onboarded_at is not None
        assert admin.usd_balance(u.eth_address) >= d.signup_grant_raw  # >= 1 drip
        assert admin.native_balance(u.eth_address) > 0


def test_provision_is_idempotent():
    prov, _admin, _d = _provisioner(count=3)
    first = prov.ensure_provisioned()
    second = prov.ensure_provisioned()
    assert {u.email for u in first} == {u.email for u in second}
    assert len(second) == 3  # no duplicates created
```

> These hit the chain ~3×(mint+gas+3 approvals) ≈ 15 txns — slow but bounded. If the suite marks slow onchain tests, follow that marker convention.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/onchain/test_house_accounts.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

```python
# agentpit/liquidity/house_accounts.py
"""Idempotent provisioning of the engine's house (bot) accounts."""
import logging

from agentpit.auth.passwords import hash_password
from agentpit.config import Settings
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.onchain.admin import OnchainAdmin

log = logging.getLogger(__name__)

_EMAIL = "house-bot-{i}@agentpit.local"
_PASSWORD = "house-bot-fixed-secret-pw"  # house accounts never log in via HTTP


class HouseAccountProvisioner:
    def __init__(self, db: DbSession, onchain: OnchainAdmin, settings: Settings):
        self._db = db
        self._onchain = onchain
        self._settings = settings

    def ensure_provisioned(self) -> list[User]:
        target = self._settings.liquidity_house_account_count
        with self._db.read() as conn:
            existing = {u.email: u for u in TableRead.list_bot_users(conn)}

        # Re-onboard accounts the chain forgot (Anvil wipe).
        for u in existing.values():
            self._maybe_reonboard(u)

        users: list[User] = list(existing.values())
        for i in range(target):
            email = _EMAIL.format(i=i)
            if email in existing:
                continue
            users.append(self._create_and_onboard(email))
        log.info("house accounts: %d provisioned (target %d)", len(users), target)
        return users

    # --- helpers ----------------------------------------------------

    def _create_and_onboard(self, email: str) -> User:
        with self._db.write() as conn:
            prior = TableRead.get_user_by_email(conn, email)
            if prior is not None:           # partial-create recovery
                user_id, acct, api_key = prior.user_id, prior.eth_key, prior.api_key
            else:
                user_id, acct, api_key = TableWrite.create_user(
                    conn, email=email, password_hash=hash_password(_PASSWORD), handle=None
                )

        self._fund(acct)

        with self._db.write() as conn:
            TableWrite.mark_user_onboarded(conn, user_id)
            TableWrite.mark_user_as_bot(conn, api_key)
        with self._db.read() as conn:
            user = TableRead.get_user_by_userid(conn, user_id)
        assert user is not None
        return user

    def _fund(self, acct) -> None:
        timeout = self._settings.tx_confirmations_timeout_s
        for _ in range(self._settings.liquidity_funding_drips):
            self._onchain.faucet_drip(acct.address, timeout=timeout)
        self._onchain.fund_gas(
            acct.address, self._settings.signup_gas_grant_wei, timeout=timeout
        )
        self._onchain.grant_user_approvals(acct, timeout=timeout)

    def _maybe_reonboard(self, user: User) -> None:
        try:
            if self._onchain.native_balance(user.eth_address) > 0:
                return
        except Exception as exc:
            log.warning("native balance check failed for %s: %s", user.user_id, exc)
            return
        log.info("house account %s unfunded (chain reset) — re-onboarding", user.email)
        try:
            self._fund(user.eth_key)
        except Exception:
            log.exception("re-onboarding house account %s failed", user.email)
```

> `create_user` returns `(user_id, LocalAccount, api_key)`; the partial-recovery branch reuses the prior `User.eth_key` (a `LocalAccount`) as `acct`. Confirm `User.eth_key.address` is the eth address (it is, per `_run_onboarding(user.eth_key)` in AuthService).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/onchain/test_house_accounts.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add agentpit/liquidity/house_accounts.py tests/onchain/test_house_accounts.py
git commit -m "feat(liquidity): idempotent house-account provisioning + re-onboard"
```

---

## Task 7: `engine.py` — `LiquidityEngine.tick()`

**Files:**
- Create: `agentpit/liquidity/engine.py`
- Test: `tests/onchain/test_liquidity_tick.py`

Context: per tick, enumerate `list_active_synced_markets`, fetch real mids, and for each market whose mid moved (or first-seen) re-quote a rotating subset of maker accounts on the **YES token**, two-sided, strictly non-crossing. Before resting SELL rungs, ensure the maker holds YES inventory via `user_split_position` (mints YES+NO). All `place_order` calls use `order_type="GTC"` and must NOT fill.

- [ ] **Step 1: Write the failing test** (Anvil + PG; create a market the normal way, stub the oracle)

```python
# tests/onchain/test_liquidity_tick.py
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient

from agentpit.api.app import create_app
from agentpit.config import Settings
from agentpit.liquidity import price_oracle
from agentpit.liquidity.engine import LiquidityEngine
from agentpit.liquidity.house_accounts import HouseAccountProvisioner
from agentpit.onchain.admin import OnchainAdmin
from agentpit.onchain.contracts import Contracts
from agentpit.onchain.deployment import Deployment
from agentpit.onchain.web3_client import Web3Client
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead


def test_one_tick_builds_two_sided_book_no_trades(monkeypatch):
    app = create_app()
    client = TestClient(app)
    # Create a synced-shaped market (binary). Mark it ACTIVE with a polymarket
    # condition id so list_active_synced_markets returns it.
    m = client.post("/markets", json={
        "question": f"LE {uuid.uuid4().hex[:6]}?", "description": "x",
        "outcome_labels": ["YES", "NO"]}).json()
    cond = m["condition_id"]["value"]

    s = Settings(liquidity_house_account_count=3, liquidity_wallet_funding_usdc=1_000,
                 liquidity_makers_per_market=2, liquidity_split_per_market_usdc=50)
    d = Deployment.load(s.deployment_path)
    w = Web3Client(s, d)
    admin = OnchainAdmin(w, Contracts(w.web3, d))
    db = DbSession(s.database_url)

    # Force the market ACTIVE + synced (set POLYMARKET_CONDITION_ID + YES token).
    with db.write() as conn:
        conn.execute(
            "UPDATE markets SET MARKET_STATE='ACTIVE', POLYMARKET_CONDITION_ID=%s, "
            "POLYMARKET_YES_TOKEN_ID=%s WHERE CONDITION_ID=%s",
            ("0xpm", "PMYES", cond),
        )

    house = HouseAccountProvisioner(db, admin, s).ensure_provisioned()
    monkeypatch.setattr(price_oracle, "get", lambda url: {"mid": "0.50"})

    engine = LiquidityEngine(db, admin, s, house)
    engine.tick()

    # YES local token id:
    with db.read() as conn:
        market = TableRead.list_active_synced_markets(conn)[0]
    yes_token = market.erc1155_tokens[0][0]

    book = client.get(f"/book?token_id={yes_token}").json()
    assert book["bids"] and book["asks"]                 # two-sided
    best_bid = max(float(b["price"]) for b in book["bids"])
    best_ask = min(float(a["price"]) for a in book["asks"])
    assert best_bid < 0.5 < best_ask                     # straddles pegged mid, no cross

    # Zero real trades happened.
    with db.read() as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS C FROM trades WHERE MARKET = %s", (cond,)
        ).fetchone()["C"]
    assert n == 0
```

> The exact `/book` route + response shape: confirm against the market-data routes (the recon names `OrderService.get_book`). If the engine should pass `getter` into `fetch_mids_for_markets`, monkeypatch `price_oracle.get` as above (the module-level default).

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/onchain/test_liquidity_tick.py -v`
Expected: FAIL (`ModuleNotFoundError: agentpit.liquidity.engine`).

- [ ] **Step 3: Implement**

```python
# agentpit/liquidity/engine.py
"""In-process Liquidity Engine — one tick rests a pegged, non-crossing book."""
import logging
from decimal import Decimal

from agentpit.config import Settings
from agentpit.datastructures.place_order_request import PlaceOrderRequest
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.liquidity import price_oracle
from agentpit.liquidity.ladder import MICRO, build_ladder
from agentpit.onchain.admin import OnchainAdmin
from agentpit.services.order_service import OrderService

log = logging.getLogger(__name__)


class LiquidityEngine:
    def __init__(
        self, db: DbSession, onchain: OnchainAdmin, settings: Settings,
        house_users: list[User],
    ):
        self._db = db
        self._onchain = onchain
        self._cfg = settings
        self._house = house_users
        self._order = OrderService(db, onchain)
        self._last_mid: dict[int, int] = {}

    def tick(self) -> dict:
        with self._db.read() as conn:
            markets = TableRead.list_active_synced_markets(conn)
        mids = price_oracle.fetch_mids_for_markets(markets)
        quoted = 0
        for m in markets:
            mid = mids.get(m.market_id)
            if mid is None or not self._moved(m.market_id, mid):
                continue
            try:
                self._quote_market(m, mid)
                self._last_mid[m.market_id] = mid
                quoted += 1
            except Exception:
                log.exception("quoting market %s failed", m.market_id)
        return {"markets": len(markets), "quoted": quoted}

    # --- internals --------------------------------------------------

    def _moved(self, market_id: int, mid: int) -> bool:
        prev = self._last_mid.get(market_id)
        return prev is None or abs(mid - prev) >= self._cfg.liquidity_requote_threshold_micro

    def _makers_for(self, market_id: int) -> list[User]:
        if not self._house:
            return []
        n = min(self._cfg.liquidity_makers_per_market, len(self._house))
        start = (market_id * n) % len(self._house)
        rotated = self._house[start:] + self._house[:start]
        return rotated[:n]

    def _quote_market(self, market, mid: int) -> None:
        yes_token = market.erc1155_tokens[0][0]
        cond = market.condition_id.value
        size_per_side = self._cfg.liquidity_split_per_market_usdc * MICRO
        for u in self._makers_for(market.market_id):
            self._ensure_inventory(u, market)
            self._order.cancel_market_orders(u, market=cond, asset_id=None)
            rungs = build_ladder(
                mid,
                rungs_per_side=self._cfg.liquidity_ladder_rungs_per_side,
                wall_fraction=self._cfg.liquidity_wall_fraction,
                size_per_side_micro=size_per_side,
            )
            for r in rungs:
                payload = PlaceOrderRequest(
                    token_id=yes_token,
                    side=r.side,
                    price=Decimal(r.price_micro) / MICRO,
                    size=Decimal(r.size_micro) / MICRO,
                    order_type="GTC",
                )
                resp = self._order.place_order(u, payload)
                if getattr(resp, "tradeIDs", None):
                    log.error(
                        "liquidity quote unexpectedly filled (market=%s side=%s price=%s)",
                        market.market_id, r.side, r.price_micro,
                    )

    def _ensure_inventory(self, user: User, market) -> None:
        yes_token_int = int(market.erc1155_tokens[0][0])
        target = self._cfg.liquidity_split_per_market_usdc * MICRO
        held = self._onchain.ctf_balance(user.eth_address, yes_token_int)
        if held >= target:
            return
        condition_bytes = bytes.fromhex(market.condition_id.value[2:])
        self._onchain.user_split_position(user.eth_key, condition_bytes, target)
```

> Keep Stage 1 to the YES token only (two-sided). NO-side quoting and walk-trades are Stage 2/3. If `PlaceOrderRequest` rejects a `size` larger than balance, lower the per-rung size (split allocates `size_per_side` per side across rungs; ensure inventory `target` ≥ total SELL size placed — they're equal by construction since `size_per_side_micro == target`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/onchain/test_liquidity_tick.py -v`
Expected: PASS. If a SELL rung fails `_check_balance`, raise `liquidity_split_per_market_usdc` in the test or split a bit more than the resting SELL total.

- [ ] **Step 5: Commit**

```bash
git add agentpit/liquidity/engine.py tests/onchain/test_liquidity_tick.py
git commit -m "feat(liquidity): LiquidityEngine.tick — pegged non-crossing book"
```

---

## Task 8: Wire the engine into the app lifespan

**Files:**
- Modify: `agentpit/api/app.py`
- Test: `tests/onchain/test_liquidity_lifespan.py`

Context: mirror `_polymarket_sync_loop`. Provision house accounts ONCE at startup (blocking, via `asyncio.to_thread`) before creating the loop task; gate everything on `settings.liquidity_engine_enabled` (default off → existing tests unaffected); add `engine_task` to the `finally` cancel tuple.

- [ ] **Step 1: Write the failing test**

```python
# tests/onchain/test_liquidity_lifespan.py
from fastapi.testclient import TestClient

from agentpit.api.app import create_app
from agentpit.config import Settings


def test_engine_disabled_by_default():
    # Default settings: engine off. App starts/stops with no house accounts created.
    with TestClient(create_app()) as client:
        assert client.get("/system/health").status_code in (200, 404)
    # No assertion on bots — just that lifespan enter/exit is clean with engine off.


def test_engine_enabled_starts_and_stops(monkeypatch):
    monkeypatch.setenv("LIQUIDITY_ENGINE", "true")
    monkeypatch.setenv("AGENTPIT_LIQUIDITY_HOUSE_ACCOUNTS", "2")
    monkeypatch.setenv("AGENTPIT_LIQUIDITY_WALLET_FUNDING_USDC", "1000")
    monkeypatch.setenv("AGENTPIT_LIQUIDITY_INTERVAL_SECONDS", "0.2")
    # Lifespan should provision 2 bots and run >=1 tick without raising.
    with TestClient(create_app()) as client:
        import time
        time.sleep(1.0)
        bots = client.get("/system/health")  # smoke
    assert bots.status_code in (200, 404)
```

> Confirm a real cheap health route exists; if not, drop the `/system/health` calls and assert the `with TestClient(...)` block enters/exits without raising. The substantive check is that an enabled engine provisions + ticks + cancels cleanly.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/onchain/test_liquidity_lifespan.py -v`
Expected: FAIL (engine not wired; `LIQUIDITY_ENGINE=true` has no effect / `time.sleep` then clean exit but no provisioning — adjust once wired).

- [ ] **Step 3: Implement** — add to `agentpit/api/app.py`

Imports:
```python
from agentpit.liquidity.engine import LiquidityEngine
from agentpit.liquidity.house_accounts import HouseAccountProvisioner
```

Module-level worker + loop (beside the sync/snapshot pair):
```python
def _run_liquidity_tick(engine: LiquidityEngine) -> dict:
    return engine.tick()


async def _liquidity_engine_loop(engine: LiquidityEngine, interval_seconds: float) -> None:
    while True:
        try:
            stats = await asyncio.to_thread(_run_liquidity_tick, engine)
            log.info("Liquidity tick: %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Liquidity tick failed")
        await asyncio.sleep(interval_seconds)
```

Inside `lifespan`, after the snapshot block and before `yield`:
```python
        engine_task: asyncio.Task | None = None
        if settings.liquidity_engine_enabled:
            log.info(
                "Liquidity engine enabled (interval=%ss, accounts=%d)",
                settings.liquidity_interval_seconds,
                settings.liquidity_house_account_count,
            )
            provisioner = HouseAccountProvisioner(db_session, onchain_admin, settings)
            house_users = await asyncio.to_thread(provisioner.ensure_provisioned)
            engine = LiquidityEngine(db_session, onchain_admin, settings, house_users)
            engine_task = asyncio.create_task(
                _liquidity_engine_loop(engine, settings.liquidity_interval_seconds)
            )
        else:
            log.info("Liquidity engine disabled (set LIQUIDITY_ENGINE=true to enable)")
```

In the `finally`, extend the cancel tuple:
```python
            for task in (sync_task, snapshot_task, engine_task):
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/onchain/test_liquidity_lifespan.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agentpit/api/app.py tests/onchain/test_liquidity_lifespan.py
git commit -m "feat(liquidity): wire engine as a lifespan sibling loop (off by default)"
```

---

## Task 9: Stage-1 gate — full suite green

- [ ] **Step 1: Build check**

Run: `.venv/bin/python -c "from agentpit.api.app import create_app; create_app()"`
Expected: exit 0, no import errors.

- [ ] **Step 2: Run the whole suite on Postgres + Anvil**

Ensure `scripts/run_node.sh` + `scripts/deploy_exchange.sh` are up and Postgres `agentpit_test` exists.
Run: `.venv/bin/pytest -q | tee /tmp/le_stage1.log`
Expected: all prior 264 tests still green + the new Stage-1 tests pass; engine OFF by default means no behavior change for existing tests.

- [ ] **Step 3: Confirm no accidental fills path**

Verify the tick test asserts `trades` count == 0 and the book straddles the pegged mid. Re-read `engine._quote_market` for the non-crossing invariant.

- [ ] **Step 4: Commit any gate fixes, then dispatch the whole-phase review** (Stage 1 only).

---

## Self-Review notes (author)
- **Spec coverage:** Stage-1 deliverables 1–7 (spec §8) → Tasks 1–8; verification → Task 9. Stage 2 (walk-trades) and Stage 3 (resolution) are intentionally OUT of this plan.
- **Non-crossing invariant** is the safety property that keeps Stage 1 trade-free — enforced in `ladder.build_ladder` (tested) and relied on in `engine._quote_market` (all makers share one mid).
- **Type consistency:** `build_ladder(mid_micro, *, rungs_per_side, wall_fraction, size_per_side_micro, best_bid_micro=None, best_ask_micro=None)` is called identically in the engine. `Rung(side, price_micro, size_micro)`. `place_order(user, PlaceOrderRequest(...))`.
- **Open risks for the implementer to confirm against live code:** exact `_USER_COLS`/`_MARKET_COLS`/`_row_to_*` names; `/book` route + response field names; `usd.json` mint method name; whether a market-insert test fixture exists for Task 4.
