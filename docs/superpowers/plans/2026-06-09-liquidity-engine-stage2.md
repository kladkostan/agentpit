# Liquidity Engine — Stage 2 (arbitrage-flavoured tape prints) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Animate the trade tape and keep agentpit's *traded* (last-trade) price tracking Polymarket, by printing a small real trade **only when** Polymarket's fair value has diverged from the last print beyond a threshold. The oracle (Stage 1/1.5) already keeps the *quoted* book aligned; Stage 2 only adds the tape.

**Model:** A taker house account (from a dedicated taker pool, disjoint from makers) crosses the best resting level in the direction of Polymarket's move. Direction-correct, throttled, self-trade-safe. Builds on Stage 1.5 (green, 295 passed). Engine OFF by default.

**Tech:** same as Stage 1 — service-layer direct calls (`OrderService.place_order`), real Postgres + Anvil tests.

**Conventions:** micro units (`MICRO=1e6`), price tick `0.001`; commits without `Co-Authored-By`; `.venv/bin/pytest`. The matcher excludes only same `ORDER_ID` → **taker account must differ from every maker it crosses** (guaranteed by disjoint pools). `place_order` returns `success=False` on settlement failure (does NOT raise) — inspect it.

---

## Design

**Account pools** (set once in `LiquidityEngine.__init__`): split `house_users` into
`self._takers = house_users[:taker_pool_size]` and `self._makers = house_users[taker_pool_size:]`.
`_makers_for` picks from `self._makers`; `_taker_for(market_id)` rotates over `self._takers`. Disjoint → taker ≠ maker always.

**Print decision** (per tick, per market, after the quote): engine keeps `self._last_print_fair: dict[int,int]`.
```
fair = (F_bid + F_ask) // 2                      # Polymarket fair, already fetched this tick
prev = self._last_print_fair.get(market_id)
if prev is not None and abs(fair - prev) < print_threshold_micro:  return  # stable → no print
up = prev is None or fair > prev                 # first encounter seeds the tape with a BUY
taker = self._taker_for(market_id)
own_bid, own_ask = self._order._best_bid_ask(yes_token)
if up:   side, price = BUY,  own_ask    # lift the ask → last-trade rises
else:    side, price = SELL, own_bid    # hit the bid  → last-trade falls; taker needs YES inventory first
resp = place_order(taker, FAK @ price, print_size_shares)
if resp.success and resp.tradeIDs:  self._last_print_fair[market_id] = fair   # only latch on a real fill
```
- **FAK** (fill-and-kill) so the taker never leaves a resting order (which a later taker could cross → self-trade).
- print size (`liquidity_print_size_shares`, default 100) < a near-spread rung (~570 sh) → fully fills against one maker level.
- A SELL print needs the taker to own YES → call `_ensure_inventory(taker, market)` before it (one split).
- Global per-tick cap `liquidity_max_prints_per_tick` (settlement is serialized on the admin lock; cheap on Anvil but bounded for safety).
- On `success=False` or no fill: do **not** latch `_last_print_fair` → retried next tick.

**Why this converges:** after a BUY print, last-trade = `own_ask ≈ F_ask`; `|fair − F_ask| =` half-spread `< threshold` → no re-print until Polymarket moves ≥ `print_threshold` again. Quoted touch is restored by the next oracle re-quote.

---

## Task 1: Config fields

**Files:** Modify `agentpit/config.py`; Test `tests/test_config_liquidity.py`.

- [ ] **Step 1: add a failing assert** to `test_liquidity_defaults`:
```python
    assert s.liquidity_taker_pool_size == 8
    assert s.liquidity_print_threshold_micro == 5_000
    assert s.liquidity_print_size_shares == 100
    assert s.liquidity_max_prints_per_tick == 5
```
- [ ] **Step 2: run** `.venv/bin/pytest tests/test_config_liquidity.py -v` → FAIL (AttributeError).
- [ ] **Step 3: add fields** to `Settings` (after the existing liquidity block):
```python
    liquidity_taker_pool_size: int = Field(
        default=8, validation_alias="AGENTPIT_LIQUIDITY_TAKER_POOL_SIZE"
    )
    liquidity_print_threshold_micro: int = Field(
        default=5_000, validation_alias="AGENTPIT_LIQUIDITY_PRINT_THRESHOLD"
    )
    liquidity_print_size_shares: int = Field(
        default=100, validation_alias="AGENTPIT_LIQUIDITY_PRINT_SIZE_SHARES"
    )
    liquidity_max_prints_per_tick: int = Field(
        default=5, validation_alias="AGENTPIT_LIQUIDITY_MAX_PRINTS_PER_TICK"
    )
```
- [ ] **Step 4: run** → PASS.
- [ ] **Step 5: commit** `feat(liquidity): Stage 2 config (taker pool, print threshold/size/cap)`.

---

## Task 2: Taker pool + arb print + tick wiring

**Files:** Modify `agentpit/liquidity/engine.py`; Test `tests/onchain/test_liquidity_arb.py` (new).

- [ ] **Step 1: write the failing onchain test** `tests/onchain/test_liquidity_arb.py`:
```python
import uuid
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
from agentpit.services.order_service import OrderService


def _setup(monkeypatch, box):
    app = create_app(); client = TestClient(app)
    m = client.post("/markets", json={"question": f"ARB {uuid.uuid4().hex[:6]}?",
        "description": "x", "outcome_labels": ["YES", "NO"]}).json()
    cond = m["condition_id"]["value"]
    s = Settings(liquidity_house_account_count=5, liquidity_funding_drips=1,
                 liquidity_makers_per_market=2, liquidity_taker_pool_size=2,
                 liquidity_split_per_market_usdc=50, liquidity_print_size_shares=10,
                 liquidity_print_threshold_micro=5_000)
    d = Deployment.load(s.deployment_path); w = Web3Client(s, d)
    admin = OnchainAdmin(w, Contracts(w.web3, d)); db = DbSession(s.database_url)
    with db.write() as conn:
        conn.execute("UPDATE markets SET MARKET_STATE='ACTIVE', POLYMARKET_CONDITION_ID=%s, "
                     "POLYMARKET_YES_TOKEN_ID=%s WHERE CONDITION_ID=%s", ("0xpm", "PMYES", cond))
    house = HouseAccountProvisioner(db, admin, s).ensure_provisioned()
    monkeypatch.setattr(price_oracle, "fetch_bid_ask_micro", lambda tid, **kw: box["v"])
    return db, admin, s, house, cond, m


def _trade_count(db, cond):
    with db.read() as conn:
        return conn.execute("SELECT COUNT(*) AS C FROM trades WHERE MARKET=%s", (cond,)).fetchone()["C"]


def test_arb_print_seeds_and_follows(monkeypatch):
    box = {"v": (490_000, 510_000)}
    db, admin, s, house, cond, m = _setup(monkeypatch, box)
    engine = LiquidityEngine(db, admin, s, house)

    engine.tick()                       # quote + seed one print
    n1 = _trade_count(db, cond)
    assert n1 >= 1                      # tape seeded
    yes = TableRead.list_active_synced_markets.__wrapped__ if False else None  # (use the market's yes token)
    with db.read() as conn:
        mk = TableRead.list_active_synced_markets(conn)[0]
    yes_token = mk.erc1155_tokens[0][0]
    last1 = OrderService(db, admin).get_last_trade_price(yes_token)

    box["v"] = (590_000, 610_000)       # Polymarket moved up ~0.10 (> print threshold)
    engine.tick()                       # requote + BUY print
    n2 = _trade_count(db, cond)
    assert n2 > n1                      # another print happened
    last2 = OrderService(db, admin).get_last_trade_price(yes_token)
    assert float(last2) > float(last1) # traded price followed Polymarket up


def test_no_print_when_fair_stable(monkeypatch):
    box = {"v": (490_000, 510_000)}
    db, admin, s, house, cond, m = _setup(monkeypatch, box)
    engine = LiquidityEngine(db, admin, s, house)
    engine.tick()                       # seed
    n1 = _trade_count(db, cond)
    engine.tick()                       # same fair → no new print
    assert _trade_count(db, cond) == n1
```
> Confirm `OrderService.get_last_trade_price(token_id)` exists and its return type (likely a decimal string) — adapt the `float(...)` comparison. If the seed-print direction makes `last1`/`last2` comparison awkward, assert on `_trade_count` growth + that `last2` ≈ the new Polymarket touch instead. Keep: (1) a print appears, (2) a bigger Polymarket move yields another print and a higher traded price, (3) a stable fair yields no new print.

- [ ] **Step 2: run** `.venv/bin/pytest tests/onchain/test_liquidity_arb.py -v` → FAIL (engine has no pools/print).

- [ ] **Step 3: implement** in `engine.py`:

In `__init__`, after `self._house = house_users`, split the pool and add print state:
```python
        n_takers = min(settings.liquidity_taker_pool_size, max(0, len(house_users) - 1))
        self._takers = house_users[:n_takers]
        self._makers = house_users[n_takers:] or house_users
        self._last_print_fair: dict[int, int] = {}
```
Change `_makers_for` to iterate `self._makers` (not `self._house`). Add:
```python
    def _taker_for(self, market_id: int):
        if not self._takers:
            return None
        return self._takers[market_id % len(self._takers)]
```
In `tick()`, after the quote block for a market, run the print (respecting a per-tick budget):
```python
        prints_left = self._cfg.liquidity_max_prints_per_tick
        ...
        for m in markets:
            bid, ask = price_oracle.fetch_bid_ask_micro(m.polymarket_yes_token_id)
            if bid is None or ask is None or bid >= ask:
                continue
            mid = (bid + ask) // 2
            if self._moved(m.market_id, mid):
                try:
                    self._quote_market(m, bid, ask); self._last_mid[m.market_id] = mid; quoted += 1
                except Exception:
                    log.exception("quoting market %s failed", m.market_id)
            if prints_left > 0:
                try:
                    if self._maybe_print(m, bid, ask):
                        printed += 1; prints_left -= 1
                except Exception:
                    log.exception("arb print market %s failed", m.market_id)
        return {"markets": len(markets), "quoted": quoted, "printed": printed}
```
Add the print method:
```python
    def _maybe_print(self, market, p_bid: int, p_ask: int) -> bool:
        fair = (p_bid + p_ask) // 2
        prev = self._last_print_fair.get(market.market_id)
        if prev is not None and abs(fair - prev) < self._cfg.liquidity_print_threshold_micro:
            return False
        taker = self._taker_for(market.market_id)
        if taker is None:
            return False
        yes_token = market.erc1155_tokens[0][0]
        own_bid, own_ask = self._order._best_bid_ask(yes_token)
        up = prev is None or fair > prev
        size = Decimal(self._cfg.liquidity_print_size_shares)
        if up:
            if own_ask is None:
                return False
            side, price = "BUY", Decimal(own_ask) / MICRO
        else:
            if own_bid is None:
                return False
            self._ensure_inventory(taker, market)   # taker needs YES to sell
            side, price = "SELL", Decimal(own_bid) / MICRO
        resp = self._order.place_order(taker, PlaceOrderRequest(
            token_id=yes_token, side=side, price=price, size=size, order_type="FAK"))
        if not resp.success or not resp.tradeIDs:
            log.warning("arb print did not fill (market=%s side=%s success=%s)",
                        market.market_id, side, resp.success)
            return False
        self._last_print_fair[market.market_id] = fair
        return True
```
> Confirm `PlaceOrderRequest` accepts `order_type="FAK"` (it's in the Literal). If FAK isn't honored by the matcher, use `"GTC"` — print size < level size means it fully fills and leaves nothing resting anyway, but FAK is the correct taker semantic.

- [ ] **Step 4: run** `.venv/bin/pytest tests/onchain/test_liquidity_arb.py tests/onchain/test_liquidity_tick.py -v` → all green; the Stage-1 zero-trades tests still pass (they don't run `_maybe_print` past the threshold gate on a single un-moved tick — verify: a single tick with `prev=None` WILL seed one print, so `test_one_tick_builds_two_sided_book_no_trades` may now see 1 trade! **Update that test**: it asserts zero trades, but Stage 2 seeds a print on first tick. Either (a) construct the engine with `liquidity_taker_pool_size=0` in that specific Stage-1 test so no taker exists → no print, preserving the pure zero-trades book assertion; or (b) move the zero-trades guarantee to "no UNINTENDED crossing" and assert exactly the seed print. Prefer (a) — set `liquidity_taker_pool_size=0` in the two Stage-1 tick tests so they keep asserting zero trades for the resting-only book.)

- [ ] **Step 5:** build check `.venv/bin/python -c "from agentpit.api.app import create_app; create_app()"`.
- [ ] **Step 6: commit** `feat(liquidity): Stage 2 arb-flavoured tape prints (taker pool, divergence-gated)`.

---

## Task 3: Stage-2 gate

- [ ] Full suite `.venv/bin/pytest -q` green on Postgres + Anvil (Stage-1 tick tests updated for the taker-pool-0 case).
- [ ] Dispatch a whole-phase review (Stage 2 only): focus on self-trade safety (taker ∉ makers under all pool sizes), the FAK/`success` handling, the `_last_print_fair` latch (no runaway prints; no print on failed settlement), and that the print never crosses the taker's own orders (takers never rest).

## Self-review notes
- Self-trade: disjoint pools guarantee taker ≠ maker; takers never rest (FAK) so a taker can't cross itself.
- Convergence: one print per ≥threshold Polymarket move; latch on real fill only.
- Stage-1 zero-trades tests must set `liquidity_taker_pool_size=0` (no taker → no seed print).
- Type check: `get_last_trade_price` return type; `PlaceOrderRequest` FAK support; `resp.success`/`resp.tradeIDs` fields (confirmed in Stage 1).
