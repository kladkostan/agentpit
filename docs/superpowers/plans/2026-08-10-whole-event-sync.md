# Whole-Event Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a market qualifies for the sync, bring its sibling outcomes with it, so a 33-outcome event stops being represented by one candidate at <1%. And stop telling a reader an actively-trading market awaits resolution.

**Architecture:** The per-market filter is extracted from `fetch_all_polymarket_markets`'s loop so one predicate governs both the primary window and the siblings. A second pass batches Gamma's `/events?id=` for the distinct events of the primary window, keeps each event's top N open outcomes by 24h volume, and appends the ones the primary pass did not already have. The UI change is one string and one hard-coded literal.

**Tech Stack:** Python 3.13, psycopg3 + Postgres, pytest; Vite/React 18/TS, vitest.

## Global Constraints

- Every filter that applies to a primary-window market applies **unchanged** to a sibling: the liquidity floor `max(liquidity, volumeNum) >= liquidity_threshold`, the `closed` check, and the expiry rule `_is_market_over`. One predicate, used by both — do not write a second copy.
- The cap is **top 12 open outcomes by 24h volume**, read from configuration as `SYNC_EVENT_MAX_OUTCOMES` (default 12).
- A market that qualified in the primary window is never dropped by the cap. It is already in the primary list; siblings are only ever ADDED, never subtracted.
- **The sync's ordering, primary cap and liquidity floor do not change**: `order="volume24hr"`, `SYNC_MAX_MARKETS`, `SYNC_LIQUIDITY_MIN`. Switching the sort key to lifetime volume was measured and rejected — see `docs/superpowers/specs/2026-08-10-overdue-live-markets-design.md`.
- Measured cost of this change: 2,302 markets per pass against today's 1,000 (2.3x). Without the liquidity floor it would be 3,345 — the floor removes 1,043 empty siblings and is load-bearing, not incidental.
- The label copy becomes `overdue` + the lapsed date, replacing `Awaiting resolution`. Lowercase in the source: every call site sits inside a container with the `uppercase` CSS class.
- **The label gate does not change**: it fires only when the date has passed AND the state is `ACTIVE`. Production has 849 past-dated events that are fully resolved and must keep printing their date.
- Events need no new wiring: each market payload carries `events[0]`, and `polymarket_sync.py:424-442` already upserts the event from it.
- Backend tests: `cd /Users/yavorsky/dev/agentpit && .venv/bin/python -m pytest tests -q --ignore=tests/onchain`. NEVER source `.env` — `tests/conftest.py` uses `os.environ.setdefault` and a sourced `.env` defeats every default. The local anvil must be running.
- UI checks, from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`.
- Commit messages must NOT carry a `Co-Authored-By` trailer. Commit on branch `mvp`.

## File Structure

| File | Responsibility |
| --- | --- |
| `agentpit/polymarket/polymarket_sync.py` | The extracted predicate, the sibling pass, and its wiring into `fetch_and_sync_polymarket_markets`. |
| `agentpit/config.py` | `sync_event_max_outcomes`. |
| `agentpit/api/app.py` | Passes the new setting through. |
| `tests/polymarket/test_polymarket_sync.py` | The sibling-selection cases. |
| `ui/src/lib/format.ts`, `ui/src/lib/format.test.ts` | The copy. |
| `ui/src/pages/EventDetailPage.tsx` | Its hard-coded `"Closes "` literal. |

---

### Task 1: Pull the event's siblings, capped

**Files:**
- Modify: `agentpit/polymarket/polymarket_sync.py` (the filter loop in `fetch_all_polymarket_markets` ~lines 280-315; `fetch_and_sync_polymarket_markets` ~lines 624-650)
- Modify: `agentpit/config.py` (the sync block, ~lines 29-35)
- Modify: `agentpit/api/app.py:86-93` (`_run_polymarket_sync`)
- Test: `tests/polymarket/test_polymarket_sync.py` (append)

**Interfaces:**
- Produces: `_passes_market_filters(m: dict, *, liquidity_threshold: float, closed: bool, archived: bool) -> bool` — the predicate, applied to an ALREADY-normalized market. True means keep.
- Produces: `fetch_event_siblings(pm_markets: list[dict], *, cap: int, liquidity_threshold: float, host: str = POLYMARKET_GAMMA_URL, fetcher=None) -> list[dict]` — the extra markets, normalized, never including one already in `pm_markets`.
- Produces: `Settings.sync_event_max_outcomes: int` (env `SYNC_EVENT_MAX_OUTCOMES`, default 12).

- [ ] **Step 1: Write the failing test**

Append to `tests/polymarket/test_polymarket_sync.py`. Add `fetch_event_siblings` and `_passes_market_filters` to the existing import block at the top:

```python
# ----- an event is one question; half an answer is worse than none ----------


def _sib(name, *, v24, liq=20_000, closed=False):
    """One outcome of a multi-outcome event."""
    return {
        "conditionId": "0x" + name.encode().hex().ljust(64, "0")[:64],
        "question": f"Will {name} win?",
        "groupItemTitle": name,
        "volume24hr": v24,
        "volumeNum": 1_000_000,
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
    event = _event(favourite, _sib("Person C", v24=0, liq=0))
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
```

These tests reference the module as `polymarket_sync.…`. The file imports it
TODAY only inside a function body (line 100), which is not in scope at module
level — add `from agentpit.polymarket import polymarket_sync` to the imports at
the top of the file. Leave the existing function-local import alone.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/polymarket/test_polymarket_sync.py -q -k "sibling or cap_keeps or placeholder or no_event"`
Expected: FAIL — `module 'agentpit.polymarket.polymarket_sync' has no attribute 'fetch_event_siblings'`.

- [ ] **Step 3: Extract the predicate**

`fetch_all_polymarket_markets` currently normalizes and filters inline. Pull the filter out so the sibling pass cannot drift from it. Add above `fetch_all_polymarket_markets`:

```python
def _passes_market_filters(
    m: dict, *, liquidity_threshold: float, closed: bool, archived: bool
) -> bool:
    """Does this ALREADY-NORMALIZED market belong in the catalogue?

    The single copy of that question. The primary window and the sibling pass
    both call it, so a market cannot be admitted through one path and rejected
    through the other.
    """
    if not m.get("condition_id"):
        return False
    # Use the stronger of orderbook depth ("liquidity") and cumulative trade
    # volume ("volumeNum"). Multi-outcome favourites have shallow books on the
    # cheap side even though they're heavily traded — filtering on liquidity
    # alone silently drops exactly the markets users care about.
    liquidity = _as_float(m.get("liquidity"))
    volume = _as_float(m.get("volumeNum"))
    if volume == 0.0:
        volume = _as_float(m.get("volume"))
    if max(liquidity, volume) < liquidity_threshold:
        return False
    if not archived and m.get("archived", False):
        raise ValueError(
            f"API returned archived market {m.get('condition_id')} despite "
            "request for non-archived"
        )
    if not closed and m.get("closed", False):
        return False
    if not closed and _is_market_over(m):
        return False
    return True
```

Then replace the body of the `for m in data:` loop inside `fetch_all_polymarket_markets` with:

```python
        filtered_data = []
        for m in data:
            m = _normalize_market_fields(m)
            if _passes_market_filters(
                m,
                liquidity_threshold=liquidity_threshold,
                closed=closed,
                archived=archived,
            ):
                filtered_data.append(m)
```

Keep the `archived` ValueError inside the predicate — it is a guard against the API lying, and moving it changes nothing about when it fires.

- [ ] **Step 4: Write the sibling pass**

Add below `fetch_all_polymarket_markets`:

```python
#: Gamma caps a response at 100 rows; 40 ids per call leaves headroom.
_EVENT_BATCH = 40


def _fetch_events_by_id(ids: list[str], host: str) -> list[dict]:
    # Event ids are numeric strings from the payload we just fetched, and the
    # rest of this module builds Gamma URLs the same way (see
    # `fetch_polymarket_market`), so no escaping layer is introduced here.
    query = "&".join(f"id={i}" for i in ids)
    response = get(f"{host}/events?limit=100&{query}")
    return response if isinstance(response, list) else []


def fetch_event_siblings(
    pm_markets: list[dict],
    *,
    cap: int,
    liquidity_threshold: float,
    host: str = POLYMARKET_GAMMA_URL,
    fetcher=None,
) -> list[dict]:
    """The other outcomes of the events `pm_markets` belong to.

    An event is one question, and half an answer to it is worse than none: the
    top-1000-by-24h-volume window admitted exactly 1 of the 33 outcomes of
    "Next Prime Minister of Ethiopia?", so the site showed a $273M event as one
    candidate at under 1%.

    Keeps each event's `cap` busiest open outcomes by 24h volume. The median
    event has 11, so 12 lets most through whole and truncates only the
    long-tail monsters — the largest upstream events carry 128 outcomes and
    nobody trades their tail.

    Returns only markets NOT already in `pm_markets`, so a market that
    qualified on its own merit can never be displaced by the cap.
    """
    fetch = fetcher or _fetch_events_by_id
    have = {m.get("condition_id") or m.get("conditionId") for m in pm_markets}
    event_ids: list[str] = []
    for m in pm_markets:
        for e in (m.get("events") or []):
            if e.get("id") is not None and str(e["id"]) not in event_ids:
                event_ids.append(str(e["id"]))
    if not event_ids:
        return []

    extra: list[dict] = []
    for i in range(0, len(event_ids), _EVENT_BATCH):
        try:
            events = fetch(event_ids[i : i + _EVENT_BATCH], host)
        except Exception as exc:  # one bad batch must not lose the rest
            logger.warning(
                "event sibling fetch failed for batch %d (%s)",
                i // _EVENT_BATCH,
                exc.__class__.__name__,
            )
            continue
        for event in events:
            outcomes = [
                m for m in (event.get("markets") or []) if not m.get("closed")
            ]
            outcomes.sort(key=lambda m: -_as_float(m.get("volume24hr")))
            for m in outcomes[:cap]:
                m = _normalize_market_fields(m)
                if m.get("condition_id") in have:
                    continue
                if not _passes_market_filters(
                    m,
                    liquidity_threshold=liquidity_threshold,
                    closed=False,
                    archived=False,
                ):
                    continue
                have.add(m["condition_id"])
                extra.append(m)
    return extra
```

`get` (from `py_clob_client.http_helpers.helpers`) and `_as_float` are already
imported/defined in this module — line 22 and line 97. No new import is needed.

- [ ] **Step 5: Wire it in**

In `fetch_and_sync_polymarket_markets`, add an `event_max_outcomes: int = 0` keyword (0 disables the pass, which keeps every existing caller's behaviour unchanged), and between the fetch and the create:

```python
    if event_max_outcomes > 0:
        siblings = fetch_event_siblings(
            pm_markets,
            cap=event_max_outcomes,
            liquidity_threshold=liquidity_min,
            host=host,
        )
        logger.info(
            "event expansion added %d sibling markets to %d primary",
            len(siblings), len(pm_markets),
        )
        pm_markets = pm_markets + siblings
```

Extend that function's docstring Args block with the new parameter, in the style of the two already there.

In `agentpit/config.py`, beside `sync_liquidity_min`:

```python
    # When a market qualifies, its sibling outcomes come with it, capped at
    # this many per event (busiest first by 24h volume). The median upstream
    # event has 11 open outcomes, so 12 lets most through whole; the largest
    # carry 128 and nobody trades their tail. Measured cost at 12: 2302
    # markets per pass against 1000 without it. 0 disables the expansion.
    sync_event_max_outcomes: int = Field(
        default=12, validation_alias="SYNC_EVENT_MAX_OUTCOMES"
    )
```

In `agentpit/api/app.py`, `_run_polymarket_sync`, add the argument:

```python
            event_max_outcomes=settings.sync_event_max_outcomes,
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/polymarket/test_polymarket_sync.py -q`
Expected: PASS, including the file's pre-existing tests. Those exercise `fetch_all_polymarket_markets`, whose behaviour must be identical after the extraction — that is the check that the predicate was moved rather than changed.

- [ ] **Step 7: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. If a test fails, read the failure — do not adjust an assertion.

- [ ] **Step 8: Commit**

```bash
git add agentpit/polymarket/polymarket_sync.py agentpit/config.py \
        agentpit/api/app.py tests/polymarket/test_polymarket_sync.py
git commit -m "feat(sync): a qualifying market brings its event with it"
```

---

### Task 2: Say `overdue`, not `Awaiting resolution`

**Files:**
- Modify: `ui/src/lib/format.ts` (`closeLabel`)
- Modify: `ui/src/pages/EventDetailPage.tsx:172-180`
- Test: `ui/src/lib/format.test.ts`

**Interfaces:**
- Consumes and produces the unchanged shape `{ prefix: string | null; value: string } | null`. Only what goes in it changes.

**A latent bug this must fix.** `EventDetailPage.tsx:175` renders a hard-coded `<span>Closes </span>` whenever `closes.prefix` is non-null, ignoring the prefix's actual value. Harmless today, because the only non-null prefix is `"closes"`. The moment a second prefix exists, that page prints **"Closes Jun 1" on an overdue market** — precisely the bug this whole line of work removes. It must render `{closes.prefix}` like `MarketDetailPage.tsx:124` already does. The surrounding container carries the `uppercase` class, so a lowercase prefix renders identically to today's literal.

- [ ] **Step 1: Update the failing test**

In `ui/src/lib/format.test.ts`, the existing case asserting `Awaiting resolution` becomes:

```ts
  it("says the deadline lapsed, not that the market is settled", () => {
    // The Ethiopia case: deadline 1 Jun, upstream still reports
    // acceptingOrders true and $678k of 24h volume in August. Saying
    // "Awaiting resolution" told a reader the position was settled when they
    // could still take one.
    expect(closeLabel(JUN_1, "ACTIVE", AUG_10)).toEqual({
      prefix: "overdue",
      value: "Jun 1",
    });
  });
```

Leave every other case in that describe block exactly as it is — especially the finished-state loop, which is the 849-event regression guard.

- [ ] **Step 2: Run the test to verify it fails**

Run, from `ui/`: `npx vitest run src/lib/format.test.ts`
Expected: FAIL — received `{ prefix: null, value: "Awaiting resolution" }`.

- [ ] **Step 3: Change the copy**

In `ui/src/lib/format.ts`, inside `closeLabel`, replace the overdue branch:

```ts
  if (endDate < nowSeconds && state === "ACTIVE") {
    // The deadline lapsed, not the market: upstream keeps the book open while
    // the question stays open. Keep the date — how far it has slipped is
    // information — and drop the claim that anything is closing.
    const overdue = formatDate(endDate);
    return overdue === null ? null : { prefix: "overdue", value: overdue };
  }
```

- [ ] **Step 4: Fix the detail page's hard-coded prefix**

In `ui/src/pages/EventDetailPage.tsx`, replace the literal:

```tsx
                <span className="text-foreground/40">Closes </span>
```

with:

```tsx
                <span className="text-foreground/40">{closes.prefix} </span>
```

Leave `MarketDetailPage.tsx` alone — it already renders `{closes.prefix}`.

- [ ] **Step 5: Run every UI check**

Run, from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all four pass.

- [ ] **Step 6: Commit**

```bash
git add ui/src/lib/format.ts ui/src/lib/format.test.ts \
        ui/src/pages/EventDetailPage.tsx
git commit -m "fix(ui): an overdue market is overdue, not awaiting resolution"
```

---

## Self-Review

**Spec coverage.** Spec "pull the event, capped" → Task 1 Steps 3-5, with the cap in configuration as the spec requires. Spec's insistence that every primary filter applies unchanged to siblings → the extracted `_passes_market_filters`, used by both paths, and Task 1 Step 6's requirement that the pre-existing `fetch_all_polymarket_markets` tests pass untouched. Spec "the qualifying market is always kept" → `fetch_event_siblings` only ever returns markets NOT already present, so the primary list is never subtracted from; tested. Spec "say what is actually true" → Task 2. Spec's out-of-scope list → the Global Constraints line freezing ordering, primary cap and floor.

**Placeholders.** None. Every code step carries the code; every test step carries the assertions. Two steps say "check first" about an import — those are one-line greps, not deferred decisions.

**Type consistency.** `_passes_market_filters` takes the same three keyword names in its definition (Step 3) and both call sites (Steps 3, 4). `fetch_event_siblings`'s signature in the Interfaces block, the tests (Step 1) and the implementation (Step 4) agree on `cap`, `liquidity_threshold`, `host`, `fetcher`. `sync_event_max_outcomes` is spelled identically in `config.py` (Step 5), `app.py` (Step 5) and the `event_max_outcomes` parameter it feeds.

**Deliberate asymmetry, flagged.** `fetch_and_sync_polymarket_markets` defaults `event_max_outcomes=0` (disabled) while `Settings` defaults to 12. That is intentional: the function has other callers and tests that must not silently start making network calls, while production gets the expansion through the setting. Task 1 Step 6's full-suite run is what proves the default kept them quiet.
