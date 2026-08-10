# Overdue but Still Trading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop dropping markets whose stated deadline has lapsed while Polymarket is still taking orders on them, and stop printing a date that has passed beside a live order book.

**Architecture:** Two independent changes. The sync's expiry test defers to upstream's `acceptingOrders` instead of trusting the stated date. The UI moves its "closes <date>" decision into a pure helper that returns `Awaiting resolution` when the date has lapsed on something still tradable.

**Tech Stack:** Python 3.13, psycopg3 + Postgres, pytest; Vite/React 18/TS, vitest.

## Global Constraints

- A market is over when **upstream says so**, not when its stated date passes. Exclude only when the end date has passed AND `acceptingOrders` is false.
- When `acceptingOrders` is absent from the payload — older Gamma shapes, fixtures — fall back to the current date-only behaviour. Do not silently loosen existing expectations.
- The existing `closed` check above the expiry test stays exactly as it is. It is orthogonal: it catches markets Gamma leaks despite `closed=false`.
- **The sync's ordering, cap and liquidity floor do not change**: `order="volume24hr"`, `SYNC_MAX_MARKETS=1000`, `max(liquidity, volumeNum) >= SYNC_LIQUIDITY_MIN=5000`. This was considered and rejected on measurement — see the spec.
- `END_DATE` is stored from upstream as-is. No schema change, no backfill.
- `EventSort.ENDING_SOON` keeps its `(END_DATE IS NULL OR END_DATE >= NOW())` predicate untouched — an overdue market is not "ending soon".
- The UI label copy is exactly `Awaiting resolution`, replacing the whole value AND its "closes" prefix.
- **The UI gate must include state, not just the date.** On production 50 past-dated events still have an ACTIVE market and 849 are fully resolved; gating on the date alone would make those 849 claim they await resolution.
- `ui/` vitest runs in a **node** environment and `@testing-library/react` is NOT installed — components cannot be render-tested. The label decision must live in a pure helper tested directly.
- `tsconfig` sets `exactOptionalPropertyTypes` — optional props need `foo?: T | undefined`.
- Backend tests: `cd /Users/yavorsky/dev/agentpit && .venv/bin/python -m pytest tests -q --ignore=tests/onchain`. NEVER source `.env` — `tests/conftest.py` uses `os.environ.setdefault` and a sourced `.env` defeats every default. The local anvil must be running (`./scripts/run_node.sh`).
- UI checks, from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`.
- Commit messages must NOT carry a `Co-Authored-By` trailer. Commit on branch `mvp`.

## File Structure

| File | Responsibility |
| --- | --- |
| `agentpit/polymarket/polymarket_sync.py` | `_normalize_market_fields` learns `acceptingOrders`; `_is_market_expired` becomes `_is_market_over`. |
| `tests/polymarket/test_polymarket_sync.py` | The three admission cases. |
| `ui/src/lib/format.ts` | `closeLabel` — the pure decision the two cards share. |
| `ui/src/lib/format.test.ts` | Its cases, including the 849-event trap. |
| `ui/src/components/MarketCard.tsx`, `ui/src/components/MultiMarketEventCard.tsx` | Render whatever `closeLabel` returns. |

---

### Task 1: Upstream decides whether a market is over

**Files:**
- Modify: `agentpit/polymarket/polymarket_sync.py` (`_normalize_market_fields` ~lines 140-174, `_is_market_expired` ~lines 176-194, its call site at ~line 299)
- Test: `tests/polymarket/test_polymarket_sync.py` (append)

**Interfaces:**
- Produces: `_is_market_over(market: dict) -> bool` replacing `_is_market_expired`. True means "exclude". Nothing else consumes it — grep to confirm before renaming.

- [ ] **Step 1: Write the failing test**

Append to `tests/polymarket/test_polymarket_sync.py`. That file imports
individual names in one block at the top; add `_is_market_over` and
`_normalize_market_fields` to it, and — in the same edit — drop the now-stale
`_is_market_expired` from the list. It is imported there today and **never
used**, so the rename costs exactly that one line and nothing else:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/polymarket/test_polymarket_sync.py -q -k "overdue or upstream_signal or deadline or accepting_orders"`
Expected: FAIL — `module 'agentpit.polymarket.polymarket_sync' has no attribute '_is_market_over'`.

- [ ] **Step 3: Normalize the new field**

In `_normalize_market_fields`, add the coalesce beside the other bool-ish fields and extend the coercion loop. The existing loop is:

```python
    for key in ("active", "closed", "archived"):
```

Add the key alias first, then include it in that tuple:

```python
    _coalesce_key(market, "accepting_orders", ["acceptingOrders", "acceptingOrder"])
```

```python
    for key in ("active", "closed", "archived", "accepting_orders"):
```

`_to_bool` already handles `True`, `"true"`, `"1"`, `1` and their false forms and returns `None` for anything it does not recognise — which is what leaves an absent field absent.

- [ ] **Step 4: Replace the expiry test**

Replace `_is_market_expired` with:

```python
def _is_market_over(market: dict) -> bool:
    """Is this market finished — as UPSTREAM sees it, not as its date claims?

    A stated end date is a deadline, not a verdict. Polymarket routinely lets a
    market trade past its own date while the question stays open: "Next Prime
    Minister of Ethiopia?" carried endDate 2026-06-01 and took $678k of volume
    in the 24 hours before this was written, ranking #5 of every active market.
    Trusting the date alone dropped 28 such markets out of the top-1000 window
    — $1.8M of daily volume, every one of them still accepting orders.

    So a lapsed date only counts when upstream has also stopped taking orders.
    When the payload carries no `accepting_orders` at all — older Gamma shapes,
    fixtures — the date decides, as it always did.
    """
    end_date_iso = market.get("end_date_iso")
    if not end_date_iso:
        return False
    try:
        # 'Z' is valid ISO 8601 but datetime.fromisoformat rejects it before 3.11.
        if end_date_iso.endswith("Z"):
            end_date_iso = end_date_iso[:-1] + "+00:00"
        end_date = datetime.fromisoformat(end_date_iso)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    if end_date >= datetime.now(timezone.utc):
        return False
    accepting = market.get("accepting_orders")
    if accepting is None:
        return True
    return not accepting
```

Then update the call site (currently `if not closed and _is_market_expired(m):`) to call `_is_market_over`. Before renaming, run `grep -rn "_is_market_expired" agentpit tests` and update every hit — leave no alias behind.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/polymarket/test_polymarket_sync.py -q`
Expected: PASS, including the file's pre-existing tests. Those fixtures carry no `acceptingOrders`, so they take the date fallback and behave exactly as before — that is the check that this did not loosen anything.

- [ ] **Step 6: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. If a test fails, read the failure — do not adjust an assertion.

- [ ] **Step 7: Commit**

```bash
git add agentpit/polymarket/polymarket_sync.py tests/polymarket/test_polymarket_sync.py
git commit -m "fix(sync): a lapsed deadline is not a finished market"
```

---

### Task 2: The cards stop printing a date that has passed

**Files:**
- Modify: `ui/src/lib/format.ts`
- Modify: `ui/src/components/MarketCard.tsx:41,79-87`
- Modify: `ui/src/components/MultiMarketEventCard.tsx:85,109-117`
- Test: `ui/src/lib/format.test.ts` (append)

**Interfaces:**
- Produces: `closeLabel(endDate: number | null, state: MarketState, nowSeconds: number) -> { prefix: string | null; value: string } | null`. `null` means there is nothing to show, and each card keeps its own existing fallback for that case.

**Why a helper and not an inline ternary:** `ui/` vitest runs in node with no `@testing-library/react`, so a component cannot be render-tested. A pure function is the only part of this that can be covered, and both cards must make the identical decision — they describe the same thing and must not label it differently.

- [ ] **Step 1: Write the failing test**

Append to `ui/src/lib/format.test.ts`:

```ts
describe("closeLabel", () => {
  const JUN_1 = Math.floor(Date.UTC(2026, 5, 1) / 1000);
  const AUG_10 = Math.floor(Date.UTC(2026, 7, 10) / 1000);
  const DEC_1 = Math.floor(Date.UTC(2026, 11, 1) / 1000);

  it("prints the date while it is still ahead", () => {
    expect(closeLabel(DEC_1, "ACTIVE", AUG_10)).toEqual({
      prefix: "closes",
      value: formatShortDate(DEC_1),
    });
  });

  it("says the outcome is pending once the date has passed on a live market", () => {
    // The Ethiopia case: deadline 1 Jun, still trading in August.
    expect(closeLabel(JUN_1, "ACTIVE", AUG_10)).toEqual({
      prefix: null,
      value: "Awaiting resolution",
    });
  });

  it("keeps printing the date for a past-dated market that is finished", () => {
    // 849 events on production are past-dated and fully resolved. Gating on
    // the date alone would have every one of them claim it awaits resolution.
    for (const state of ["RESOLVED", "CANCELLED", "CLOSED"] as const) {
      expect(closeLabel(JUN_1, state, AUG_10)).toEqual({
        prefix: "closes",
        value: formatShortDate(JUN_1),
      });
    }
  });

  it("has nothing to say without a date", () => {
    expect(closeLabel(null, "ACTIVE", AUG_10)).toBeNull();
  });
});
```

Add `closeLabel` to the file's existing import from `./format`.

- [ ] **Step 2: Run the test to verify it fails**

Run, from `ui/`: `npx vitest run src/lib/format.test.ts`
Expected: FAIL — `closeLabel is not a function`.

- [ ] **Step 3: Write the helper**

In `ui/src/lib/format.ts`, beside `formatShortDate`:

```ts
/** What a card prints where a closing date goes.
 *
 *  A market can trade past its own stated deadline — Polymarket keeps the book
 *  open while the question stays open — and printing "closes Jun 1" beside a
 *  live order book makes the card contradict itself.
 *
 *  The test is deliberately date AND state, never date alone: 849 events on
 *  production are past-dated and fully resolved, and for those the date is the
 *  right thing to show. */
export function closeLabel(
  endDate: number | null,
  state: MarketState,
  nowSeconds: number,
): { prefix: string | null; value: string } | null {
  if (endDate === null) return null;
  if (endDate < nowSeconds && state === "ACTIVE") {
    return { prefix: null, value: "Awaiting resolution" };
  }
  const value = formatShortDate(endDate);
  return value === null ? null : { prefix: "closes", value };
}
```

Add the type-only import at the top of the file:

```ts
import type { MarketState } from "@/types/market";
```

- [ ] **Step 4: Run the test to verify it passes**

Run, from `ui/`: `npx vitest run src/lib/format.test.ts`
Expected: PASS.

- [ ] **Step 5: Use it in the market card**

In `ui/src/components/MarketCard.tsx`, replace line 41:

```tsx
  const closes = formatShortDate(market.end_date);
```

with:

```tsx
  const closes = closeLabel(
    market.end_date,
    market.market_state,
    Date.now() / 1000,
  );
```

and the render block (lines 79-87) becomes:

```tsx
          <span className="shrink-0 whitespace-nowrap">
            {closes ? (
              <>
                {closes.prefix ? (
                  <span className="text-foreground/40">{closes.prefix} </span>
                ) : null}
                {closes.value}
              </>
            ) : (
              <span className="text-foreground/40">#{market.market_id}</span>
            )}
          </span>
```

Update the import on the file's existing `@/lib/format` line: `formatShortDate` may no longer be used here — check before removing it, the file may use it elsewhere.

- [ ] **Step 6: Use it in the event card**

In `ui/src/components/MultiMarketEventCard.tsx`, line 85 becomes:

```tsx
  const closes = closeLabel(event.end_date, state, Date.now() / 1000);
```

`state` is already computed on the line below as `eventState(markets)` — move the `closes` line BELOW it so `state` is in scope, rather than recomputing it.

The render block (lines 109-117) becomes:

```tsx
          <span className="shrink-0 whitespace-nowrap">
            {closes ? (
              <>
                {closes.prefix ? (
                  <span className="text-foreground/40">{closes.prefix} </span>
                ) : null}
                {closes.value}
              </>
            ) : event.category ? (
              <span className="text-foreground/40">{event.category}</span>
            ) : null}
          </span>
```

- [ ] **Step 7: Run every UI check**

Run, from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all four pass. `exactOptionalPropertyTypes` is on, so a type error here means the return shape needs `| undefined` rather than a cast — fix the type, do not cast.

- [ ] **Step 8: Commit**

```bash
git add ui/src/lib/format.ts ui/src/lib/format.test.ts \
        ui/src/components/MarketCard.tsx ui/src/components/MultiMarketEventCard.tsx
git commit -m "fix(ui): an overdue market says it awaits resolution, not a date"
```

---

## Self-Review

**Spec coverage.** Spec §1 (upstream decides) → Task 1 Steps 3-4. Spec §2 (stored date unchanged) → enforced by the Global Constraints line and by the absence of any schema or `EventSort` step. Spec §3 (the interface) → Task 2, with the 849-event trap as its own test case. Spec's "what this does not touch" → the Global Constraints line freezing the sync's ordering, cap and floor.

**Placeholders.** None. Every code step carries the code; every test step carries the assertions. Two steps say "check before removing/renaming" — those are grep instructions with a named command, not deferred decisions.

**Type consistency.** `closeLabel` is defined once in Task 2 Step 3 with the signature `(number | null, MarketState, number)` and both call sites in Steps 5-6 pass exactly that. Its return `{ prefix: string | null; value: string } | null` is destructured the same way in both cards. `_is_market_over` is named identically in the test (Step 1), the implementation (Step 4) and the call-site instruction.

**Ordering risk, flagged deliberately.** Task 2 Step 6 moves the `closes` line below `state`. If an implementer leaves it above, `state` is used before its declaration — `const` gives a TDZ ReferenceError at runtime, not a compile error in every config, so Step 7's build is the guard.
