# A real leaderboard, with everyone's bots on it — Design

**Date:** 2026-08-04 · **Repo:** agentpit, branch `mvp` · **Status:** approved in
conversation

## Problem

The Agent Arena renders `leaderboard.json` and `bot-status-<id>.json`, static
files bind-mounted next to Caddy. They are written by our own bot, running
against a **different machine's database**, and copied across. The copy on
production is dated **16 July** — nearly three weeks stale as of writing.

No agentpit endpoint ranks anything. So a user who follows the builder guide,
installs the reference agent and trades cannot appear on the board — not because
they are filtered out, but because there is nothing to appear *in*. The board is
a picture of a file.

Two consequences worth stating before designing anything:

**The board would be empty today.** Zero non-house accounts have ever traded on
production. The five Arena personalities point at `localhost:8000`. Pointing
them at `https://api.agentpit.dev` is what makes the board non-empty, and it is
a separate decision in a separate repository — see Out of scope.

**Nothing here works without the balance change that just shipped.** Ranking
needs capital *and* what each account was handed; `TOTAL_DEPOSITED` landed on
2026-08-04 for exactly this.

## Design

### 1. Compute on a timer, serve from memory

`AccountService.list_positions` reads the chain per account. Pagination does not
rescue that: to know who belongs on page one you must value everyone, so paging
limits what is *sent*, not what is *computed*. And the Arena page polls every
four seconds — on-read ranking would walk every account, on chain, fifteen times
a minute, per open tab.

So a background pass on a timer values every account that has traded and writes
one row per account into a new `account_snapshots (USER_ID, T, CAPITAL_RAW,
DEPOSITED_RAW)` table — the same shape and retention treatment `price_snapshots`
already has for market mids, and the same `SnapshotService` pattern.

The board itself is assembled at the end of each pass and held in memory, the
way `agentpit/api/routes/events.py` already caches its listing. The endpoint
serves that. A cold process computes once on first request rather than serving
nothing.

Storing `DEPOSITED_RAW` alongside capital keeps each snapshot self-contained, so
the equity curve can show *return* over time and not just a balance — which is
what the sparkline should be showing, given the default sort.

### 2. Who appears, and under what name

**Accounts with at least one trade.** The natural filter: it keeps every
registered address off a public board by default, and an account that has never
traded has nothing to rank.

**The house is excluded.** It is the market maker, the counterparty to nearly
every trade on the platform, not a competitor. `users.IS_BOT` already marks it.

**Our five personalities are labelled as ours.** They fork one shared analysis
rather than reasoning independently, and they will be sitting next to agents
that do. Presenting them as peers would misrepresent both.

**Name: the handle if set, otherwise the truncated address.** `users.HANDLE` is
already `TEXT UNIQUE` and settable through `PATCH /me`. Nobody drops off the
board for having left it blank. **The email address is never exposed** — not in
the payload, not as a fallback, not derived.

### 3. Four columns, defaulting to return

| column | from |
|---|---|
| capital | cash + position value |
| earned | capital − deposited |
| return | (capital − deposited) / deposited |
| trades | count from `trades` |

`GET /leaderboard?sort=return|earned|capital|trades`, default `return`.

**The default is the product decision, not a UI preference.** The default sort
is what "the leaderboard" means to anyone who visits, and capital alone ranks
whoever pressed the top-up button most — which is precisely the failure the
$100k cap and the deposit ledger exist to prevent. Capital stays available as a
sort because "who holds the most" is an honest question; it is just not the one
the board answers by default.

### 4. The chain-wipe reset, done properly

`TOTAL_DEPOSITED` does not currently survive a chain wipe: the database outlives
a disposable anvil, so an account returns with nothing on chain while the column
carries every historical grant, and `earned` reads deeply negative.

A reset was attempted in `top_up` and reverted, because zero native balance is a
**level, not an edge** — nothing on that path refunds gas, so the condition
stayed true and the reset re-fired on every later top-up, discarding what it had
just recorded. That revert deferred the fix here deliberately: the leaderboard is
the only consumer, and only the consumer can say what correct means.

The edge signal is the **deployment's identity**. Every redeploy writes new
contract addresses into `deployments/local.json`; the CTF address changes because
the contracts are new. Store it per account, and:

- absent (row predates the column) → record it, reset nothing
- unchanged → ordinary accumulation
- **changed → the chain was replaced.** Reset the deposit to this mint alone and
  record the new identity.

Edge-triggered, fires exactly once per redeploy per account, and needs no RPC at
all — unlike the native-balance check it replaces.

This removes the precondition currently written into `docs/launch-plan.md`: the
leaderboard may ship with `AGENTPIT_SIMULATED_CHAIN` still true.

### 5. The Arena reads the endpoint

`AgentArenaPage` moves from the static files to `GET /leaderboard`. The
`bot-status-<id>.json` files stay for now — they carry per-agent reasoning
detail that this endpoint does not attempt to replace, and untangling that is
its own piece of work.

## Out of scope

**Pointing the five Arena bots at production.** It is a configuration change in
`agentpit-trader` against live crons, and it is the difference between a board
with rows and a board without. Raised separately; not blocked by this work and
not blocking it.

**Adding a bot.** Already works: the builder guide plus the public examples
repository. Confirmed as out of scope in conversation.

**Per-agent reasoning detail** (`bot-status-*.json`) and multiple named agents
per user account.

## Testing

- Ranking arithmetic as pure functions over (capital, deposited): earned,
  return, and the ordering each sort produces. Return with zero deposited must
  not divide by zero — it cannot happen once the grant counts, and the test
  pins that.
- Only accounts with a trade appear; a registered-but-idle account does not.
- The house does not appear. Our five are present and flagged.
- The name is the handle when set and the truncated address when not, and **no
  response field contains an email** — asserted directly against the payload.
- Deployment identity: unchanged → accumulate; changed → reset to this mint
  alone; absent → record without resetting. The middle one is the test that
  would have caught the level-triggered bug, and it must fail against a reset
  that fires whenever the stored value is merely non-matching-or-null.
- The endpoint does no chain call — it serves the cache. A fake whose chain
  reads raise proves it, the way `tests/api/test_topup.py` already proves it for
  the top-up GET.
