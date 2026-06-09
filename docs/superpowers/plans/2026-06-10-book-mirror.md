# Book Mirror (Phase 5c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the synthetic liquidity ladder with a 1:1 live mirror of the real Polymarket order book (every real price level = one resting house order) plus a mirrored trade tape, fed by the Polymarket CLOB WebSocket market channel.

**Architecture:** An async WSS feed maintains in-memory `BookReplica`s (replace-semantics `price_change` events on top of `book` snapshots). A reconciler diffs each replica against the mirror account's live orders and applies minimal cancel/place operations through the existing `OrderService` (resting orders are signature+DB-only — zero chain txs). A tape writer turns `last_trade_price` events into synthetic `trades` rows (`STATUS='MIRRORED'`). One single "mirror account" owns everything.

**Tech Stack:** Python 3.13, FastAPI lifespan tasks, `websockets==12.0` (already in requirements.txt), httpx (REST seed), psycopg/Postgres, Anvil for integration tests.

**Spec:** `docs/superpowers/specs/2026-06-10-book-mirror-design.md` — read it first, especially §5 (non-crossing invariant) and §7 (bot interaction).

**Prerequisites for integration tests:** Postgres running (`agentpit` DB), forked Anvil + deployed exchange (`scripts/run_node.sh`, `scripts/deploy_exchange.sh`). Pure-unit tasks (1, 2, 5) need neither.

---

## File structure

| File | Status | Responsibility |
|---|---|---|
| `agentpit_bots/`, `tests/bots/` | **delete** (Task 0) | Attempt-1 external bots; zero imports from `agentpit/` |
| `agentpit/liquidity/replica.py` | **new** (Task 1) | Pure in-memory book replica; applies WSS events; exports safe snapshots |
| `agentpit/liquidity/reconciler.py` | **new** (Tasks 2, 6) | Pure diff (desired vs live levels) + DB/chain applier |
| `agentpit/liquidity/tape.py` | **new** (Task 4) | Synthetic `MIRRORED` trade rows from `last_trade_price` events |
| `agentpit/liquidity/feed.py` | **new** (Task 5) | WSS client (shards, PING, watchdog), REST seed, event routing (`MirrorState`) |
| `agentpit/liquidity/mirror.py` | **new** (Task 7) | `MirrorEngine`: target refresh, feed task + reconcile loop glue |
| `agentpit/db/table_read.py` | modify (Task 3) | `list_live_order_levels`, `foreign_touch` helpers |
| `agentpit/liquidity/engine.py`, `ladder.py`, `price_oracle.py` | **delete** (Task 7) | Replaced by the mirror |
| `agentpit/config.py` | modify (Task 7) | Drop 9 ladder/print fields; add 7 `mirror_*` fields; house count 100→1, drips 1→4 |
| `agentpit/api/app.py` | modify (Task 7) | Replace engine loop with feed + reconciler tasks |
| `agentpit/liquidity/house_accounts.py` | modify (Task 7) | Add `email_for(i)` helper (mirror account lookup); otherwise unchanged |
| `tests/liquidity/test_replica.py`, `test_mirror_diff.py`, `test_feed.py` | **new** | Pure-unit suites |
| `tests/onchain/test_mirror_tape.py`, `test_mirror_reconcile.py` | **new** | Integration suites |
| `tests/liquidity/test_ladder.py`, `test_price_oracle.py`, `tests/onchain/test_liquidity_tick.py`, `test_liquidity_arb.py` | **delete** (Task 7) | Test the deleted modules |
| `tests/onchain/test_liquidity_lifespan.py` | rewrite (Task 7) | Lifespan spawns/cancels mirror tasks |
| `scripts/mirror_smoke.py` | **new** (Task 8) | 60s live WSS capture; answers the open NO-side tape question |

Key existing interfaces (verified, do not re-derive):
- `OrderService(db, onchain).place_order(user, PlaceOrderRequest) -> OrderResponse` — fields `success, orderID, status, tradeIDs, errorMsg`. Non-crossing GTC = sign + DB insert only.
- `PlaceOrderRequest(token_id: str, side: "BUY"|"SELL", price: Decimal (0<p<1, snaps to 0.001), size: Decimal (shares), order_type="GTC")`.
- `OrderService.cancel_orders(user, order_ids) -> CancelOrdersResponse`; `cancel_market_orders(user, market=<condition_id str>, asset_id=None)`.
- `HouseAccountProvisioner(db, onchain, settings).ensure_provisioned() -> list[User]` (idempotent; returns ALL existing bot users plus shortfall).
- `OnchainAdmin.ctf_balance(eth_address, token_id_int) -> int`; `user_split_position(eth_key, condition_bytes, amount_micro)`.
- `Market.erc1155_tokens[0][0]` = local YES token id (str), `[1][0]` = NO; `market.condition_id.value` = local condition hex str; `market.polymarket_yes_token_id` = subscription key.
- `TableRead.list_active_synced_markets(conn)`, `list_bot_users(conn)`.
- `trades` insert columns: see `OrderService._insert_trade` (`order_service.py:695-752`); `MATCH_TIME` is **unix seconds** (WSS timestamps are ms strings — divide by 1000).
- Internal price/size unit: micro (1_000_000 == $1.00 == 1 share); price tick = 1000 micro (0.001).

---

### Task 0: Delete attempt-1 bots (`agentpit_bots/` + `tests/bots/`)

**Files:**
- Delete: `agentpit_bots/` (entire directory)
- Delete: `tests/bots/` (entire directory)

- [ ] **Step 1: Verify nothing outside the two directories imports agentpit_bots**

Run: `grep -rn "agentpit_bots" --include="*.py" agentpit/ scripts/ tests/ | grep -v "^tests/bots/"`
Expected: no output (docs/ references are fine — they are history).

- [ ] **Step 2: Delete both directories**

```bash
git rm -r -q agentpit_bots tests/bots
```

- [ ] **Step 3: Run the full suite to prove nothing else broke**

Run: `pytest -q`
Expected: all tests pass; total count drops by ~68 (the deleted `tests/bots` suite).

- [ ] **Step 4: Commit**

```bash
git commit -m "chore: remove attempt-1 external bots (agentpit_bots + tests/bots)"
```

---

### Task 1: `BookReplica` — pure replica of one Polymarket book

**Files:**
- Create: `agentpit/liquidity/replica.py`
- Test: `tests/liquidity/test_replica.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/liquidity/test_replica.py
from agentpit.liquidity.replica import MICRO, TICK, BookReplica, to_micro


def _book_msg(asset="A", bids=None, asks=None):
    return {
        "event_type": "book", "asset_id": asset,
        "bids": [{"price": p, "size": s} for p, s in (bids or [])],
        "asks": [{"price": p, "size": s} for p, s in (asks or [])],
    }


def test_to_micro_decimal_strings_never_float():
    assert to_micro("0.48") == 480_000
    assert to_micro(".5") == 500_000          # Polymarket emits ".48"-style strings
    assert to_micro("0.980") == 980_000       # trailing-zero variant
    assert to_micro("145369.13") == 145_369_130_000
    assert to_micro("garbage") is None
    assert to_micro(None) is None


def test_apply_book_replaces_state_and_seeds():
    r = BookReplica("A")
    assert r.snapshot() is None               # unseeded → unusable
    assert r.apply_book(_book_msg(bids=[("0.40", "10")], asks=[("0.60", "5")]))
    assert r.apply_book(_book_msg(bids=[("0.45", "7")], asks=[("0.55", "3")]))
    snap = r.snapshot()
    assert snap.bids == ((450_000, 7_000_000),)   # fully replaced, not merged
    assert snap.asks == ((550_000, 3_000_000),)


def test_apply_book_wrong_asset_rejected():
    r = BookReplica("A")
    assert not r.apply_book(_book_msg(asset="B", bids=[("0.4", "1")]))
    assert r.snapshot() is None


def test_apply_book_skips_off_tick_zero_and_garbage_levels():
    r = BookReplica("A")
    r.apply_book(_book_msg(
        bids=[("0.4005", "10"), ("0.40", "0"), ("x", "1"), ("0.41", "2")],
        asks=[("0.60", "1")]))
    snap = r.snapshot()
    assert snap.bids == ((410_000, 2_000_000),)   # off-tick, zero-size, garbage dropped


def test_snapshot_orders_best_first_regardless_of_input_order():
    # Live feed sends arrays worst-to-best; never trust array order.
    r = BookReplica("A")
    r.apply_book(_book_msg(
        bids=[("0.10", "1"), ("0.40", "2")],     # ascending (worst first)
        asks=[("0.90", "1"), ("0.60", "2")]))    # descending (worst first)
    snap = r.snapshot()
    assert snap.bids[0] == (400_000, 2_000_000)  # best bid first
    assert snap.asks[0] == (600_000, 2_000_000)  # best (lowest) ask first


def test_price_change_replace_semantics_and_delete():
    r = BookReplica("A")
    r.apply_book(_book_msg(bids=[("0.40", "10")], asks=[("0.60", "5")]))
    assert r.apply_price_change_entry(
        {"asset_id": "A", "side": "BUY", "price": "0.40", "size": "3"})
    assert r.snapshot().bids == ((400_000, 3_000_000),)   # replace, not add
    assert r.apply_price_change_entry(
        {"asset_id": "A", "side": "BUY", "price": "0.40", "size": "0"})
    assert r.snapshot().bids == ()                        # size 0 = level removed
    assert r.apply_price_change_entry(
        {"asset_id": "A", "side": "SELL", "price": "0.61", "size": "2"})
    assert r.snapshot().asks == ((600_000, 5_000_000), (610_000, 2_000_000))


def test_price_change_sibling_asset_filtered():
    # price_change messages carry mirrored entries for BOTH sibling asset_ids.
    r = BookReplica("A")
    r.apply_book(_book_msg(bids=[("0.40", "10")], asks=[("0.60", "5")]))
    assert not r.apply_price_change_entry(
        {"asset_id": "SIBLING", "side": "SELL", "price": "0.60", "size": "9"})
    assert r.snapshot().bids == ((400_000, 10_000_000),)


def test_price_change_before_seed_ignored():
    r = BookReplica("A")
    assert not r.apply_price_change_entry(
        {"asset_id": "A", "side": "BUY", "price": "0.40", "size": "3"})


def test_tick_size_change_resets_epoch_until_fresh_snapshot():
    r = BookReplica("A")
    r.apply_book(_book_msg(bids=[("0.40", "10")], asks=[("0.60", "5")]))
    r.mark_stale()                                        # tick_size_change / watchdog
    assert r.snapshot() is None
    assert not r.apply_price_change_entry(                # deltas dropped while stale
        {"asset_id": "A", "side": "BUY", "price": "0.40", "size": "3"})
    r.apply_book(_book_msg(bids=[("0.30", "1")], asks=[("0.70", "1")]))
    assert r.snapshot().bids == ((300_000, 1_000_000),)   # fresh snapshot re-seeds


def test_crossed_replica_yields_no_snapshot():
    r = BookReplica("A")
    r.apply_book(_book_msg(bids=[("0.60", "1")], asks=[("0.55", "1")]))
    assert r.snapshot() is None


def test_one_sided_and_empty_books_are_valid():
    r = BookReplica("A")
    r.apply_book(_book_msg(bids=[("0.40", "1")], asks=[]))
    snap = r.snapshot()
    assert snap.bids == ((400_000, 1_000_000),) and snap.asks == ()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/liquidity/test_replica.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentpit.liquidity.replica'`

- [ ] **Step 3: Implement `replica.py`**

```python
# agentpit/liquidity/replica.py
"""Pure in-memory replica of one Polymarket order book (one asset_id).

Fed by CLOB WSS market-channel events. No I/O. All prices/sizes are integer
micro units (1_000_000 == $1.00 == 1 share), parsed from the feed's decimal
STRINGS via Decimal — never through float.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

MICRO = 1_000_000
TICK = 1_000  # 0.001 — the local book's price grid


def to_micro(value) -> int | None:
    """Decimal string -> integer micro units; None on garbage."""
    if value is None:
        return None
    try:
        return int((Decimal(str(value)) * MICRO).to_integral_value())
    except (InvalidOperation, ValueError, TypeError):
        return None


@dataclass(frozen=True)
class BookSnapshot:
    """Immutable, validated view: levels sorted best-first."""
    asset_id: str
    bids: tuple[tuple[int, int], ...]  # (price_micro, size_micro), best (highest) first
    asks: tuple[tuple[int, int], ...]  # best (lowest) first


def _clean_levels(levels) -> dict[int, int]:
    out: dict[int, int] = {}
    for lvl in levels or []:
        if not isinstance(lvl, dict):
            continue
        p, s = to_micro(lvl.get("price")), to_micro(lvl.get("size"))
        if p is None or s is None or s <= 0:
            continue
        if not (0 < p < MICRO) or p % TICK:
            continue  # outside (0,1) or off the local 0.001 grid
        out[p] = s
    return out


class BookReplica:
    def __init__(self, asset_id: str):
        self.asset_id = asset_id
        self.bids: dict[int, int] = {}  # price_micro -> size_micro
        self.asks: dict[int, int] = {}
        self.seeded = False
        self.stale = False  # tick_size_change / watchdog: drop deltas, await snapshot

    def apply_book(self, msg: dict) -> bool:
        """Full snapshot: REPLACES the book. Returns True if applied."""
        if msg.get("asset_id") != self.asset_id:
            return False
        self.bids = _clean_levels(msg.get("bids"))
        self.asks = _clean_levels(msg.get("asks"))
        self.seeded = True
        self.stale = False
        return True

    def apply_price_change_entry(self, entry: dict) -> bool:
        """One price_changes[] entry. size is the NEW TOTAL at that level
        (replace semantics); size 0 removes the level. Returns True if applied."""
        if entry.get("asset_id") != self.asset_id or not self.seeded or self.stale:
            return False
        side = entry.get("side")
        p, s = to_micro(entry.get("price")), to_micro(entry.get("size"))
        if side not in ("BUY", "SELL") or p is None or s is None or s < 0:
            return False
        if not (0 < p < MICRO) or p % TICK:
            return False
        book = self.bids if side == "BUY" else self.asks
        if s == 0:
            book.pop(p, None)
        else:
            book[p] = s
        return True

    def mark_stale(self) -> None:
        """Epoch reset (tick_size_change / watchdog): drop state, await snapshot."""
        self.bids.clear()
        self.asks.clear()
        self.seeded = False
        self.stale = True

    def snapshot(self) -> BookSnapshot | None:
        """Validated frozen view, or None when unusable (unseeded/stale/crossed)."""
        if not self.seeded or self.stale:
            return None
        if self.bids and self.asks and max(self.bids) >= min(self.asks):
            return None  # crossed upstream data — never reconcile from this
        return BookSnapshot(
            asset_id=self.asset_id,
            bids=tuple(sorted(self.bids.items(), key=lambda kv: -kv[0])),
            asks=tuple(sorted(self.asks.items())),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/liquidity/test_replica.py -q`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add agentpit/liquidity/replica.py tests/liquidity/test_replica.py
git commit -m "feat(liquidity): BookReplica — pure Polymarket book replica with replace-semantics deltas"
```

---

### Task 2: Pure diff — desired mirror levels vs live orders

**Files:**
- Create: `agentpit/liquidity/reconciler.py` (pure part only; the applier is Task 6)
- Test: `tests/liquidity/test_mirror_diff.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/liquidity/test_mirror_diff.py
from agentpit.liquidity.replica import MICRO, BookSnapshot
from agentpit.liquidity.reconciler import (
    LiveLevel, Placement, cap_sells_to_inventory, desired_levels, diff_levels,
    split_target_micro,
)

YES, NO = "tok-yes", "tok-no"


def _snap(bids=(), asks=()):
    return BookSnapshot(asset_id="pm-yes", bids=tuple(bids), asks=tuple(asks))


def test_desired_levels_yes_verbatim_no_complement():
    snap = _snap(bids=[(400_000, 10)], asks=[(600_000, 5)])
    got = set(desired_levels(snap, YES, NO))
    assert got == {
        Placement(YES, "BUY", 400_000, 10),     # YES bid verbatim
        Placement(NO, "SELL", 600_000, 10),     # its complement: SELL NO @ 1-0.40
        Placement(YES, "SELL", 600_000, 5),     # YES ask verbatim
        Placement(NO, "BUY", 400_000, 5),       # its complement: BUY NO @ 1-0.60
    }


def test_desired_levels_never_cross_within_either_token():
    # Non-crossed YES snapshot must yield non-crossed YES and NO books (spec §5).
    snap = _snap(bids=[(400_000, 1), (300_000, 2)], asks=[(410_000, 1), (900_000, 3)])
    desired = desired_levels(snap, YES, NO)
    for tok in (YES, NO):
        bids = [d.price_micro for d in desired if d.token_id == tok and d.side == "BUY"]
        asks = [d.price_micro for d in desired if d.token_id == tok and d.side == "SELL"]
        assert max(bids) < min(asks)


def test_diff_noop_when_book_already_mirrored():
    snap = _snap(bids=[(400_000, 10)], asks=[(600_000, 5)])
    current = [
        LiveLevel("o1", YES, "BUY", 400_000, 10),
        LiveLevel("o2", NO, "SELL", 600_000, 10),
        LiveLevel("o3", YES, "SELL", 600_000, 5),
        LiveLevel("o4", NO, "BUY", 400_000, 5),
    ]
    cancels, places = diff_levels(desired_levels(snap, YES, NO), current)
    assert cancels == [] and places == []


def test_diff_size_change_is_cancel_plus_place():
    snap = _snap(bids=[(400_000, 7)], asks=())
    current = [LiveLevel("o1", YES, "BUY", 400_000, 10),
               LiveLevel("o2", NO, "SELL", 600_000, 10)]
    cancels, places = diff_levels(desired_levels(snap, YES, NO), current)
    assert set(cancels) == {"o1", "o2"}
    assert set(places) == {Placement(YES, "BUY", 400_000, 7),
                           Placement(NO, "SELL", 600_000, 7)}


def test_diff_removed_level_cancelled_new_level_placed():
    snap = _snap(bids=[(410_000, 3)], asks=())
    current = [LiveLevel("o1", YES, "BUY", 400_000, 3),
               LiveLevel("o2", NO, "SELL", 600_000, 3)]
    cancels, places = diff_levels(desired_levels(snap, YES, NO), current)
    assert set(cancels) == {"o1", "o2"}
    assert set(places) == {Placement(YES, "BUY", 410_000, 3),
                           Placement(NO, "SELL", 590_000, 3)}


def test_diff_duplicate_orders_at_one_level_keep_one_cancel_rest():
    # Crash mid-cycle can leave two orders at one level; keep one, cancel the dupe.
    snap = _snap(bids=[(400_000, 10)], asks=())
    current = [
        LiveLevel("o1", YES, "BUY", 400_000, 10),
        LiveLevel("o1b", YES, "BUY", 400_000, 10),
        LiveLevel("o2", NO, "SELL", 600_000, 10),
    ]
    cancels, places = diff_levels(desired_levels(snap, YES, NO), current)
    assert cancels == ["o1b"] and places == []


def test_split_target_is_max_of_both_ask_sides():
    # YES asks need YES inventory; NO asks (= complement of YES bids) need NO.
    snap = _snap(bids=[(400_000, 70), (100_000, 30)], asks=[(600_000, 40)])
    assert split_target_micro(snap) == 100  # max(40, 70+30)


def test_cap_sells_keeps_best_prices_first():
    places = [
        Placement(YES, "SELL", 700_000, 6),
        Placement(YES, "SELL", 600_000, 5),   # best ask — must survive
        Placement(YES, "BUY", 400_000, 99),   # buys never capped
        Placement(NO, "SELL", 500_000, 4),
    ]
    got = cap_sells_to_inventory(places, {YES: 8, NO: 0})
    assert Placement(YES, "SELL", 600_000, 5) in got
    assert Placement(YES, "SELL", 700_000, 6) not in got   # inventory exhausted (8 < 5+6)
    assert Placement(NO, "SELL", 500_000, 4) not in got    # zero NO inventory
    assert Placement(YES, "BUY", 400_000, 99) in got
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/liquidity/test_mirror_diff.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentpit.liquidity.reconciler'`

- [ ] **Step 3: Implement the pure part of `reconciler.py`**

```python
# agentpit/liquidity/reconciler.py
"""Diff a Polymarket BookSnapshot against the mirror account's live orders.

Pure functions in this module; the DB/chain applier (reconcile_market) is
added in a later task. Invariant (spec §5): desired levels derived from a
non-crossed snapshot are non-crossed per token AND across the YES/NO
complement map, so the mirror can never self-match — provided cancels are
applied before placements.
"""
from dataclasses import dataclass

from agentpit.liquidity.replica import MICRO, BookSnapshot


@dataclass(frozen=True)
class LiveLevel:
    order_id: str
    token_id: str
    side: str          # "BUY" | "SELL"
    price_micro: int
    size_micro: int    # REMAINING_AMOUNT


@dataclass(frozen=True)
class Placement:
    token_id: str
    side: str
    price_micro: int
    size_micro: int


def desired_levels(snap: BookSnapshot, yes_token: str, no_token: str) -> list[Placement]:
    """YES book verbatim + NO book as the exact 1-p complement (same sizes)."""
    out: list[Placement] = []
    for p, s in snap.bids:
        out.append(Placement(yes_token, "BUY", p, s))
        out.append(Placement(no_token, "SELL", MICRO - p, s))
    for p, s in snap.asks:
        out.append(Placement(yes_token, "SELL", p, s))
        out.append(Placement(no_token, "BUY", MICRO - p, s))
    return out


def diff_levels(
    desired: list[Placement], current: list[LiveLevel]
) -> tuple[list[str], list[Placement]]:
    """(order_ids to cancel, placements to make). Orders are immutable, so a
    size change at a level is cancel + re-place. One live order per
    (token, side, price) is kept; duplicates are cancelled."""
    want = {(d.token_id, d.side, d.price_micro): d.size_micro for d in desired}
    keep: set[tuple[str, str, int]] = set()
    cancels: list[str] = []
    for o in current:
        key = (o.token_id, o.side, o.price_micro)
        if key in want and want[key] == o.size_micro and key not in keep:
            keep.add(key)
        else:
            cancels.append(o.order_id)
    places = [
        Placement(token, side, price, size)
        for (token, side, price), size in want.items()
        if (token, side, price) not in keep
    ]
    return cancels, places


def split_target_micro(snap: BookSnapshot) -> int:
    """CTF inventory needed to back every SELL: YES asks need YES tokens, NO
    asks mirror the YES bid side. A split mints YES+NO equally, so the target
    is the max of the two ask-side sums (spec §8)."""
    yes_ask_sum = sum(s for _, s in snap.asks)
    no_ask_sum = sum(s for _, s in snap.bids)
    return max(yes_ask_sum, no_ask_sum)


def cap_sells_to_inventory(
    places: list[Placement], inventory_micro: dict[str, int]
) -> list[Placement]:
    """Drop SELL placements that exceed held CTF inventory, keeping the best
    (lowest-priced) asks. BUYs pass through (USDC is never the binding
    constraint). Result preserves no particular order."""
    remaining = dict(inventory_micro)
    out = [p for p in places if p.side == "BUY"]
    sells = sorted((p for p in places if p.side == "SELL"), key=lambda p: p.price_micro)
    for p in sells:
        held = remaining.get(p.token_id, 0)
        if p.size_micro <= held:
            remaining[p.token_id] = held - p.size_micro
            out.append(p)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/liquidity/test_mirror_diff.py tests/liquidity/test_replica.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add agentpit/liquidity/reconciler.py tests/liquidity/test_mirror_diff.py
git commit -m "feat(liquidity): pure mirror diff — desired levels, cancel/place sets, inventory caps"
```

---

### Task 3: `TableRead` helpers — live mirror levels + foreign touch

**Files:**
- Modify: `agentpit/db/table_read.py` (add two static methods, after `list_active_synced_markets`)
- Test: `tests/db/test_table_read_mirror.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/db/test_table_read_mirror.py
import uuid

from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead

_ORDER_COLS = (
    "API_KEY, PRICE, POST_ONLY, ORDER_TYPE, SALT, MAKER, TAKER, SIGNER, TOKEN_ID, "
    "MAKER_AMOUNT, TAKER_AMOUNT, EXPIRATION, NONCE, FEE_RATE_BPS, SIDE, "
    "SIGNATURE_TYPE, SIGNATURE, ORDER_JSON, STATUS, REMAINING_AMOUNT, CREATED_AT, ORDER_ID"
)


def _insert_order(conn, *, api_key, token, side, price, remaining, status="live"):
    conn.execute(
        f"INSERT INTO orders ({_ORDER_COLS}) VALUES "
        "(%s,%s,0,'GTC','0','0x0','0x0','0x0',%s,0,0,0,0,0,%s,'EIP712','sig','{}',%s,%s,0,%s)",
        (api_key, price, token, side, status, remaining, uuid.uuid4().hex),
    )


def test_list_live_order_levels_scopes_by_key_token_and_status():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        _insert_order(conn, api_key="mirror", token="T1", side="BUY",
                      price=400_000, remaining=5)
        _insert_order(conn, api_key="mirror", token="T1", side="SELL",
                      price=600_000, remaining=3, status="cancelled")   # not live
        _insert_order(conn, api_key="mirror", token="T9", side="BUY",
                      price=100_000, remaining=1)                       # other token
        _insert_order(conn, api_key="someone", token="T1", side="BUY",
                      price=410_000, remaining=2)                       # other owner
    with db.read() as conn:
        rows = TableRead.list_live_order_levels(conn, "mirror", ["T1", "T2"])
    assert [(r["TOKEN_ID"], r["SIDE"], int(r["PRICE"]), int(r["REMAINING_AMOUNT"]))
            for r in rows] == [("T1", "BUY", 400_000, 5)]


def test_foreign_touch_excludes_own_orders():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        _insert_order(conn, api_key="mirror", token="T3", side="BUY",
                      price=990_000, remaining=1)        # own — must be ignored
        _insert_order(conn, api_key="bot", token="T3", side="BUY",
                      price=450_000, remaining=1)
        _insert_order(conn, api_key="bot2", token="T3", side="SELL",
                      price=520_000, remaining=1)
    with db.read() as conn:
        bid, ask = TableRead.foreign_touch(conn, "mirror", "T3")
        none_bid, none_ask = TableRead.foreign_touch(conn, "mirror", "T-EMPTY")
    assert (bid, ask) == (450_000, 520_000)
    assert (none_bid, none_ask) == (None, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_table_read_mirror.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'list_live_order_levels'`

- [ ] **Step 3: Add the helpers to `TableRead`**

Insert directly after `list_active_synced_markets` in `agentpit/db/table_read.py`:

```python
    @staticmethod
    def list_live_order_levels(
        db: psycopg.Connection, api_key: str, token_ids: list[str]
    ) -> list[dict]:
        """The mirror account's live orders on the given tokens — the
        'current' side of the reconciler diff."""
        if not token_ids:
            return []
        placeholders = ",".join("%s" for _ in token_ids)
        return db.execute(
            "SELECT ORDER_ID, TOKEN_ID, SIDE, PRICE, REMAINING_AMOUNT FROM orders "
            f"WHERE API_KEY = %s AND STATUS = 'live' AND TOKEN_ID IN ({placeholders})",
            [api_key, *token_ids],
        ).fetchall()

    @staticmethod
    def foreign_touch(
        db: psycopg.Connection, own_api_key: str, token_id: str
    ) -> tuple[int | None, int | None]:
        """(best_bid, best_ask) among OTHER owners' live orders on one token.
        The reconciler uses this to budget placements that would cross a real
        user's order (an intentional fill — spec §7)."""
        rows = db.execute(
            "SELECT SIDE, MAX(PRICE) AS MX, MIN(PRICE) AS MN FROM orders "
            "WHERE TOKEN_ID = %s AND STATUS = 'live' AND API_KEY != %s "
            "GROUP BY SIDE",
            (token_id, own_api_key),
        ).fetchall()
        bid = ask = None
        for r in rows:
            if r["SIDE"] == "BUY":
                bid = int(r["MX"])
            elif r["SIDE"] == "SELL":
                ask = int(r["MN"])
        return bid, ask
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/db/test_table_read_mirror.py -q`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add agentpit/db/table_read.py tests/db/test_table_read_mirror.py
git commit -m "feat(db): mirror reconciler reads — live order levels + foreign touch"
```

---

### Task 4: `tape.py` — synthetic `MIRRORED` trade rows

**Files:**
- Create: `agentpit/liquidity/tape.py`
- Test: `tests/onchain/test_mirror_tape.py` (needs Anvil to create a market via `POST /markets`)

- [ ] **Step 1: Write the failing test**

```python
# tests/onchain/test_mirror_tape.py
from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.liquidity.tape import MIRROR_API_KEY, MIRROR_TRADE_STATUS, insert_mirrored_trade
from tests.onchain._helpers import create_market, fresh_client


def test_mirrored_trade_feeds_last_trade_price_but_no_user_feed():
    client = fresh_client()
    m = create_market(client)
    cond = m["condition_id"]["value"]
    yes_token = m["erc1155_tokens"][0][0]

    db = DbSession(Settings().database_url)
    with db.write() as conn:
        trade_id = insert_mirrored_trade(
            conn, condition_id=cond, local_token_id=yes_token,
            price_micro=480_000, size_micro=2_500_000, side="BUY",
            match_time_s=1_700_000_000,
        )

    with db.read() as conn:
        row = conn.execute(
            "SELECT * FROM trades WHERE TRADE_ID = %s", (trade_id,)).fetchone()
    assert row["STATUS"] == MIRROR_TRADE_STATUS
    assert row["TAKER_API_KEY"] == MIRROR_API_KEY      # never a real user's key
    assert int(row["PRICE"]) == 480_000

    # Token-scoped readers see it (STATUS != 'FAILED' filter passes)...
    book = client.get(f"/book?token_id={yes_token}").json()
    assert book["last_trade_price"] == "0.48"

    # ...user-scoped feeds can't: trades are keyed by real API keys only.
    with db.read() as conn:
        rows = TableRead.list_trades_for_api_key(conn, "any-real-user-key")
    assert all(r["TRADE_ID"] != trade_id for r in rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/onchain/test_mirror_tape.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentpit.liquidity.tape'`

- [ ] **Step 3: Implement `tape.py`**

```python
# agentpit/liquidity/tape.py
"""Mirror the real Polymarket tape: one synthetic trades row per
last_trade_price WSS event.

STATUS='MIRRORED' is distinct for provenance yet passes every reader's
`STATUS != 'FAILED'` filter (last-trade-price, price history, charts).
TAKER/MAKER_API_KEY are fabricated constants so user-scoped feeds
(/data/trades, /activity) never surface these rows. No FK constraints exist
on trades (table_create.py), so order-less rows are safe.
"""
import secrets

import psycopg

MIRROR_TRADE_STATUS = "MIRRORED"
MIRROR_API_KEY = "mirror-tape"  # opaque, never a real user's api key


def insert_mirrored_trade(
    conn: psycopg.Connection,
    *,
    condition_id: str,
    local_token_id: str,
    price_micro: int,
    size_micro: int,
    side: str,
    match_time_s: int,
) -> str:
    trade_id = f"mirror-{secrets.token_hex(12)}"
    conn.execute(
        """
        INSERT INTO trades (
            TRADE_ID, TAKER_ORDER_ID, MAKER_ORDERS, MARKET, ASSET_ID,
            PRICE, TRADE_SIZE, REMAINING_SIZE, SIDE, STATUS,
            MATCH_TIME, TRANSACTION_HASH, BUCKET_INDEX, FEE_RATE_BPS,
            TAKER_API_KEY, MAKER_API_KEY
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            trade_id, "", "[]", condition_id, local_token_id,
            price_micro, size_micro, 0, side, MIRROR_TRADE_STATUS,
            match_time_s, "", 0, 0,
            MIRROR_API_KEY, MIRROR_API_KEY,
        ),
    )
    return trade_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/onchain/test_mirror_tape.py -q`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add agentpit/liquidity/tape.py tests/onchain/test_mirror_tape.py
git commit -m "feat(liquidity): synthetic MIRRORED tape rows from real Polymarket trades"
```

---

### Task 5: `feed.py` — WSS client, REST seed, event routing

**Files:**
- Create: `agentpit/liquidity/feed.py`
- Test: `tests/liquidity/test_feed.py` (pure + fake-websocket async tests; no network)

- [ ] **Step 1: Write the failing tests**

```python
# tests/liquidity/test_feed.py
import asyncio
import json

import pytest

from agentpit.liquidity.feed import (
    MarketRef, MirrorState, fetch_books_rest, parse_events, run_connection, shard,
)


def _ref(pm="PM-YES", market_id=1):
    return MarketRef(market_id=market_id, condition_id=f"0xc{market_id}",
                     yes_token=f"y{market_id}", no_token=f"n{market_id}",
                     pm_yes_token=pm)


def test_parse_events_handles_both_framings_and_garbage():
    assert parse_events('{"event_type":"book"}') == [{"event_type": "book"}]
    assert parse_events('[{"a":1},{"b":2}]') == [{"a": 1}, {"b": 2}]
    assert parse_events("PONG") == []
    assert parse_events("[1,2]") == []


def test_shard():
    assert shard(list(range(5)), 2) == [[0, 1], [2, 3], [4]]
    assert shard([], 2) == []


def test_state_routes_book_and_price_change_and_marks_dirty():
    st = MirrorState([_ref()])
    st.handle_event({"event_type": "book", "asset_id": "PM-YES",
                     "bids": [{"price": "0.4", "size": "1"}], "asks": []})
    assert "PM-YES" in st.dirty
    st.dirty.clear()
    st.handle_event({"event_type": "price_change", "price_changes": [
        {"asset_id": "PM-YES", "side": "BUY", "price": "0.41", "size": "2"},
        {"asset_id": "UNKNOWN", "side": "SELL", "price": "0.6", "size": "9"},
    ]})
    assert st.dirty == {"PM-YES"}
    assert st.replicas["PM-YES"].bids == {400_000: 1_000_000, 410_000: 2_000_000}


def test_state_tick_size_change_marks_stale_not_dirty():
    st = MirrorState([_ref()])
    st.handle_event({"event_type": "book", "asset_id": "PM-YES",
                     "bids": [], "asks": [{"price": "0.6", "size": "1"}]})
    st.dirty.clear()
    st.handle_event({"event_type": "tick_size_change", "asset_id": "PM-YES"})
    assert st.replicas["PM-YES"].stale and st.dirty == set()


def test_state_queues_only_known_asset_trades():
    st = MirrorState([_ref()])
    st.handle_event({"event_type": "last_trade_price", "asset_id": "PM-YES",
                     "price": "0.5", "size": "10", "side": "BUY",
                     "timestamp": "1700000000000"})
    st.handle_event({"event_type": "last_trade_price", "asset_id": "UNKNOWN",
                     "price": "0.5", "size": "10", "side": "BUY",
                     "timestamp": "1700000000000"})
    assert len(st.trades) == 1


def test_fetch_books_rest_batches_and_applies():
    calls = []

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return [{"asset_id": tid["token_id"], "bids": [], "asks": []}
                    for tid in calls[-1]]

    class FakeClient:
        def post(self, url, json):
            calls.append(json)
            return FakeResp()

    ids = [f"a{i}" for i in range(250)]
    books = fetch_books_rest(ids, client=FakeClient(), batch_size=100)
    assert [len(c) for c in calls] == [100, 100, 50]
    assert len(books) == 250


class FakeWs:
    """Scripted websocket: yields queued frames, then times out forever."""
    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)

    async def recv(self):
        if self.frames:
            return self.frames.pop(0)
        await asyncio.sleep(3600)

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


@pytest.mark.asyncio
async def test_run_connection_subscribes_routes_pings_then_watchdog_stales():
    ref = _ref()
    st = MirrorState([ref])
    book = json.dumps([{"event_type": "book", "asset_id": "PM-YES",
                        "bids": [{"price": "0.4", "size": "1"}], "asks": []}])
    ws = FakeWs([book, "PONG"])

    def connect(url):
        return ws

    task = asyncio.create_task(run_connection(
        st, ["PM-YES"], connect=connect,
        ping_interval=0.05, watchdog_seconds=0.5, reconnect_delay=10.0))
    await asyncio.sleep(0.2)
    # Phase 1: subscribed, book routed, PING sent on idle — before the watchdog.
    sub = json.loads(ws.sent[0])
    assert sub == {"assets_ids": ["PM-YES"], "type": "market"}
    assert "PING" in ws.sent[1:]                  # keepalive sent on idle
    assert st.replicas["PM-YES"].seeded

    await asyncio.sleep(0.6)
    # Phase 2: 0.5s with no events → watchdog tripped → replica marked stale
    # (it re-seeds from the fresh snapshot a real reconnect delivers).
    assert st.replicas["PM-YES"].stale

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
```

Note: `pytest.mark.asyncio` requires `pytest-asyncio`. Check `pip show pytest-asyncio`; if absent, add `pytest-asyncio==0.23.*` to `requirements.txt`, `pip install pytest-asyncio==0.23.*`, and add `asyncio_mode = auto` under `[pytest]` in `pytest.ini` (then the decorator may be dropped, but keeping it is harmless).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/liquidity/test_feed.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentpit.liquidity.feed'`

- [ ] **Step 3: Implement `feed.py`**

```python
# agentpit/liquidity/feed.py
"""Polymarket CLOB market-channel client + event routing for the book mirror.

Connection facts (verified live, spec §3): public channel, subscribe with
{"assets_ids": [...], "type": "market"}; ≤200 assets per connection (the real
cap ~500 fails SILENTLY — no initial snapshots); client sends the text frame
"PING" every 10s; PING/PONG is NOT a data-liveness signal (known silent-freeze
server bug), so an event-inactivity watchdog forces a reconnect, and the fresh
'book' snapshots delivered on re-subscribe are the resync point. Messages may
be a JSON array of events or a single event object.
"""
import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass

import httpx

from agentpit.liquidity.replica import BookReplica

log = logging.getLogger(__name__)

WSS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
CLOB_BOOKS_URL = "https://clob.polymarket.com/books"
# Plain non-browser clients get Cloudflare 403s on the CLOB REST API.
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; agentpit-mirror/1.0)"}


@dataclass(frozen=True)
class MarketRef:
    """Everything the mirror needs per market, both id namespaces resolved."""
    market_id: int
    condition_id: str    # LOCAL condition id (hex str) — order/cancel scoping
    yes_token: str       # local erc1155_tokens[0][0]
    no_token: str        # local erc1155_tokens[1][0]
    pm_yes_token: str    # POLYMARKET_YES_TOKEN_ID — subscription key


def parse_events(raw) -> list[dict]:
    """WSS frames arrive as a JSON array of events OR a single event object."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    return []


def shard(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


class MirrorState:
    """Shared mutable state between the feed (writer) and reconciler (reader).
    Single event loop — no locking needed; the reconciler only reads validated
    immutable snapshots."""

    def __init__(self, refs: list[MarketRef]):
        self.by_asset: dict[str, MarketRef] = {}
        self.replicas: dict[str, BookReplica] = {}
        self.dirty: set[str] = set()       # pm asset ids needing a reconcile
        self.trades: deque = deque()       # raw last_trade_price events
        self.set_targets(refs)

    def set_targets(self, refs: list[MarketRef]) -> tuple[list[MarketRef], list[MarketRef]]:
        """Replace the target set. Returns (added, removed) refs."""
        new = {r.pm_yes_token: r for r in refs}
        added = [r for a, r in new.items() if a not in self.by_asset]
        removed = [r for a, r in self.by_asset.items() if a not in new]
        for r in removed:
            self.replicas.pop(r.pm_yes_token, None)
            self.dirty.discard(r.pm_yes_token)
        for r in added:
            self.replicas[r.pm_yes_token] = BookReplica(r.pm_yes_token)
        self.by_asset = new
        return added, removed

    def handle_event(self, ev: dict) -> None:
        et = ev.get("event_type")
        if et == "book":
            rep = self.replicas.get(ev.get("asset_id"))
            if rep is not None and rep.apply_book(ev):
                self.dirty.add(rep.asset_id)
        elif et == "price_change":
            for entry in ev.get("price_changes") or []:
                if not isinstance(entry, dict):
                    continue
                rep = self.replicas.get(entry.get("asset_id"))
                if rep is not None and rep.apply_price_change_entry(entry):
                    self.dirty.add(rep.asset_id)
        elif et == "tick_size_change":
            rep = self.replicas.get(ev.get("asset_id"))
            if rep is not None:
                rep.mark_stale()           # epoch reset — await a fresh snapshot
                self.dirty.discard(rep.asset_id)
        elif et == "last_trade_price":
            if ev.get("asset_id") in self.by_asset:
                self.trades.append(ev)


def fetch_books_rest(
    asset_ids: list[str], *, client=None, batch_size: int = 100
) -> list[dict]:
    """Batch REST seed via POST /books (rate limit 500 req/10s — fine).
    Returns raw book payloads (same shape as the WSS 'book' event)."""
    cl = client or httpx.Client(headers=_HEADERS, timeout=15.0)
    out: list[dict] = []
    for batch in shard(asset_ids, batch_size):
        try:
            resp = cl.post(CLOB_BOOKS_URL, json=[{"token_id": a} for a in batch])
            resp.raise_for_status()
            body = resp.json()
        except Exception:
            log.exception("REST /books seed failed for a batch of %d", len(batch))
            continue
        out.extend(b for b in body if isinstance(b, dict))
    return out


async def run_connection(
    state: MirrorState,
    asset_ids: list[str],
    *,
    connect=None,
    ping_interval: float = 10.0,
    watchdog_seconds: float = 120.0,
    reconnect_delay: float = 2.0,
) -> None:
    """One sharded connection: subscribe, route events, PING on idle, and
    force a reconnect when no events arrive within the watchdog window
    (re-subscribing yields fresh 'book' snapshots — the resync point)."""
    if connect is None:
        import websockets
        connect = lambda url: websockets.connect(url)  # noqa: E731
    while True:
        try:
            async with connect(WSS_URL) as ws:
                await ws.send(json.dumps({"assets_ids": asset_ids, "type": "market"}))
                idle = 0.0
                while idle < watchdog_seconds:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=ping_interval)
                    except TimeoutError:
                        idle += ping_interval
                        await ws.send("PING")
                        continue
                    events = parse_events(raw)
                    if events:
                        idle = 0.0
                        for ev in events:
                            state.handle_event(ev)
                log.warning(
                    "mirror feed watchdog tripped (%ss silent, %d assets) — reconnecting",
                    watchdog_seconds, len(asset_ids))
                for a in asset_ids:        # stale until the re-subscribe snapshot
                    rep = state.replicas.get(a)
                    if rep is not None:
                        rep.mark_stale()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("mirror feed connection error (%d assets)", len(asset_ids))
        await asyncio.sleep(reconnect_delay)
```

Note for Python 3.13: `asyncio.wait_for` raises the builtin `TimeoutError` (aliased to `asyncio.TimeoutError`), so `except TimeoutError` is correct.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/liquidity/test_feed.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add agentpit/liquidity/feed.py tests/liquidity/test_feed.py requirements.txt pytest.ini
git commit -m "feat(liquidity): mirror feed — WSS client with watchdog, REST seed, event routing"
```

---

### Task 6: `reconcile_market` — apply the diff through OrderService

**Files:**
- Modify: `agentpit/liquidity/reconciler.py` (add the applier below the pure functions)
- Test: `tests/onchain/test_mirror_reconcile.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/onchain/test_mirror_reconcile.py
from decimal import Decimal

from agentpit.config import Settings
from agentpit.datastructures.place_order_request import PlaceOrderRequest
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.liquidity.feed import MarketRef
from agentpit.liquidity.house_accounts import HouseAccountProvisioner
from agentpit.liquidity.replica import BookSnapshot
from agentpit.liquidity.reconciler import reconcile_market
from agentpit.onchain.admin import OnchainAdmin
from agentpit.onchain.contracts import Contracts
from agentpit.onchain.deployment import Deployment
from agentpit.onchain.web3_client import Web3Client
from agentpit.services.order_service import OrderService
from tests.onchain._helpers import create_market, fresh_client, register, unique_email


def _rig():
    s = Settings(liquidity_house_account_count=1, liquidity_funding_drips=1)
    d = Deployment.load(s.deployment_path)
    w = Web3Client(s, d)
    admin = OnchainAdmin(w, Contracts(w.web3, d))
    db = DbSession(s.database_url)
    client = fresh_client()
    m = create_market(client)
    cond = m["condition_id"]["value"]
    ref = MarketRef(
        market_id=m["market_id"], condition_id=cond,
        yes_token=m["erc1155_tokens"][0][0], no_token=m["erc1155_tokens"][1][0],
        pm_yes_token="PM-YES")
    user = HouseAccountProvisioner(db, admin, s).ensure_provisioned()[0]
    return s, db, admin, client, ref, user


def _snap(bids, asks):
    return BookSnapshot(asset_id="PM-YES", bids=tuple(bids), asks=tuple(asks))


def _levels(client, token):
    book = client.get(f"/book?token_id={token}").json()
    return ({float(b["price"]): float(b["size"]) for b in book["bids"]},
            {float(a["price"]): float(a["size"]) for a in book["asks"]})


def test_reconcile_mirrors_both_books_and_is_idempotent():
    s, db, admin, client, ref, user = _rig()
    order = OrderService(db, admin)
    snap = _snap(bids=[(400_000, 10_000_000), (300_000, 5_000_000)],
                 asks=[(600_000, 7_000_000)])

    stats = reconcile_market(db, order, admin, user, ref, snap, s)
    assert stats["placed"] == 6 and stats["cancelled"] == 0

    yes_bids, yes_asks = _levels(client, ref.yes_token)
    no_bids, no_asks = _levels(client, ref.no_token)
    assert yes_bids == {0.4: 10.0, 0.3: 5.0} and yes_asks == {0.6: 7.0}
    assert no_bids == {0.4: 7.0} and no_asks == {0.6: 10.0, 0.7: 5.0}

    stats2 = reconcile_market(db, order, admin, user, ref, snap, s)
    assert (stats2["placed"], stats2["cancelled"], stats2["fills"]) == (0, 0, 0)

    with db.read() as conn:
        n = conn.execute("SELECT COUNT(*) AS C FROM trades WHERE MARKET = %s",
                         (ref.condition_id,)).fetchone()["C"]
    assert n == 0          # mirroring NEVER trades with itself


def test_reconcile_level_change_minimal_ops():
    s, db, admin, client, ref, user = _rig()
    order = OrderService(db, admin)
    reconcile_market(db, order, admin, user, ref,
                     _snap(bids=[(400_000, 10_000_000)], asks=[(600_000, 7_000_000)]), s)
    stats = reconcile_market(db, order, admin, user, ref,
                             _snap(bids=[(410_000, 10_000_000)],            # bid moved
                                   asks=[(600_000, 7_000_000)]), s)
    # Only the moved bid (YES BUY + NO SELL complement) is touched.
    assert stats["cancelled"] == 2 and stats["placed"] == 2
    yes_bids, _ = _levels(client, ref.yes_token)
    assert yes_bids == {0.41: 10.0}


def test_reconcile_fills_bot_order_when_price_passes_through():
    s, db, admin, client, ref, user = _rig()
    order = OrderService(db, admin)
    reconcile_market(db, order, admin, user, ref,
                     _snap(bids=[(400_000, 10_000_000)], asks=[(600_000, 7_000_000)]), s)

    # A real user rests a bid INSIDE the spread...
    email = unique_email()
    register(client, email)          # /register onboards + funds the account
    with db.read() as conn:
        bot = TableRead.get_user_by_email(conn, email)
    assert bot is not None
    bot_order = OrderService(db, admin).place_order(bot, PlaceOrderRequest(
        token_id=ref.yes_token, side="BUY",
        price=Decimal("0.55"), size=Decimal("2"), order_type="GTC"))
    assert bot_order.success and not bot_order.tradeIDs

    # ...and the real market moves DOWN through it: new ask 0.50 < bot bid 0.55.
    stats = reconcile_market(db, order, admin, user, ref,
                             _snap(bids=[(400_000, 10_000_000)],
                                   asks=[(500_000, 7_000_000)]), s)
    assert stats["fills"] >= 1     # the bot got its (deserved) fill, settled on-chain

    with db.read() as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS C FROM trades WHERE MARKET = %s AND STATUS != 'FAILED'",
            (ref.condition_id,)).fetchone()["C"]
    assert n >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/onchain/test_mirror_reconcile.py -q`
Expected: FAIL — `ImportError: cannot import name 'reconcile_market'`

- [ ] **Step 3: Implement the applier in `reconciler.py`**

Append to `agentpit/liquidity/reconciler.py`:

```python
import logging
from decimal import Decimal

from agentpit.config import Settings
from agentpit.datastructures.place_order_request import PlaceOrderRequest
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.onchain.admin import OnchainAdmin
from agentpit.services.order_service import OrderService

log = logging.getLogger(__name__)


def _ensure_inventory(
    onchain: OnchainAdmin, user: User, ref, snap: BookSnapshot, cfg: Settings
) -> int:
    """Split-mint CTF inventory up to the snapshot's ask-side need × buffer.
    Returns the number of split txs performed (0 or 1 per call — splits are
    admin txs behind the global send_lock, budgeted by the caller)."""
    need = int(split_target_micro(snap) * cfg.mirror_inventory_buffer)
    if need <= 0:
        return 0
    held_yes = onchain.ctf_balance(user.eth_address, int(ref.yes_token))
    held_no = onchain.ctf_balance(user.eth_address, int(ref.no_token))
    add = need - min(held_yes, held_no)
    if add <= 0:
        return 0
    condition_bytes = bytes.fromhex(ref.condition_id[2:])
    onchain.user_split_position(user.eth_key, condition_bytes, add)
    return 1


def _crosses(p: Placement, foreign_bid: int | None, foreign_ask: int | None) -> bool:
    if p.side == "BUY":
        return foreign_ask is not None and p.price_micro >= foreign_ask
    return foreign_bid is not None and p.price_micro <= foreign_bid


def reconcile_market(
    db: DbSession,
    order: OrderService,
    onchain: OnchainAdmin,
    user: User,
    ref,                       # feed.MarketRef (duck-typed to avoid an import cycle)
    snap: BookSnapshot,
    cfg: Settings,
) -> dict:
    """Converge the local books (YES + NO complement) to the snapshot.
    Cancels strictly before placements (spec §5). Placements that would cross
    a NON-house order are intentional bot fills (spec §7) — they run last,
    capped at cfg.mirror_max_settlements_per_cycle real settlements."""
    tokens = [ref.yes_token, ref.no_token]
    with db.read() as conn:
        rows = TableRead.list_live_order_levels(conn, user.api_key, tokens)
        foreign = {t: TableRead.foreign_touch(conn, user.api_key, t) for t in tokens}
    current = [
        LiveLevel(r["ORDER_ID"], r["TOKEN_ID"], r["SIDE"],
                  int(r["PRICE"]), int(r["REMAINING_AMOUNT"]))
        for r in rows
    ]
    cancels, places = diff_levels(desired_levels(snap, ref.yes_token, ref.no_token),
                                  current)

    splits = 0
    try:
        splits = _ensure_inventory(onchain, user, ref, snap, cfg)
    except Exception:
        log.exception("inventory split failed for market %s", ref.market_id)
    inventory = {
        ref.yes_token: onchain.ctf_balance(user.eth_address, int(ref.yes_token)),
        ref.no_token: onchain.ctf_balance(user.eth_address, int(ref.no_token)),
    }
    places = cap_sells_to_inventory(places, inventory)

    if cancels:
        order.cancel_orders(user, cancels)

    # Non-crossing placements first; crossing ones (real settlements) last + capped.
    calm = [p for p in places if not _crosses(p, *foreign[p.token_id])]
    hot = [p for p in places if _crosses(p, *foreign[p.token_id])]
    placed = fills = 0
    for p in calm + hot:
        if p in hot and fills >= cfg.mirror_max_settlements_per_cycle:
            continue           # defer to a later cycle — keeps the loop unblocked
        resp = order.place_order(user, PlaceOrderRequest(
            token_id=p.token_id, side=p.side,
            price=Decimal(p.price_micro) / MICRO,
            size=Decimal(p.size_micro) / MICRO,
            order_type="GTC",
        ))
        if not resp.success:
            log.warning("mirror placement settlement failed (market=%s %s@%s): %s",
                        ref.market_id, p.side, p.price_micro, resp.errorMsg)
            continue
        placed += 1
        if resp.tradeIDs:
            fills += 1
            if p in calm:
                log.error("mirror placement unexpectedly filled — foreign-touch "
                          "guard missed (market=%s %s@%s)",
                          ref.market_id, p.side, p.price_micro)
    return {"placed": placed, "cancelled": len(cancels), "fills": fills,
            "splits": splits}
```

Note: `Placement` is a frozen dataclass, so `p in hot` is value-equality — correct because (token, side, price) keys are unique within one diff.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/onchain/test_mirror_reconcile.py -q` (needs Anvil + Postgres)
Expected: 3 passed. The third test performs one real on-chain settlement (≤60s worst case, usually seconds on local Anvil).

These tests need the `mirror_*` Settings fields which are added in Task 7 — if running tasks strictly in order, add the two fields used here (`mirror_inventory_buffer`, `mirror_max_settlements_per_cycle`, from the Task 7 block) to `agentpit/config.py` now; Task 7 adds the rest.

- [ ] **Step 5: Commit**

```bash
git add agentpit/liquidity/reconciler.py tests/onchain/test_mirror_reconcile.py agentpit/config.py
git commit -m "feat(liquidity): mirror reconciler applier — cancels-first, inventory splits, capped bot fills"
```

---

### Task 7: Engine glue, config swap, app wiring, ladder deletion

**Files:**
- Create: `agentpit/liquidity/mirror.py`
- Modify: `agentpit/config.py`, `agentpit/api/app.py`, `agentpit/liquidity/house_accounts.py`
- Delete: `agentpit/liquidity/engine.py`, `agentpit/liquidity/ladder.py`, `agentpit/liquidity/price_oracle.py`, `tests/liquidity/test_ladder.py`, `tests/liquidity/test_price_oracle.py`, `tests/onchain/test_liquidity_tick.py`, `tests/onchain/test_liquidity_arb.py`
- Rewrite: `tests/onchain/test_liquidity_lifespan.py`

- [ ] **Step 1: Update `agentpit/config.py`**

Replace the whole `# Liquidity Engine` block (everything from `liquidity_engine_enabled` to `liquidity_max_prints_per_tick`) with:

```python
    # Liquidity Engine (Phase 5c: Polymarket book mirror)
    liquidity_engine_enabled: bool = Field(
        default=False, validation_alias="LIQUIDITY_ENGINE"
    )
    liquidity_interval_seconds: float = Field(
        default=2.0, validation_alias="AGENTPIT_LIQUIDITY_INTERVAL_SECONDS"
    )
    # ONE mirror account owns every mirror order (spec §6). >1 is unused but
    # kept for provisioning flexibility.
    liquidity_house_account_count: int = Field(
        default=1, validation_alias="AGENTPIT_LIQUIDITY_HOUSE_ACCOUNTS"
    )
    # 1 faucet drip = $1B apUSD. 4 drips cover splits + bids across all markets.
    liquidity_funding_drips: int = Field(
        default=4, validation_alias="AGENTPIT_LIQUIDITY_FUNDING_DRIPS"
    )
    mirror_assets_per_connection: int = Field(
        default=200, validation_alias="AGENTPIT_MIRROR_ASSETS_PER_CONNECTION"
    )
    mirror_reconcile_min_interval_seconds: float = Field(
        default=0.5, validation_alias="AGENTPIT_MIRROR_RECONCILE_MIN_INTERVAL_SECONDS"
    )
    mirror_watchdog_seconds: float = Field(
        default=120.0, validation_alias="AGENTPIT_MIRROR_WATCHDOG_SECONDS"
    )
    mirror_inventory_buffer: float = Field(
        default=1.2, validation_alias="AGENTPIT_MIRROR_INVENTORY_BUFFER"
    )
    mirror_max_splits_per_cycle: int = Field(
        default=2, validation_alias="AGENTPIT_MIRROR_MAX_SPLITS_PER_CYCLE"
    )
    mirror_max_settlements_per_cycle: int = Field(
        default=1, validation_alias="AGENTPIT_MIRROR_MAX_SETTLEMENTS_PER_CYCLE"
    )
    mirror_tape_enabled: bool = Field(
        default=True, validation_alias="AGENTPIT_MIRROR_TAPE_ENABLED"
    )
    mirror_target_refresh_seconds: float = Field(
        default=60.0, validation_alias="AGENTPIT_MIRROR_TARGET_REFRESH_SECONDS"
    )
```

Then: `grep -rn "liquidity_makers_per_market\|liquidity_ladder\|liquidity_wall_fraction\|liquidity_requote\|liquidity_taker_pool\|liquidity_print\|liquidity_max_prints\|liquidity_split_per_market" agentpit/ tests/` — every hit must be in a file this task deletes or rewrites. Fix any stragglers.

- [ ] **Step 2: Add `email_for` to `house_accounts.py`**

```python
def email_for(i: int) -> str:
    """Deterministic house-account email; index 0 is the mirror account."""
    return _EMAIL.format(i=i)
```

(Module-level function, placed under the `_PASSWORD` constant.)

- [ ] **Step 3: Create `agentpit/liquidity/mirror.py`**

```python
# agentpit/liquidity/mirror.py
"""MirrorEngine — glue between the WSS feed, the reconciler, and the tape.

Two lifespan tasks (siblings of polymarket_sync / snapshot):
  run_feed       — REST-seeds replicas, then holds sharded WSS connections.
  run_reconciler — drains dirty markets (coalesced per-market) and the trade
                   queue; refreshes the target market set; cancels orders on
                   the ACTIVE→gone edge (resolution/cancellation).
Blocking work (DB/chain/REST) runs via asyncio.to_thread.
"""
import asyncio
import logging

from agentpit.config import Settings
from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.liquidity import feed, tape
from agentpit.liquidity.feed import MarketRef, MirrorState
from agentpit.liquidity.reconciler import reconcile_market
from agentpit.liquidity.replica import to_micro
from agentpit.onchain.admin import OnchainAdmin
from agentpit.services.order_service import OrderService

log = logging.getLogger(__name__)


def _load_refs(db: DbSession) -> list[MarketRef]:
    with db.read() as conn:
        markets = TableRead.list_active_synced_markets(conn)
    refs = []
    for m in markets:
        if not m.polymarket_yes_token_id or len(m.erc1155_tokens) < 2:
            continue
        refs.append(MarketRef(
            market_id=m.market_id,
            condition_id=m.condition_id.value,
            yes_token=m.erc1155_tokens[0][0],
            no_token=m.erc1155_tokens[1][0],
            pm_yes_token=m.polymarket_yes_token_id,
        ))
    return refs


class MirrorEngine:
    def __init__(self, db: DbSession, onchain: OnchainAdmin,
                 settings: Settings, user: User):
        self._db = db
        self._onchain = onchain
        self._cfg = settings
        self._user = user
        self._order = OrderService(db, onchain)
        self.state = MirrorState([])
        self._resubscribe = asyncio.Event()

    # ---- feed side -------------------------------------------------------

    async def run_feed(self) -> None:
        while True:
            assets = list(self.state.replicas)
            self._resubscribe.clear()
            if not assets:
                await self._wait_resubscribe(self._cfg.mirror_target_refresh_seconds)
                continue
            books = await asyncio.to_thread(feed.fetch_books_rest, assets)
            for b in books:
                self.state.handle_event({**b, "event_type": "book"})
            conns = [
                asyncio.create_task(feed.run_connection(
                    self.state, shard_assets,
                    watchdog_seconds=self._cfg.mirror_watchdog_seconds))
                for shard_assets in feed.shard(
                    assets, self._cfg.mirror_assets_per_connection)
            ]
            try:
                await self._resubscribe.wait()   # target set changed — rebuild
            finally:
                for t in conns:
                    t.cancel()
                for t in conns:
                    try:
                        await t
                    except asyncio.CancelledError:
                        pass

    async def _wait_resubscribe(self, timeout: float) -> None:
        try:
            await asyncio.wait_for(self._resubscribe.wait(), timeout)
        except TimeoutError:
            pass

    # ---- reconcile side --------------------------------------------------

    async def run_reconciler(self) -> None:
        last_run: dict[str, float] = {}
        last_refresh = 0.0
        while True:
            try:
                now = asyncio.get_running_loop().time()
                if now - last_refresh >= self._cfg.mirror_target_refresh_seconds:
                    last_refresh = now
                    await self._refresh_targets()
                await self._drain_tape()
                ready = [
                    a for a in list(self.state.dirty)
                    if now - last_run.get(a, 0.0)
                    >= self._cfg.mirror_reconcile_min_interval_seconds
                ]
                for asset in ready:
                    self.state.dirty.discard(asset)
                    ref = self.state.by_asset.get(asset)
                    rep = self.state.replicas.get(asset)
                    snap = rep.snapshot() if rep is not None else None
                    if ref is None or snap is None:
                        continue
                    last_run[asset] = now
                    stats = await asyncio.to_thread(
                        reconcile_market, self._db, self._order, self._onchain,
                        self._user, ref, snap, self._cfg)
                    if stats["placed"] or stats["cancelled"]:
                        log.info("mirror market %s: %s", ref.market_id, stats)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("mirror reconcile cycle failed")
            await asyncio.sleep(
                self._cfg.mirror_reconcile_min_interval_seconds
                if self.state.dirty or self.state.trades
                else self._cfg.liquidity_interval_seconds)

    async def _refresh_targets(self) -> None:
        refs = await asyncio.to_thread(_load_refs, self._db)
        added, removed = self.state.set_targets(refs)
        for ref in removed:    # resolution/cancel edge: pull our orders
            log.info("market %s left the active set — cancelling mirror orders",
                     ref.market_id)
            await asyncio.to_thread(
                self._order.cancel_market_orders, self._user,
                ref.condition_id, None)
        if added or removed:
            self._resubscribe.set()

    async def _drain_tape(self) -> None:
        if not self._cfg.mirror_tape_enabled:
            self.state.trades.clear()
            return
        while self.state.trades:
            ev = self.state.trades.popleft()
            ref = self.state.by_asset.get(ev.get("asset_id"))
            price = to_micro(ev.get("price"))
            size = to_micro(ev.get("size"))
            side = ev.get("side")
            try:
                ts_s = int(ev.get("timestamp", "0")) // 1000   # WSS gives ms
            except (TypeError, ValueError):
                ts_s = 0
            if ref is None or price is None or size is None or size <= 0 \
                    or side not in ("BUY", "SELL") or ts_s <= 0:
                continue
            def _write(ref=ref, price=price, size=size, side=side, ts_s=ts_s):
                with self._db.write() as conn:
                    tape.insert_mirrored_trade(
                        conn, condition_id=ref.condition_id,
                        local_token_id=ref.yes_token, price_micro=price,
                        size_micro=size, side=side, match_time_s=ts_s)
            await asyncio.to_thread(_write)
```

- [ ] **Step 4: Rewire `agentpit/api/app.py`**

1. Replace the import `from agentpit.liquidity.engine import LiquidityEngine` with `from agentpit.liquidity.mirror import MirrorEngine` and add `from agentpit.liquidity.house_accounts import email_for` to the existing house_accounts import line.
2. Delete `_run_liquidity_tick` and `_liquidity_engine_loop` (both functions).
3. Replace the `engine_task` block inside `lifespan` with:

```python
        mirror_tasks: list[asyncio.Task] = []
        if settings.liquidity_engine_enabled:
            log.info("Liquidity mirror enabled (reconcile interval=%ss)",
                     settings.mirror_reconcile_min_interval_seconds)
            provisioner = HouseAccountProvisioner(db_session, onchain_admin, settings)
            house_users = await asyncio.to_thread(provisioner.ensure_provisioned)
            mirror_user = next(
                (u for u in house_users if u.email == email_for(0)), house_users[0])
            mirror = MirrorEngine(db_session, onchain_admin, settings, mirror_user)
            mirror_tasks = [
                asyncio.create_task(mirror.run_feed()),
                asyncio.create_task(mirror.run_reconciler()),
            ]
        else:
            log.info("Liquidity mirror disabled (set LIQUIDITY_ENGINE=true to enable)")
```

4. In the `finally` block change the cancellation tuple to `for task in (sync_task, snapshot_task, *mirror_tasks):`.

- [ ] **Step 5: Delete the ladder stack and its tests**

```bash
git rm -q agentpit/liquidity/engine.py agentpit/liquidity/ladder.py \
  agentpit/liquidity/price_oracle.py tests/liquidity/test_ladder.py \
  tests/liquidity/test_price_oracle.py tests/onchain/test_liquidity_tick.py \
  tests/onchain/test_liquidity_arb.py
grep -rn "liquidity.engine\|liquidity.ladder\|liquidity.price_oracle\|build_ladder\|fetch_bid_ask_micro\|fetch_mid_micro" agentpit/ tests/
```
Expected grep output: nothing (fix any stragglers before proceeding).

- [ ] **Step 6: Rewrite `tests/onchain/test_liquidity_lifespan.py`**

```python
# tests/onchain/test_liquidity_lifespan.py
import asyncio
import uuid

from fastapi.testclient import TestClient

from agentpit.api.app import create_app
from agentpit.config import Settings
from agentpit.liquidity import feed


def test_mirror_disabled_by_default():
    app = create_app(Settings())
    with TestClient(app):
        pass  # lifespan runs; no mirror tasks, no house provisioning, no crash


def test_mirror_enabled_spawns_and_cancels_cleanly(monkeypatch):
    # Stub the feed: a connection task that idles forever (no network).
    async def fake_connection(state, assets, **kw):
        await asyncio.Event().wait()

    monkeypatch.setattr(feed, "run_connection", fake_connection)
    monkeypatch.setattr(feed, "fetch_books_rest", lambda ids, **kw: [])

    s = Settings(liquidity_engine_enabled=True, liquidity_house_account_count=1,
                 liquidity_funding_drips=1, mirror_target_refresh_seconds=0.1)
    app = create_app(s)
    with TestClient(app) as client:
        r = client.get("/markets")        # API serves while the mirror idles
        assert r.status_code == 200
    # Clean shutdown (no hang, no unraised CancelledError) is the assertion.
```

- [ ] **Step 7: Run the full suite**

Run: `pytest -q`
Expected: all pass. `tests/onchain/test_house_accounts.py` passes unchanged (it sets explicit counts). The conftest `LIQUIDITY_ENGINE=false` isolation (commit b0835b9) keeps default runs cheap.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(liquidity): MirrorEngine wiring — replace synthetic ladder with Polymarket book mirror"
```

---

### Task 8: Live smoke script (answers the NO-side tape question)

**Files:**
- Create: `scripts/mirror_smoke.py`

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
# scripts/mirror_smoke.py
"""60-second live capture from the Polymarket WSS market channel.

Usage:
    python scripts/mirror_smoke.py <YES_TOKEN_ID> [<YES_TOKEN_ID> ...]

Prints per-event-type counts, replica convergence stats, and — the open spec
question (§9/§13.3) — whether last_trade_price events for the SIBLING (NO)
asset arrive on a YES-only subscription.
"""
import asyncio
import json
import sys
from collections import Counter

import websockets

from agentpit.liquidity.feed import WSS_URL, parse_events
from agentpit.liquidity.replica import BookReplica


async def main(asset_ids: list[str], duration: float = 60.0) -> None:
    counts: Counter = Counter()
    trade_assets: Counter = Counter()
    replicas = {a: BookReplica(a) for a in asset_ids}
    async with websockets.connect(WSS_URL) as ws:
        await ws.send(json.dumps({"assets_ids": asset_ids, "type": "market"}))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + duration
        while loop.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
            except TimeoutError:
                await ws.send("PING")
                continue
            for ev in parse_events(raw):
                et = ev.get("event_type", "?")
                counts[et] += 1
                if et == "book" and ev.get("asset_id") in replicas:
                    replicas[ev["asset_id"]].apply_book(ev)
                elif et == "price_change":
                    for e in ev.get("price_changes") or []:
                        rep = replicas.get(e.get("asset_id"))
                        if rep is not None:
                            rep.apply_price_change_entry(e)
                elif et == "last_trade_price":
                    a = ev.get("asset_id", "?")
                    trade_assets["subscribed" if a in replicas else "sibling"] += 1

    print("event counts:", dict(counts))
    print("last_trade_price by origin:", dict(trade_assets))
    print("=> sibling>0 means NO-side trades DO arrive on a YES-only subscription")
    for a, r in replicas.items():
        snap = r.snapshot()
        print(f"{a[:16]}…: seeded={r.seeded} levels="
              f"{len(snap.bids) if snap else 0}+{len(snap.asks) if snap else 0}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1:]))
```

- [ ] **Step 2: Run it against two liquid markets**

Get two YES token ids: `curl -s "https://gamma-api.polymarket.com/markets?limit=2&active=true&closed=false&order=volumeNum&ascending=false" | python3 -c "import json,sys; [print(json.loads(m['clobTokenIds'])[0]) for m in json.load(sys.stdin)]"`

Run: `python scripts/mirror_smoke.py <id1> <id2>`
Expected: non-zero `book` and `price_change` counts; replicas seeded with dozens of levels. Record the `last_trade_price by origin` line in the spec (§13.3): if `sibling` > 0, NO-side trades arrive and the V1 "YES asset_id only" tape policy (drop sibling events) is confirmed necessary; if only `subscribed`, the policy is a no-op. Either way no code change is required — `MirrorState.handle_event` already drops unknown asset_ids.

- [ ] **Step 3: Update spec §13.3 with the observed answer, then commit**

```bash
git add scripts/mirror_smoke.py docs/superpowers/specs/2026-06-10-book-mirror-design.md
git commit -m "feat(liquidity): live WSS smoke script; pin down NO-side tape behavior"
```

---

### Task 9: Final verification

- [ ] **Step 1: Full suite**

Run: `pytest -q`
Expected: all pass, zero warnings about un-awaited tasks.

- [ ] **Step 2: Live end-to-end sanity (manual, with real services)**

With Postgres + Anvil + deployed exchange running and `.env` containing `SYNC=true`, `LIQUIDITY_ENGINE=true`:

```bash
uvicorn agentpit.api.app:create_app --factory --port 8211 &
sleep 90   # sync + seed + first reconcile cycles
curl -s "localhost:8211/markets" | python3 -c "
import json,sys
ms=[m for m in json.load(sys.stdin) if m.get('polymarket_condition_id')]
print(ms[0]['erc1155_tokens'][0][0])"
# then, with that token id:
curl -s "localhost:8211/book?token_id=<TOKEN>" | python3 -m json.tool | head -40
```

Expected: the book shows the real Polymarket level structure (irregular sizes, real depth — compare against polymarket.com for the same market); `last_trade_price` is non-zero once a real trade prints; re-fetching after a minute shows the book moving with the real market.

- [ ] **Step 3: Commit any leftovers, update memory/docs**

```bash
git status --short   # expect clean
```

---

## Self-review notes (spec → tasks)

- Spec §5 invariant → Task 2 (`test_desired_levels_never_cross_within_either_token`) + Task 6 (cancels-before-places ordering, zero-self-trades assertion).
- Spec §6 components → Tasks 1 (replica), 2+6 (reconciler), 4 (tape), 5 (feed), 7 (mirror glue, config, deletion table rows incl. Task 0).
- Spec §7 bot interaction → Task 6 (`test_reconcile_fills_bot_order_when_price_passes_through`, hot/calm split, settlement cap).
- Spec §8 inventory → Task 2 (`split_target_micro`, `cap_sells_to_inventory`) + Task 6 (`_ensure_inventory`).
- Spec §9 tape → Task 4 + Task 7 `_drain_tape` (ms→s, YES-only policy) + Task 8 (live answer).
- Spec §10 config → Task 7 Step 1 (field-for-field).
- Spec §11 degradations → watchdog/reconnect (Task 5), crossed/stale snapshot = None (Task 1), frozen-book-on-outage is the natural behavior of "no events → no dirty → no ops".
- Spec §12 testing → Tasks 1/2/5 pure, 3/4/6 integration, 8 live smoke.
- Deviations from spec: (1) `mirror_target_refresh_seconds` is a config addition (target-set refresh cadence) not present in §10. (2) On target-set changes the feed REBUILDS its connections instead of sending live `operation: subscribe/unsubscribe` messages (spec §4 mentions dynamic subscribe) — equivalent outcome (re-subscribing delivers fresh snapshots, the documented resync point) with less connection-state bookkeeping; switch to live operations later only if reconnect churn ever matters.
