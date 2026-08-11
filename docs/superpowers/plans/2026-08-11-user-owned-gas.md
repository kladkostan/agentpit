# Your Wallet, Your Gas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the house giving away gas it does not need to, stop settled winnings masquerading as live positions, and let the account decide whether we transact from its wallet.

**Architecture:** Four independent backend changes and two UI ones. The backend already computes `redeemable` correctly on every position — the defect is that it then prices a $1 token at its last trade. Most of this plan is small, precise edits to existing code plus one new route and one new column.

**Tech Stack:** Python 3.13, FastAPI, psycopg3 + Postgres, web3.py, pytest; Vite/React 18/TS, vitest.

## Global Constraints

- **The collateral token is `apUSD`, never USDC.** The deployed contract answers `symbol() = "apUSD"`, `name() = "Agentpit USD"`. Labelling it USDC is a false claim about redeemability.
- **One gas grant, at signup, sized to the job.** 138,946 gas measured across all 16 accounts on the production chain — two `approve` plus one `setApprovalForAll`. No other grant anywhere.
- **`fund_gas` disappears from the redeem loop entirely.** Claiming costs 91,743 gas ≈ $0.0011 and the holder pays it.
- Ordering, from the spec and not negotiable: the correct presentation of unclaimed winnings ships **with or before** the per-account switch-off, never after.
- The claim action is called **Claim** in the button, the toast and every string the user sees. `redeem` is the contract's word.
- `PositionWire.redeemable` already exists and is already computed correctly (`account_service.py:81-84`). Do not re-derive it.
- Backend tests: `cd /Users/yavorsky/dev/agentpit && .venv/bin/python -m pytest tests -q --ignore=tests/onchain`. NEVER source `.env` — `tests/conftest.py` uses `os.environ.setdefault` and a sourced `.env` defeats every default. The local anvil must be running.
- UI checks, from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`. `ui/` vitest runs in **node** with no `@testing-library/react` — components cannot be render-tested, so any real decision lives in a pure helper.
- `tsconfig` sets `exactOptionalPropertyTypes` — optional props need `foo?: T | undefined`.
- Commit messages must NOT carry a `Co-Authored-By` trailer. Commit on branch `mvp`.

## File Structure

| File | Responsibility |
| --- | --- |
| `agentpit/config.py` | The sized signup grant. |
| `agentpit/polymarket/polymarket_sync.py` | `fund_gas` removed from the redeem loop; the loop honours the per-account flag. |
| `agentpit/services/account_service.py` | A claimable position is worth exactly $1. |
| `agentpit/api/routes/positions.py` | Claim by condition id, because the UI has no market id. |
| `agentpit/api/routes/users.py` | The credits balance, and the auto-claim toggle. |
| `agentpit/db/table_create.py` / `table_read.py` / `table_write.py` | `AUTO_REDEEM_ENABLED`. |
| `ui/src/lib/positionBuckets.ts` (new) | Which bucket a position falls in, and the unclaimed total — the pure decision. |
| `ui/src/pages/ProfilePage.tsx` | The third filter, the Claim button, the 2:1 header, the fifth metric. |
| `ui/src/pages/SettingsPage.tsx` | The auto-claim toggle row and the credits line. |

---

### Task 1: One grant, sized, at signup only

**Files:**
- Modify: `agentpit/config.py:174-176` (`signup_gas_grant_wei`)
- Modify: `agentpit/polymarket/polymarket_sync.py:1026-1070` (`auto_redeem_resolved_markets`)
- Test: `tests/polymarket/test_polymarket_sync.py` (append)

**Interfaces:**
- Produces: `auto_redeem_resolved_markets(db, admin)` — the `gas_topup_wei` keyword is GONE, not defaulted to zero. A caller passing it should fail loudly.

- [ ] **Step 1: Write the failing test**

Append to `tests/polymarket/test_polymarket_sync.py`:

```python
# ----- the house stops paying other people's gas -----------------------------


def test_the_redeem_loop_never_funds_gas():
    """Claiming a win costs the holder 91,743 gas. On a chain where that is
    money, it is theirs to spend — and we were sending a whole coin, 227x the
    need, before every single claim."""
    import inspect
    from agentpit.polymarket import polymarket_sync

    src = inspect.getsource(polymarket_sync.auto_redeem_resolved_markets)
    assert "fund_gas" not in src
    assert "gas_topup_wei" not in src


def test_the_redeem_loop_takes_no_gas_argument():
    import inspect
    from agentpit.polymarket import polymarket_sync

    params = inspect.signature(
        polymarket_sync.auto_redeem_resolved_markets
    ).parameters
    assert "gas_topup_wei" not in params
```

An `inspect.getsource` assertion is normally a poor proxy for behaviour. Here the behaviour under test is an *absence* — that a call is never made on any path — and the loop's other paths need a chain. Task 4 adds the behavioural test that exercises this function with a stub.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/polymarket/test_polymarket_sync.py -q -k "never_funds or no_gas_argument"`
Expected: FAIL — `fund_gas` is still in the source.

- [ ] **Step 3: Remove the top-up**

In `agentpit/polymarket/polymarket_sync.py`, change the signature:

```python
def auto_redeem_resolved_markets(db, admin: OnchainAdmin) -> int:
```

and delete the whole `try/except` around `admin.fund_gas(...)` inside the holder loop, leaving:

```python
            try:
                svc.redeem(user, market.market_id)
                redeemed += 1
            except Exception:
                logger.exception(
                    "auto-redeem failed for %s on market %s",
                    user.eth_address,
                    market.market_id,
                )
                any_error = True
```

Add to the function's docstring one paragraph saying the holder pays their own
gas, and that a holder without enough credits simply fails and is retried next
pass — which is correct, because the winnings stay theirs either way.

Both call sites in `agentpit/api/app.py` already call it with no gas argument;
verify with `grep -n auto_redeem_resolved_markets agentpit/api/app.py` and
change nothing there.

- [ ] **Step 4: Size the signup grant**

In `agentpit/config.py`, replace the `signup_gas_grant_wei` default and comment:

```python
    # Gas for the three transactions a new account must send before it can
    # trade: approve(exchange), approve(ctf), setApprovalForAll(exchange).
    # Measured at 138,946 gas across all 16 accounts on the production chain.
    # At SKALE Base's 47.6 gwei that is 0.0066 native; this is 3x that, which
    # also covers a few later claims at 91,743 gas each. The previous default
    # was 10**18 — 21,000,000 gas, 150x the need — which cost $0.25 a signup
    # on a chain where the native coin is bought with USDC.
    signup_gas_grant_wei: int = Field(
        default=2 * 10**16, validation_alias="AGENTPIT_SIGNUP_GAS_GRANT_WEI"
    )
```

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. If an onboarding test asserts the old grant amount, read it — the number is the thing being changed, so updating that assertion is correct here, unlike an assertion about behaviour.

- [ ] **Step 6: Commit**

```bash
git add agentpit/config.py agentpit/polymarket/polymarket_sync.py \
        tests/polymarket/test_polymarket_sync.py
git commit -m "fix(gas): one grant, sized, at signup only"
```

---

### Task 2: A claimable position is worth exactly a dollar

**Files:**
- Modify: `agentpit/services/account_service.py:70-76` (inside `list_positions`)
- Modify: `agentpit/api/routes/positions.py` (append a route)
- Test: `tests/services/test_claimable_positions.py` (new)

**Interfaces:**
- Consumes: `PositionWire.redeemable`, already computed at `account_service.py:81-84`.
- Produces: `POST /positions/claim` with body `{"condition_id": "0x..."}` returning the existing `RedeemPositionResponse`.

**Why a new route:** the UI holds `conditionId` and no market id — `PositionWire` never carries one. The existing `POST /markets/{market_id}/redeem_position` stays exactly as it is; this is a sibling that resolves the condition first.

- [ ] **Step 1: Write the failing test**

Create `tests/services/test_claimable_positions.py`. Read a neighbouring service test first and match how it builds a service with a stubbed chain:

```python
"""A resolved market you have won is not a live position.

`list_positions` filters on balance alone, so a winning token still held
appears among OPEN positions priced by `_cur_price`. A resolved market has no
live book — the mirror cancels its orders when the market leaves the active
set — so that falls through to the last trade print. A share worth exactly $1
was being shown at whatever it last changed hands for.
"""

from __future__ import annotations


def test_a_claimable_position_is_priced_at_one_dollar(claimable_position):
    p = claimable_position
    assert p.redeemable is True
    assert p.curPrice == 1.0
    assert p.currentValue == p.size


def test_an_open_position_keeps_its_market_price(open_position):
    assert open_position.redeemable is False
    assert open_position.curPrice != 1.0


def test_the_losing_side_of_a_resolved_market_is_not_claimable(losing_position):
    """Holding the outcome that lost is worth nothing and claims nothing."""
    assert losing_position.redeemable is False
```

The three fixtures do not exist. Build them in this file over a market you
resolve with `resolved_outcome` set, with the chain balance stubbed — follow
whatever stubbing the neighbouring service tests already use rather than
inventing a new approach.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/services/test_claimable_positions.py -q`
Expected: FAIL — `curPrice` is the stale last-trade price, not 1.0.

- [ ] **Step 3: Price it correctly**

In `agentpit/services/account_service.py`, `list_positions`, the `redeemable`
computation currently happens *after* the price. Move it above, then use it:

```python
                redeemable = (
                    mkt.market_state == MarketState.RESOLVED
                    and mkt.resolved_outcome == idx
                )
                with self._db.read() as conn:
                    avg_price = self._avg_fill_price(conn, user.api_key, token_id)
                    # A won outcome pays exactly $1 a share. Its market has no
                    # live book any more, so `_cur_price` would fall through to
                    # the last trade print and show settled money at whatever
                    # it last changed hands for.
                    cur_price = (
                        1.0 if redeemable else self._cur_price(conn, token_id)
                    )
```

and delete the later `redeemable = (...)` assignment, leaving the
`PositionWire(...)` construction otherwise untouched.

- [ ] **Step 4: Add the claim route**

In `agentpit/api/routes/positions.py`, append:

```python
class ClaimRequest(BaseModel):
    condition_id: str


@router.post("/positions/claim", response_model=RedeemPositionResponse)
def claim_position(
    payload: ClaimRequest,
    user: CurrentUserDep,
    service: PositionServiceDep,
    db: SessionDep,
) -> RedeemPositionResponse:
    """Claim a won position by its condition id.

    The positions the UI holds carry a `conditionId` and no market id, so the
    existing `/markets/{market_id}/redeem_position` cannot be called from
    there. This resolves the one to the other and delegates; it adds no new
    behaviour of its own.
    """
    with db.read() as conn:
        market = TableRead.read_market_by_condition_id(
            conn, ConditionId(payload.condition_id)
        )
    if market is None:
        raise MarketNotFoundError(0)
    return service.redeem(user, market.market_id)
```

Add the imports it needs: `BaseModel` from pydantic, `SessionDep` from
`agentpit.api.deps`, `TableRead`, `ConditionId`, and `MarketNotFoundError` from
`agentpit.domain.exceptions`. Check each import path against a route file that
already uses it rather than guessing.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/services/test_claimable_positions.py -q`
Expected: PASS.

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. Existing position tests use unresolved markets, so their prices are unchanged.

- [ ] **Step 6: Commit**

```bash
git add agentpit/services/account_service.py agentpit/api/routes/positions.py \
        tests/services/test_claimable_positions.py
git commit -m "fix(positions): a won position is worth a dollar, not its last trade"
```

---

### Task 3: Unclaimed is the third thing a position can be

**Files:**
- Create: `ui/src/lib/positionBuckets.ts`
- Create: `ui/src/lib/positionBuckets.test.ts`
- Modify: `ui/src/pages/ProfilePage.tsx:43` (the `PositionFilter` type), `:112-120` (the filter memo), `:404-420` (the filter buttons), and the position row
- Modify: `ui/src/api/portfolio.ts` (add the claim call)

**Interfaces:**
- Consumes: `PositionWire.redeemable` (Task 2) and `POST /positions/claim` (Task 2).
- Produces: `positionBucket(p: { redeemable: boolean }) -> "unclaimed" | "active"` and `unclaimedTotal(positions) -> number`.

- [ ] **Step 1: Write the failing test**

Create `ui/src/lib/positionBuckets.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { positionBucket, unclaimedTotal } from "./positionBuckets";

describe("positionBucket", () => {
  it("puts a won-but-unclaimed position in its own bucket", () => {
    expect(positionBucket({ redeemable: true })).toBe("unclaimed");
  });

  it("leaves everything else among the active positions", () => {
    expect(positionBucket({ redeemable: false })).toBe("active");
  });
});

describe("unclaimedTotal", () => {
  it("adds up only what can be claimed", () => {
    expect(
      unclaimedTotal([
        { redeemable: true, currentValue: 100 },
        { redeemable: true, currentValue: 40.5 },
        { redeemable: false, currentValue: 999 },
      ]),
    ).toBe(140.5);
  });

  it("is zero when there is nothing to claim", () => {
    expect(unclaimedTotal([{ redeemable: false, currentValue: 999 }])).toBe(0);
  });

  it("is zero for an empty list", () => {
    expect(unclaimedTotal([])).toBe(0);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run, from `ui/`: `npx vitest run src/lib/positionBuckets.test.ts`
Expected: FAIL — the module does not exist.

- [ ] **Step 3: Write the helper**

Create `ui/src/lib/positionBuckets.ts`:

```ts
/** Which of the three states a position is in.
 *
 *  A position is open, or it is closed, or it is decided but not collected.
 *  The third had no name, so settled money sat under "active" — priced by a
 *  market that can no longer be traded. */
export function positionBucket(p: { redeemable: boolean }): "unclaimed" | "active" {
  return p.redeemable ? "unclaimed" : "active";
}

/** What the account is owed and has not collected, in dollars. */
export function unclaimedTotal(
  positions: readonly { redeemable: boolean; currentValue: number }[],
): number {
  return positions.reduce(
    (sum, p) => (p.redeemable ? sum + p.currentValue : sum),
    0,
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run, from `ui/`: `npx vitest run src/lib/positionBuckets.test.ts`
Expected: PASS, 5 tests.

- [ ] **Step 5: Add the claim call**

In `ui/src/api/portfolio.ts`, beside the other calls:

```ts
export function claimPositionRequest(conditionId: string): Promise<unknown> {
  return apiFetch<unknown>("/positions/claim", {
    method: "POST",
    body: JSON.stringify({ condition_id: conditionId }),
  });
}
```

Match the file's existing import of `apiFetch` rather than adding a second one.

- [ ] **Step 6: Wire the third filter**

In `ui/src/pages/ProfilePage.tsx`:

1. `type PositionFilter = "active" | "unclaimed" | "closed";`
2. In the memo at `:112-120`, choose the base list by filter: `closed` keeps `closedPositions`; `unclaimed` and `active` both start from `positions` and are then split with `positionBucket(p) === positionFilter`.
3. Compute `const unclaimed = unclaimedTotal(positions);` beside the other memos.
4. In the filter-button row, render the Unclaimed button **only when `unclaimed > 0`**, with its label carrying the amount: `` `Unclaimed · ${USD.format(unclaimed)}` ``. The number and the way to act on it belong together, and neither should be on screen when there is nothing to claim.
5. On a row in the `unclaimed` filter, render a `Claim` button that calls `claimPositionRequest(p.conditionId)`, shows `toast.success("Claimed.")`, and invalidates the positions query so the row leaves the list. On failure show the API's message via `ApiError`, as `ChangePasswordRow` does.

- [ ] **Step 7: Run every UI check**

Run, from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all four pass.

- [ ] **Step 8: Commit**

```bash
git add ui/src/lib/positionBuckets.ts ui/src/lib/positionBuckets.test.ts \
        ui/src/api/portfolio.ts ui/src/pages/ProfilePage.tsx
git commit -m "feat(profile): claim what you have won"
```

---

### Task 4: The account decides whether we spend its gas

**Files:**
- Modify: `agentpit/db/table_create.py` (`_migrate_users_table` additions list)
- Modify: `agentpit/db/table_read.py` (`_USER_COLS`), `agentpit/datastructures/user.py`, `agentpit/datastructures/auth_response.py`
- Modify: `agentpit/db/table_write.py` (a setter)
- Modify: `agentpit/polymarket/polymarket_sync.py` (`auto_redeem_resolved_markets`)
- Modify: `agentpit/api/routes/users.py` (a PATCH)
- Modify: `ui/src/pages/SettingsPage.tsx`, `ui/src/api/auth.ts`
- Test: `tests/polymarket/test_auto_redeem_optin.py` (new)

**Interfaces:**
- Produces: `User.auto_redeem: bool`, `UserPublic.auto_redeem: bool`, `TableWrite.set_auto_redeem(db, user_id, enabled) -> bool`, and `PATCH /me/auto-redeem` with body `{"enabled": bool}` returning `UserPublic`.

**Ordering:** this task must not land before Task 3. Turning the loop off while unclaimed winnings still look like live positions leaves every win mislabelled with no way to act on it.

- [ ] **Step 1: Write the failing test**

Create `tests/polymarket/test_auto_redeem_optin.py`:

```python
"""We stop transacting from someone's wallet unless they asked us to.

A redeem is settlement rather than a decision, which is the case for doing it
automatically. It is outweighed by the wallet being theirs — the same wallet we
now hand them the key to.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from agentpit.polymarket.polymarket_sync import auto_redeem_resolved_markets


def test_an_account_that_has_not_opted_in_is_skipped(db_with_a_won_position):
    db, admin = db_with_a_won_position(auto_redeem=False)
    assert auto_redeem_resolved_markets(db, admin) == 0


def test_an_account_that_opted_in_is_claimed_for(db_with_a_won_position):
    db, admin = db_with_a_won_position(auto_redeem=True)
    assert auto_redeem_resolved_markets(db, admin) == 1


def test_no_gas_is_ever_sent(db_with_a_won_position):
    """Task 1 removed the top-up; this is the behavioural proof, not a grep."""
    db, admin = db_with_a_won_position(auto_redeem=True)
    auto_redeem_resolved_markets(db, admin)
    assert not admin.fund_gas.called
```

`db_with_a_won_position` is a fixture you write in this file: a resolved market,
one participant holding the winning token, `admin` a `MagicMock` whose
`ctf_balance` returns a positive number for the winning token and 0 otherwise.
Read `tests/polymarket/` for how its neighbours build a db.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/polymarket/test_auto_redeem_optin.py -q`
Expected: FAIL — the loop redeems regardless of any flag.

- [ ] **Step 3: The column**

In `agentpit/db/table_create.py`, `_migrate_users_table`, append to `additions`:

```python
            ("AUTO_REDEEM_ENABLED", "BOOLEAN NOT NULL DEFAULT FALSE"),
```

Default false means every existing account — all 17 on production — starts opted
out, which is the decision in the spec.

- [ ] **Step 4: Carry it on the user**

Add `(AUTO_REDEEM_ENABLED) AS AUTO_REDEEM` to `TableRead._USER_COLS`, read it in
`_row_to_user` as `auto_redeem=bool(row["AUTO_REDEEM"])`, and add
`auto_redeem: bool` to both `User` and `UserPublic`. Both are required fields,
not defaulted — a default here would fail open and start spending gas.

In `agentpit/db/table_write.py`, beside `update_user_password_hash`:

```python
    @staticmethod
    def set_auto_redeem(
        db: psycopg.Connection, user_id: str, enabled: bool
    ) -> bool:
        cur = db.execute(
            "UPDATE users SET AUTO_REDEEM_ENABLED = %s WHERE USER_ID = %s",
            (enabled, user_id),
        )
        return cur.rowcount > 0
```

- [ ] **Step 5: Gate the loop**

In `auto_redeem_resolved_markets`, inside the holder loop, immediately after the
`if user is None: continue`:

```python
            if not user.auto_redeem:
                # Settlement is still theirs to trigger. The winnings do not
                # move or expire; they wait behind a button.
                continue
```

- [ ] **Step 6: The endpoint and the toggle**

In `agentpit/api/routes/users.py`, beside `update_me_password`:

```python
@router.patch("/me/auto-redeem", response_model=UserPublic)
def update_me_auto_redeem(
    payload: AutoRedeemRequest,
    user: CurrentUserDep,
    db: SessionDep,
) -> UserPublic:
    with db.write() as conn:
        TableWrite.set_auto_redeem(conn, user.user_id, payload.enabled)
        refreshed = TableRead.get_user_by_userid(conn, user.user_id)
    return UserPublic.model_validate((refreshed or user).model_dump())
```

with `AutoRedeemRequest(BaseModel)` carrying a single `enabled: bool`, defined
beside the other request models in that file.

In `ui/src/api/auth.ts`:

```ts
export function setAutoRedeemRequest(enabled: boolean): Promise<UserPublic> {
  return apiFetch<UserPublic>("/me/auto-redeem", {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
}
```

In `ui/src/pages/SettingsPage.tsx`, a row after Address, following
`ChangePasswordRow`'s shape — a label, a line of explanation, and a control on
the right. The label is **Claim winnings automatically**. The line says what it
spends, not what it is: *"Claiming costs a small amount of gas from this wallet.
With this off, you claim your winnings yourself."* On success update the session
user with the returned `UserPublic` so the control reflects what was saved.

- [ ] **Step 7: Run everything**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS.

Run, from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all four pass.

- [ ] **Step 8: Commit**

```bash
git add agentpit/db/ agentpit/datastructures/user.py \
        agentpit/datastructures/auth_response.py \
        agentpit/polymarket/polymarket_sync.py agentpit/api/routes/users.py \
        ui/src/api/auth.ts ui/src/pages/SettingsPage.tsx \
        tests/polymarket/test_auto_redeem_optin.py
git commit -m "feat(account): claiming is yours to trigger"
```

---

### Task 5: Two balances, and the width to show them

**Files:**
- Modify: `agentpit/api/routes/users.py` (a credits endpoint)
- Modify: `ui/src/api/portfolio.ts` or `ui/src/api/auth.ts` (the fetch), `ui/src/pages/ProfilePage.tsx:176` and `:202-221`, `ui/src/pages/SettingsPage.tsx`
- Test: `tests/api/test_credits_balance.py` (new)

**Interfaces:**
- Produces: `GET /me/credits` returning `{"credits_wei": "<decimal string>"}`. A string because a wei value overflows JavaScript's safe integer range.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_credits_balance.py`:

```python
"""The credit balance is what pays for a transaction. Without it a user can
hold a won position and be unable to claim it."""

from __future__ import annotations


def test_credits_are_reported_as_a_string(client, registered_user):
    r = client.post(...)  # replace with this suite's auth idiom
    r = client.get("/me/credits", headers=registered_user.auth_header)
    assert r.status_code == 200
    assert isinstance(r.json()["credits_wei"], str)
    assert int(r.json()["credits_wei"]) >= 0


def test_credits_need_authentication(client):
    assert client.get("/me/credits").status_code == 401
```

Adapt the fixtures to whatever `tests/api/` provides, exactly as the private-key
export tests did.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/test_credits_balance.py -q`
Expected: FAIL — 404.

- [ ] **Step 3: The endpoint**

In `agentpit/api/routes/users.py`:

```python
class CreditsWire(BaseModel):
    credits_wei: str


@router.get("/me/credits", response_model=CreditsWire)
def get_me_credits(user: CurrentUserDep, admin: OnchainAdminDep) -> CreditsWire:
    """The wallet's native balance — what pays for a transaction.

    A string because wei overflows JavaScript's safe integer range, and the
    front end formats it rather than doing arithmetic on it.
    """
    return CreditsWire(credits_wei=str(admin.native_balance(user.eth_address)))
```

`OnchainAdminDep` is the existing dependency — check its exact name in
`agentpit/api/deps.py` and use whatever is there.

- [ ] **Step 4: Give the numbers the width**

In `ui/src/pages/ProfilePage.tsx:176`, `lg:grid-cols-2` becomes `lg:grid-cols-3`,
the account `Card` gains `lg:col-span-2`, and the Profit/Loss `Card` is left at
one column.

The chart keeps about 330px, ample for a sparkline whose job is context. The
metric row goes from roughly 500px across four cells to 672px across five — each
cell gets *wider* while gaining one.

- [ ] **Step 5: The fifth cell**

At `:202`, `sm:grid-cols-4` becomes `sm:grid-cols-5`, and the cells become:

```tsx
              <TopMetric
                label="apUSD"
                value={balance != null ? formatVolume(balance) : "—"}
                tooltip={balance != null ? USD.format(balance) : undefined}
              />
              <TopMetric
                label="Credits"
                value={credits != null ? formatCredits(credits) : "—"}
              />
```

followed by the existing Positions / Biggest Win / Predictions cells unchanged.

`formatCredits` converts the wei string to a native-coin figure with two
decimals — put it in `ui/src/lib/format.ts` beside the other formatters, and
test it there with the same node-environment rules as everything else in that
file.

**The label is `apUSD`, never USDC.** The contract answers `symbol() = "apUSD"`.

- [ ] **Step 6: Credits in Settings**

Add the credits figure to the Address row in `SettingsPage.tsx`, under the
address, beside the line the export button already has. One line, the same
muted style.

- [ ] **Step 7: Run everything**

Run: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Run, from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add agentpit/api/routes/users.py ui/src/lib/format.ts \
        ui/src/lib/format.test.ts ui/src/api/ ui/src/pages/ProfilePage.tsx \
        ui/src/pages/SettingsPage.tsx tests/api/test_credits_balance.py
git commit -m "feat(profile): two balances, each named as the currency it is"
```

---

## Self-Review

**Spec coverage.** Spec §"one grant, sized" → Task 1. Spec §"unclaimed is the third state" → Tasks 2 and 3, split at the API boundary so a reviewer can reject the pricing without rejecting the UI. Spec §"per-account choice, default off" → Task 4, with the ordering constraint restated inside the task rather than only in this header. Spec §"two balances" and §"the chart gives its width" → Task 5. Spec's `apUSD`-never-USDC rule appears in the Global Constraints and again at the exact line where the label is written.

**Placeholders.** One deliberate: Task 5 Step 1 contains `client.post(...)  # replace with this suite's auth idiom`, and Task 2 Step 1 asks for three fixtures to be built by reading neighbours. Both are instructions to match an existing pattern the plan cannot quote without inlining another file; both name the file to read. Everything else carries its code.

**Type consistency.** `positionBucket` and `unclaimedTotal` keep the same names and signatures in the test (Task 3 Step 1) and the implementation (Step 3). `auto_redeem` is spelled identically on `User`, `UserPublic`, `TableWrite.set_auto_redeem` and the loop's guard. `credits_wei` is a string in the endpoint, the test and the TS formatter.

**One thing worth flagging.** Task 1's tests assert on `inspect.getsource` — normally a poor proxy. It is used because the property is an *absence* on every path, and the behavioural version needs a chain stub, which arrives in Task 4 Step 1's `test_no_gas_is_ever_sent`. If Task 4 were dropped, Task 1's coverage would be weaker than it looks.
