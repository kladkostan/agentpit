# Deep order book: hot band + cold sweep — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the mirror replicate a deep order book (up to 50 levels per side) while keeping the per-update hot path exactly as cheap as it is today, by reconciling only the top 8 levels on every book update and sweeping the deep levels once every 30 minutes per market.

**Architecture:** The tiers are split by **price distance from the touch**, not by list index, so levels migrate between tiers on their own as the touch moves. `diff_levels` gains a `protect` predicate so a hot pass leaves cold orders alone instead of cancelling them (the single biggest regression risk). `run_reconciler` keeps a per-asset cold-sweep clock, seeded with a deterministic per-asset offset so the first sweeps fan out across the interval instead of stampeding on boot.

**Tech Stack:** Python 3.13, pytest, psycopg (Postgres). Backend-only — no UI, no API, no on-chain change.

## Global Constraints

- Branch `mvp`, repo `/Users/yavorsky/dev/agentpit`. Backend-only: nothing under `ui/` changes.
- **NEVER source `.env` into pytest.** `tests/conftest.py` sets the test database and `SYNC=false` via `setdefault`; sourcing `.env` overrides them and the run hangs doing a live Polymarket sync. The correct command is plain: `.venv/bin/python -m pytest <paths> -q`.
- Prices and sizes are **scaled integers in micros**; `MICRO = 1_000_000` lives in `agentpit/liquidity/replica.py:10`. A price of 0.40 is `400_000`.
- The NO book is mirrored as the `MICRO - p` complement of the YES book — every price rule must be stated per `(token_id, side)`, never per level index.
- The change must be a **no-op until deliberately enabled**: with `mirror_hot_depth == mirror_book_depth` (both 8, which is what production sets today) the cold region is empty and behaviour is byte-identical to today.
- Do NOT touch crossing classification (`_crosses`, `_merge_touch`), settlement budgets, or `_ensure_inventory` — inventory is already minted from the full snapshot.
- Stage only the files named in each task. NEVER `git add -A` or `git add .`.
- No `Co-Authored-By` or any AI-attribution trailer in commit messages.

## File structure

| File | Responsibility | Change |
|---|---|---|
| `agentpit/config.py` | settings | add `mirror_hot_depth`, `mirror_cold_interval_seconds`; re-document `mirror_book_depth` as the total cap |
| `agentpit/liquidity/reconciler.py` | pure diff + DB/chain applier | add `HotCuts`, `hot_cuts`, `is_hot_level`; add `protect` to `diff_levels`; tier selection in `reconcile_market` |
| `agentpit/liquidity/mirror.py` | scheduling loop | per-asset cold clock + startup fan-out |
| `tests/test_config_liquidity.py` | config defaults | extend |
| `tests/liquidity/test_mirror_diff.py` | pure-function tests | extend |
| `tests/liquidity/test_mirror_cold.py` | new: tier scheduling + fan-out | create |

---

### Task 1: Hot-band classification (pure functions)

**Files:**
- Modify: `agentpit/liquidity/reconciler.py` (add after `desired_levels`, before `diff_levels`)
- Test: `tests/liquidity/test_mirror_diff.py` (append)

**Interfaces:**
- Consumes: `MICRO` and `BookSnapshot` from `agentpit.liquidity.replica` (already imported at `reconciler.py:17`).
- Produces:
  - `@dataclass(frozen=True) class HotCuts: bid_cut: int | None; ask_cut: int | None`
  - `hot_cuts(snap: BookSnapshot, hot_depth: int) -> HotCuts`
  - `is_hot_level(token_id: str, side: str, price_micro: int, cuts: HotCuts, yes_token: str) -> bool`

- [ ] **Step 1: Write the failing tests**

Append to `tests/liquidity/test_mirror_diff.py` (the file already defines `YES`, `NO` and `_snap`, and already imports from `agentpit.liquidity.reconciler` — extend that import with `HotCuts`, `hot_cuts`, `is_hot_level`):

```python
def test_hot_cuts_are_the_prices_of_the_nth_level():
    snap = _snap(
        bids=[(400_000, 1), (390_000, 1), (380_000, 1)],
        asks=[(410_000, 1), (420_000, 1), (430_000, 1)],
    )
    cuts = hot_cuts(snap, 2)
    assert cuts.bid_cut == 390_000   # 2nd bid, best-first
    assert cuts.ask_cut == 420_000   # 2nd ask


def test_hot_cuts_none_when_side_shallower_than_hot_depth():
    # Fewer levels than the hot depth means the whole side is hot: no cut.
    snap = _snap(bids=[(400_000, 1)], asks=[(410_000, 1), (420_000, 1)])
    cuts = hot_cuts(snap, 5)
    assert cuts.bid_cut is None
    assert cuts.ask_cut is None


def test_hot_cuts_unbounded_hot_depth_has_no_cuts():
    snap = _snap(bids=[(400_000, 1)], asks=[(410_000, 1)])
    cuts = hot_cuts(snap, 0)
    assert cuts == HotCuts(None, None)


def test_is_hot_level_classifies_both_tokens_and_sides():
    # bid_cut 390k, ask_cut 420k. YES verbatim, NO at the MICRO-p complement.
    cuts = HotCuts(bid_cut=390_000, ask_cut=420_000)
    # --- YES side
    assert is_hot_level(YES, "BUY", 400_000, cuts, YES) is True    # >= bid_cut
    assert is_hot_level(YES, "BUY", 380_000, cuts, YES) is False   # deeper than cut
    assert is_hot_level(YES, "SELL", 410_000, cuts, YES) is True   # <= ask_cut
    assert is_hot_level(YES, "SELL", 430_000, cuts, YES) is False
    # --- NO side: a YES bid @400k is a NO SELL @600k; the cut maps to 610k
    assert is_hot_level(NO, "SELL", MICRO - 400_000, cuts, YES) is True
    assert is_hot_level(NO, "SELL", MICRO - 380_000, cuts, YES) is False
    # a YES ask @410k is a NO BUY @590k; the cut maps to 580k
    assert is_hot_level(NO, "BUY", MICRO - 410_000, cuts, YES) is True
    assert is_hot_level(NO, "BUY", MICRO - 430_000, cuts, YES) is False


def test_is_hot_level_all_hot_when_cut_is_none():
    cuts = HotCuts(bid_cut=None, ask_cut=None)
    assert is_hot_level(YES, "BUY", 1, cuts, YES) is True
    assert is_hot_level(NO, "SELL", MICRO - 1, cuts, YES) is True


def test_is_hot_level_follows_the_touch_when_price_moves():
    # A level that is cold under one snapshot becomes hot after the book moves.
    deep = _snap(bids=[(400_000, 1), (390_000, 1), (380_000, 1)], asks=[(410_000, 1)])
    assert is_hot_level(YES, "BUY", 380_000, hot_cuts(deep, 2), YES) is False
    moved = _snap(bids=[(380_000, 1), (370_000, 1)], asks=[(410_000, 1)])
    assert is_hot_level(YES, "BUY", 380_000, hot_cuts(moved, 2), YES) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/liquidity/test_mirror_diff.py -q`
Expected: FAIL — `ImportError: cannot import name 'HotCuts' from 'agentpit.liquidity.reconciler'`.

- [ ] **Step 3: Implement the two pure functions**

In `agentpit/liquidity/reconciler.py`, after `desired_levels` (which ends at line 58) and before `diff_levels`:

```python
@dataclass(frozen=True)
class HotCuts:
    """Price boundary of the hot band, per side of the YES book.

    `bid_cut` is the price of the hot-depth-th bid, `ask_cut` that of the
    hot-depth-th ask. `None` means the side has fewer levels than the hot
    depth (or the hot depth is unbounded), so the whole side is hot.
    """
    bid_cut: int | None
    ask_cut: int | None


def hot_cuts(snap: BookSnapshot, hot_depth: int) -> HotCuts:
    """Derive the hot band from a snapshot. `hot_depth <= 0` = everything hot."""
    if hot_depth <= 0:
        return HotCuts(None, None)
    bid_cut = snap.bids[hot_depth - 1][0] if len(snap.bids) >= hot_depth else None
    ask_cut = snap.asks[hot_depth - 1][0] if len(snap.asks) >= hot_depth else None
    return HotCuts(bid_cut, ask_cut)


def is_hot_level(
    token_id: str, side: str, price_micro: int, cuts: HotCuts, yes_token: str
) -> bool:
    """Is this (token, side, price) inside the hot band?

    The YES book is mirrored verbatim and the NO book as the MICRO-p
    complement, so each of the four placement shapes tests a different
    inequality. Derived from the CURRENT snapshot, so a level migrates
    between tiers on its own as the touch moves.
    """
    is_yes = token_id == yes_token
    if (is_yes and side == "BUY") or (not is_yes and side == "SELL"):
        # Bid side: YES BUY @p, or its complement NO SELL @MICRO-p.
        if cuts.bid_cut is None:
            return True
        p = price_micro if is_yes else MICRO - price_micro
        return p >= cuts.bid_cut
    # Ask side: YES SELL @p, or its complement NO BUY @MICRO-p.
    if cuts.ask_cut is None:
        return True
    p = price_micro if is_yes else MICRO - price_micro
    return p <= cuts.ask_cut
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/liquidity/test_mirror_diff.py -q`
Expected: PASS — the whole file, including the pre-existing tests.

- [ ] **Step 5: Commit**

```bash
git add agentpit/liquidity/reconciler.py tests/liquidity/test_mirror_diff.py
git commit -m "feat(liquidity): classify book levels into a hot band by price

The hot/cold split is derived from the snapshot's touch rather than a list
index, so levels migrate between tiers as the book moves. The NO side is
mirrored as the MICRO-p complement, so each placement shape tests its own
inequality."
```

---

### Task 2: `diff_levels` must not cancel protected levels

**Files:**
- Modify: `agentpit/liquidity/reconciler.py:61-81` (`diff_levels`)
- Test: `tests/liquidity/test_mirror_diff.py` (append)

**Interfaces:**
- Consumes: `LiveLevel`, `Placement` (already defined in the same module).
- Produces: `diff_levels(desired: list[Placement], current: list[LiveLevel], protect: "Callable[[LiveLevel], bool] | None" = None) -> tuple[list[str], list[Placement]]` — live orders where `protect(o)` is true are neither kept nor cancelled.

- [ ] **Step 1: Write the failing tests**

Append to `tests/liquidity/test_mirror_diff.py`:

```python
def test_diff_leaves_protected_levels_alone():
    # Desired covers only the top level; the deep one is protected and must
    # survive untouched — this is the regression that would wipe the cold book.
    desired = [Placement(YES, "BUY", 400_000, 10)]
    current = [
        LiveLevel("o-hot", YES, "BUY", 400_000, 10),
        LiveLevel("o-cold", YES, "BUY", 300_000, 10),
    ]
    cancels, places = diff_levels(
        desired, current, protect=lambda o: o.price_micro == 300_000
    )
    assert cancels == []          # neither the kept hot level nor the cold one
    assert places == []           # hot level already matches


def test_diff_without_protect_still_cancels_everything_unwanted():
    desired = [Placement(YES, "BUY", 400_000, 10)]
    current = [
        LiveLevel("o-hot", YES, "BUY", 400_000, 10),
        LiveLevel("o-cold", YES, "BUY", 300_000, 10),
    ]
    cancels, places = diff_levels(desired, current)
    assert cancels == ["o-cold"]  # unchanged legacy behaviour
    assert places == []


def test_diff_protected_level_is_not_treated_as_satisfying_a_desired_level():
    # A protected order at a desired price must not suppress the placement:
    # protection means "out of scope", not "already handled".
    desired = [Placement(YES, "BUY", 400_000, 10)]
    current = [LiveLevel("o-x", YES, "BUY", 400_000, 10)]
    cancels, places = diff_levels(desired, current, protect=lambda o: True)
    assert cancels == []
    assert places == [Placement(YES, "BUY", 400_000, 10)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/liquidity/test_mirror_diff.py -q`
Expected: FAIL — `diff_levels() got an unexpected keyword argument 'protect'`.

- [ ] **Step 3: Implement**

Replace `diff_levels` in `agentpit/liquidity/reconciler.py` with:

```python
def diff_levels(
    desired: list[Placement],
    current: list[LiveLevel],
    protect: "Callable[[LiveLevel], bool] | None" = None,
) -> tuple[list[str], list[Placement]]:
    """(order_ids to cancel, placements to make). Orders are immutable, so a
    size change at a level is cancel + re-place. One live order per
    (token, side, price) is kept; duplicates are cancelled.

    `protect` marks live orders that are OUT OF SCOPE for this pass: they are
    neither cancelled nor counted as satisfying a desired level. A hot pass
    protects the cold band so it does not wipe the deep book on every update.
    """
    want = {(d.token_id, d.side, d.price_micro): d.size_micro for d in desired}
    keep: set[tuple[str, str, int]] = set()
    cancels: list[str] = []
    for o in current:
        if protect is not None and protect(o):
            continue
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
```

Add `Callable` to the module's imports — at the top of `agentpit/liquidity/reconciler.py`, alongside the existing `from dataclasses import dataclass`:

```python
from collections.abc import Callable
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/liquidity/test_mirror_diff.py -q`
Expected: PASS, including every pre-existing test in the file (they call `diff_levels` without `protect`, which must behave exactly as before).

- [ ] **Step 5: Commit**

```bash
git add agentpit/liquidity/reconciler.py tests/liquidity/test_mirror_diff.py
git commit -m "feat(liquidity): let diff_levels protect out-of-scope levels

Without this a hot pass would cancel every level it does not currently
desire, wiping the deep book on the next book update."
```

---

### Task 3: Config — hot depth and cold interval

**Files:**
- Modify: `agentpit/config.py:190-200` (after `mirror_target_refresh_seconds` / around `mirror_book_depth`)
- Test: `tests/test_config_liquidity.py`

**Interfaces:**
- Produces: `Settings.mirror_hot_depth: int` (default 8, env `AGENTPIT_MIRROR_HOT_DEPTH`) and `Settings.mirror_cold_interval_seconds: float` (default 1800.0, env `AGENTPIT_MIRROR_COLD_INTERVAL_SECONDS`). `Settings.mirror_book_depth` keeps its name and its default of 8 but now means the TOTAL cap converged by the cold sweep.

- [ ] **Step 1: Write the failing tests**

In `tests/test_config_liquidity.py`, add to the existing `test_liquidity_defaults` body:

```python
    assert s.mirror_hot_depth == 8
    assert abs(s.mirror_cold_interval_seconds - 1800.0) < 1e-9
```

and append a new test:

```python
def test_mirror_depth_env_override(monkeypatch):
    monkeypatch.setenv("AGENTPIT_MIRROR_HOT_DEPTH", "12")
    monkeypatch.setenv("AGENTPIT_MIRROR_BOOK_DEPTH", "50")
    monkeypatch.setenv("AGENTPIT_MIRROR_COLD_INTERVAL_SECONDS", "600")
    s = Settings()
    assert s.mirror_hot_depth == 12
    assert s.mirror_book_depth == 50
    assert abs(s.mirror_cold_interval_seconds - 600.0) < 1e-9
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_config_liquidity.py -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'mirror_hot_depth'`.

- [ ] **Step 3: Implement**

In `agentpit/config.py`, replace the `mirror_book_depth` block (currently at lines 195-200, comment included) with:

```python
    # Total depth cap per side. The cold sweep converges the local book to this
    # many levels; 0 = unbounded (full 1:1). Each level is ~4 DB order ops, so
    # this bounds the size of the orders table, not the hot-path cost.
    mirror_book_depth: int = Field(
        default=8, validation_alias="AGENTPIT_MIRROR_BOOK_DEPTH"
    )
    # Levels per side reconciled on EVERY book update. These carry the price the
    # user sees and the spread a bot trades against, so they must stay live.
    # Everything between this and mirror_book_depth is the cold band, refreshed
    # only by the sweep below. hot == book depth means no cold band at all,
    # which is byte-identical to the pre-two-tier behaviour.
    mirror_hot_depth: int = Field(
        default=8, validation_alias="AGENTPIT_MIRROR_HOT_DEPTH"
    )
    # How often each market's deep levels are reconciled. Deep levels move
    # rarely and nobody trades against them, so this is deliberately slow — it
    # is what keeps a 50-level book from multiplying the hot path.
    mirror_cold_interval_seconds: float = Field(
        default=1800.0, validation_alias="AGENTPIT_MIRROR_COLD_INTERVAL_SECONDS"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_config_liquidity.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agentpit/config.py tests/test_config_liquidity.py
git commit -m "feat(config): mirror hot depth and cold sweep interval

mirror_book_depth becomes the total cap converged by the cold sweep; the
defaults (hot 8 == cap 8) leave an empty cold band, so behaviour is
unchanged until the cap is raised."
```

---

### Task 4: Tier selection inside `reconcile_market`

**Files:**
- Modify: `agentpit/liquidity/reconciler.py` (`reconcile_market` signature and its `diff_levels` call around lines 155-182)
- Test: `tests/liquidity/test_mirror_diff.py` (append)

**Interfaces:**
- Consumes: `hot_cuts`, `is_hot_level` (Task 1), `diff_levels(..., protect=...)` (Task 2), `Settings.mirror_hot_depth` / `mirror_book_depth` (Task 3).
- Produces: `reconcile_market(db, order, onchain, user, ref, snap, cfg, *, cold: bool = False) -> dict` — the existing return dict, unchanged. Task 5 passes `cold=True` when a market is due for its sweep.

- [ ] **Step 1: Write the failing test**

This test exercises the tier decision without a DB or chain by checking the
helper that `reconcile_market` uses to build its diff arguments. Add the helper
as part of Step 3 so it is unit-testable on its own. Append to
`tests/liquidity/test_mirror_diff.py`:

```python
def test_tier_plan_hot_pass_targets_only_the_hot_band():
    snap = _snap(
        bids=[(400_000, 1), (390_000, 1), (380_000, 1)],
        asks=[(410_000, 1), (420_000, 1), (430_000, 1)],
    )
    desired, protect = tier_plan(snap, YES, NO, hot_depth=2, max_depth=50, cold=False)
    yes_buys = sorted(d.price_micro for d in desired if d.token_id == YES and d.side == "BUY")
    assert yes_buys == [390_000, 400_000]          # only the hot 2 bids
    assert protect is not None
    # a live cold order is protected, a live hot order is not
    assert protect(LiveLevel("c", YES, "BUY", 380_000, 1)) is True
    assert protect(LiveLevel("h", YES, "BUY", 400_000, 1)) is False


def test_tier_plan_cold_pass_targets_the_full_cap_and_protects_nothing():
    snap = _snap(
        bids=[(400_000, 1), (390_000, 1), (380_000, 1)],
        asks=[(410_000, 1)],
    )
    desired, protect = tier_plan(snap, YES, NO, hot_depth=2, max_depth=3, cold=True)
    yes_buys = sorted(d.price_micro for d in desired if d.token_id == YES and d.side == "BUY")
    assert yes_buys == [380_000, 390_000, 400_000]  # full cap
    assert protect is None                          # cold prunes stale levels


def test_tier_plan_hot_equals_cap_behaves_like_today():
    # The shipped default: hot 8 == cap 8. Nothing is protected, so a hot pass
    # is exactly the legacy single-tier reconcile.
    snap = _snap(bids=[(400_000, 1), (390_000, 1)], asks=[(410_000, 1)])
    desired, protect = tier_plan(snap, YES, NO, hot_depth=8, max_depth=8, cold=False)
    assert desired == desired_levels(snap, YES, NO, 8)
    assert protect is None
```

Extend that file's import from `agentpit.liquidity.reconciler` with `tier_plan`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/liquidity/test_mirror_diff.py -q`
Expected: FAIL — `cannot import name 'tier_plan'`.

- [ ] **Step 3: Implement `tier_plan` and use it in `reconcile_market`**

Add to `agentpit/liquidity/reconciler.py`, after `is_hot_level`:

```python
def tier_plan(
    snap: BookSnapshot,
    yes_token: str,
    no_token: str,
    *,
    hot_depth: int,
    max_depth: int,
    cold: bool,
) -> tuple[list[Placement], "Callable[[LiveLevel], bool] | None"]:
    """What one reconcile pass should target, and what it must leave alone.

    Cold pass: the full cap, protecting nothing — it also prunes deep levels
    that vanished upstream. Hot pass: the hot band only, protecting every live
    order outside it. When the hot depth already covers the cap there is no
    cold band, so the hot pass IS the full reconcile and protects nothing —
    that is the shipped default and it is identical to the legacy behaviour.
    """
    if cold or hot_depth <= 0 or (0 < max_depth <= hot_depth):
        return desired_levels(snap, yes_token, no_token, max_depth), None
    cuts = hot_cuts(snap, hot_depth)
    desired = desired_levels(snap, yes_token, no_token, hot_depth)
    return desired, lambda o: not is_hot_level(
        o.token_id, o.side, o.price_micro, cuts, yes_token
    )
```

In `reconcile_market`, add the keyword-only parameter to the signature —
`..., cfg: Settings, *, cold: bool = False) -> dict:` — and replace the
`diff_levels(...)` call (currently `reconciler.py:179-181`) with:

```python
    desired, protect = tier_plan(
        snap, ref.yes_token, ref.no_token,
        hot_depth=cfg.mirror_hot_depth,
        max_depth=cfg.mirror_book_depth,
        cold=cold,
    )
    cancels, places = diff_levels(desired, current, protect=protect)
```

Everything below that line — inventory, `cap_sells_to_inventory`, the
crossing classification and the settlement budget — is unchanged.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/liquidity -q`
Expected: PASS — the whole liquidity suite, including `test_mirror_engine.py`.

- [ ] **Step 5: Commit**

```bash
git add agentpit/liquidity/reconciler.py tests/liquidity/test_mirror_diff.py
git commit -m "feat(liquidity): reconcile in two tiers, hot band vs full sweep

A hot pass targets the top levels and protects the rest; a cold pass
converges the full cap and prunes what vanished upstream."
```

---

### Task 5: Cold-sweep scheduling with startup fan-out

**Files:**
- Modify: `agentpit/liquidity/mirror.py:164-203` (`run_reconciler`)
- Test: `tests/liquidity/test_mirror_cold.py` (create)

**Interfaces:**
- Consumes: `reconcile_market(..., cold: bool)` (Task 4); `Settings.mirror_cold_interval_seconds` (Task 3).
- Produces, both in `agentpit/liquidity/mirror.py`:
  - `cold_seed(asset: str, interval: float, now: float) -> float` — the initial `last_cold` value for an asset, spreading first sweeps across the interval.
  - `cold_due(last_cold: float, interval: float, now: float) -> bool` — whether this market's deep levels are due.

**Context you need before editing the loop:**
- `reconcile_market` has TWO call sites. `mirror.py:146` is inside `fill_markets`
  (the seeding / fill path) and calls it positionally without `cold`, so it stays
  hot — **leave that call exactly as it is.** Only the `run_reconciler` call
  (`mirror.py:188`) becomes tier-aware.
- `run_reconciler` itself has **no test coverage** — nothing in the suite drives
  it. `tests/liquidity/test_mirror_engine.py:194` monkeypatches
  `mirror.reconcile_market`, but only `fill_markets` invokes that fake, so your
  loop change cannot be caught there. That is exactly why the tier decision is
  extracted into the two pure functions above: they are the testable surface.
  Do not try to drive the `while True` loop from a test.

- [ ] **Step 1: Write the failing tests**

Create `tests/liquidity/test_mirror_cold.py`:

```python
# tests/liquidity/test_mirror_cold.py
from agentpit.liquidity.mirror import cold_due, cold_seed


def test_cold_due_only_after_a_full_interval():
    assert cold_due(last_cold=1000.0, interval=1800.0, now=2799.0) is False
    assert cold_due(last_cold=1000.0, interval=1800.0, now=2800.0) is True
    assert cold_due(last_cold=1000.0, interval=1800.0, now=9999.0) is True


def test_cold_due_never_when_sweeps_are_disabled():
    # interval <= 0 turns the cold tier off entirely: every pass stays hot.
    assert cold_due(last_cold=0.0, interval=0.0, now=1e9) is False
    assert cold_due(last_cold=0.0, interval=-1.0, now=1e9) is False


def test_a_seeded_asset_is_due_within_one_interval():
    # The seed offsets the first sweep into the past, so no market waits longer
    # than one full interval for its first deep reconcile.
    now, interval = 5_000.0, 1800.0
    seed = cold_seed("asset-42", interval, now)
    assert cold_due(seed, interval, now + interval) is True


def test_cold_seed_is_within_one_interval_in_the_past():
    now, interval = 10_000.0, 1800.0
    for asset in ("a", "b", "c", "d", "e"):
        seed = cold_seed(asset, interval, now)
        assert now - interval <= seed <= now


def test_cold_seed_is_stable_across_calls():
    # Must not use Python's salted hash(): a restart would reshuffle every
    # market's due time and could bunch them together.
    assert cold_seed("market-7", 1800.0, 500.0) == cold_seed("market-7", 1800.0, 500.0)


def test_cold_seed_spreads_assets_across_the_interval():
    # 200 assets should not land in one bucket: with 10 buckets over the
    # interval, every bucket gets at least one asset.
    now, interval = 0.0, 1000.0
    buckets = {int((now - cold_seed(f"asset-{i}", interval, now)) // 100) for i in range(200)}
    assert len(buckets) == 10
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/liquidity/test_mirror_cold.py -q`
Expected: FAIL — `cannot import name 'cold_seed' from 'agentpit.liquidity.mirror'`.

- [ ] **Step 3: Implement `cold_seed`**

Add to `agentpit/liquidity/mirror.py`, at module level (after the imports, before `MirrorEngine`), and add `import hashlib` to the module's imports:

```python
def cold_seed(asset: str, interval: float, now: float) -> float:
    """Initial `last_cold` for an asset, offset deterministically.

    Without this every market is due for its first cold sweep the moment the
    process starts, and a boot would place the whole deep book for every
    market at once. Hashing with hashlib (not the salted built-in hash) keeps
    a market's slot stable across restarts.
    """
    if interval <= 0:
        return now
    digest = hashlib.sha256(asset.encode()).digest()
    offset = int.from_bytes(digest[:8], "big") % int(interval)
    return now - offset


def cold_due(last_cold: float, interval: float, now: float) -> bool:
    """Are this market's deep levels due for a sweep? `interval <= 0` disables
    the cold tier entirely, so every pass stays hot."""
    return interval > 0 and now - last_cold >= interval
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/liquidity/test_mirror_cold.py -q`
Expected: PASS.

- [ ] **Step 5: Wire the cold clock into the loop**

In `run_reconciler` (`agentpit/liquidity/mirror.py:165`), add a second clock beside `last_run`:

```python
        last_run: dict[str, float] = {}
        last_cold: dict[str, float] = {}
```

and inside the `for asset in ready:` loop, replace the `reconcile_market` call
so the pass knows its tier (the existing call is the `await asyncio.to_thread(...)`
block):

```python
                    interval = self._cfg.mirror_cold_interval_seconds
                    if asset not in last_cold:
                        last_cold[asset] = cold_seed(asset, interval, now)
                    cold = cold_due(last_cold[asset], interval, now)
                    if cold:
                        last_cold[asset] = now
                    last_run[asset] = now
                    stats = await asyncio.to_thread(
                        reconcile_market, self._db, self._order, self._onchain,
                        self._user, ref, snap, self._cfg, cold=cold)
```

(`last_run[asset] = now` already exists immediately above the call — move it
into this block rather than duplicating it.)

- [ ] **Step 6: Run the liquidity suite**

Run: `.venv/bin/python -m pytest tests/liquidity -q`
Expected: PASS. Note what this does and does not prove: `run_reconciler` has no
test, so the suite is confirming that `test_mirror_engine.py`'s `fill_markets`
path still works (its fake `reconcile_market` takes no `cold` argument, and the
`mirror.py:146` call site must still not pass one) — the tier logic itself is
covered by the pure-function tests in `tests/liquidity/test_mirror_cold.py`.
If `test_fill_markets_seeds_then_reconciles` fails with an unexpected keyword
argument `cold`, you edited the wrong call site.

- [ ] **Step 7: Commit**

```bash
git add agentpit/liquidity/mirror.py tests/liquidity/test_mirror_cold.py
git commit -m "feat(liquidity): per-market cold sweep with a staggered start

Each market's deep levels reconcile once per interval. Seeds are hashed per
asset so the first sweeps fan out instead of arriving together on boot."
```

---

### Task 6: Full-suite verification and the production rollout note

**Files:**
- Modify: `deploy/env.prod.example`
- Modify: `docs/superpowers/specs/2026-07-29-mirror-deep-book-design.md` (append a rollout section)

**Interfaces:**
- Consumes: everything above.
- Produces: no code interfaces — this task proves the change is inert until enabled and records how to enable it.

- [ ] **Step 1: Prove the default is a no-op**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS with no failures. Record the summary line.

Then confirm the shipped defaults leave no cold band:

Run: `.venv/bin/python -c "from agentpit.config import Settings; s=Settings(); print(s.mirror_hot_depth, s.mirror_book_depth, s.mirror_cold_interval_seconds)"`
Expected: `8 8 1800.0` — hot equals the cap, so `tier_plan` returns `protect=None` and every pass is the legacy full reconcile.

- [ ] **Step 2: Add the production knobs to the example env**

In `deploy/env.prod.example`, replace the `AGENTPIT_MIRROR_BOOK_DEPTH=8` line with:

```bash
# Total book depth per side that the slow sweep converges to. Raising this is
# what turns the deep book on; the hot path is unaffected.
AGENTPIT_MIRROR_BOOK_DEPTH=50
# Levels per side re-quoted on EVERY upstream book update.
AGENTPIT_MIRROR_HOT_DEPTH=8
# How often each market's deep levels are refreshed.
AGENTPIT_MIRROR_COLD_INTERVAL_SECONDS=1800
```

- [ ] **Step 3: Append the rollout section to the spec**

Add at the end of `docs/superpowers/specs/2026-07-29-mirror-deep-book-design.md`:

```markdown
## Rollout

The code ships inert: production's `.env` sets `AGENTPIT_MIRROR_BOOK_DEPTH=8`
and the new `AGENTPIT_MIRROR_HOT_DEPTH` defaults to 8, so the cold band is
empty and every pass is the legacy full reconcile.

To enable, raise the cap in the production `.env` to
`AGENTPIT_MIRROR_BOOK_DEPTH=50` and restart the api container. Expect the
deep book to fill in gradually over the first `AGENTPIT_MIRROR_COLD_INTERVAL_SECONDS`
(30 min) rather than at once — the sweeps are staggered per market by design.

Watch during the first hour, on a 2 vCPU host:
- `docker stats` for the api container's CPU,
- `SELECT count(*) FROM orders WHERE STATUS = 'live'` — expect roughly 5x
  today's ~35k as depth converges toward 50 levels,
- `df -h /` and the json log sizes, since more placements mean more log lines.

To roll back, set the cap to 8 and restart: the next cold sweep per market
prunes the deep levels back out, since a cold pass protects nothing.
```

- [ ] **Step 4: Commit**

```bash
git add deploy/env.prod.example docs/superpowers/specs/2026-07-29-mirror-deep-book-design.md
git commit -m "docs(deploy): deep-book rollout knobs and what to watch"
```

---

## Notes for the implementer

- The prices in these tests are micros: `400_000` is 40 cents. `MICRO` is `1_000_000`.
- `BookSnapshot.bids` / `.asks` are tuples of `(price_micro, size_micro)`, already best-first — that ordering is what makes a slice "the top of book" and what `hot_cuts` relies on.
- Do not "simplify" `is_hot_level` into a single comparison. The NO side is the `MICRO - p` complement, so its inequality genuinely flips; the four-shape table in the spec is the contract.
- If a pre-existing test in `tests/liquidity/` fails, stop and report it rather than editing that test — those encode the non-crossing and settlement-budget invariants this change must not disturb.
