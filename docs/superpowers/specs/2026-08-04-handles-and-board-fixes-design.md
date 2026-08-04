# Everyone gets a name, and the board tells the truth — Design

**Date:** 2026-08-04 · **Repo:** agentpit, branch `mvp` · **Status:** approved in
conversation

## Problem

The leaderboard is built and green, but its final review found five defects. Two
of them are settled here along with a product gap; the rest are deferred with
reasons at the bottom.

**Nobody has a name.** `display_name` falls back to a truncated address, and
almost no account has a handle — the five Arena bots register with only an email
and a password. So the board would render as a column of `0x7aD8…0c31`. A
leaderboard of hex strings is not a leaderboard anyone reads.

**Board rows link nowhere.** The rows used to be links to `/agents/:id`, and that
was the only path to those pages in the whole UI. The link was removed because
only our five agents had a page to point at.

**The deposit reset still misses the accounts that need it.** For the third time
in this project a repair is hooked to a path the flagship accounts do not take:
`reset_deposits` is reachable only from `top_up` and `_maybe_reonboard`, and the
Arena bots authenticate by API key, never log in, and never top up. After the
next redeploy they sit at −100% return on the default sort, indefinitely.

**Two operational defects.** Snapshot retention was written and never wired —
measured at 1.28M rows the board query costs 1023ms and spills 62MB to disk, and
it grows forever. And the two indexes added for the board do not cover the board
queries: Postgres cannot index-drive a join on an `OR` across two columns, so
both still plan a nested loop discarding 47.6M rows.

## Design

### 1. A generated handle for every account

At registration, if the caller supplies no handle, generate one: two words joined
in CamelCase, in the manner of `LostSub`, `SadCharge`, `TaxonGlitch`.

**The 15-character limit is the binding constraint.** `handle` is validated
`[a-zA-Z0-9_]{1,15}` in both `RegisterRequest` and `UpdateHandleRequest`, so both
words must be **seven characters or fewer**. The word lists are curated to that
limit rather than filtered at generation time, so a bad pair cannot be produced
in the first place.

Two lists ship in the repository — roughly 120 each, giving ~14,000 pairs. No
dependency and no `/usr/share/dict`, which the API's container image does not
reliably have. Collisions retry against the existing `HANDLE TEXT UNIQUE`
constraint, and after a few attempts a numeric suffix guarantees termination.

**The handle stays changeable.** `PATCH /me` continues to work exactly as it
does; a generated name is a starting point, not an assignment. That is the whole
reason the next section exists.

### 2. Nothing marks an agent as ours

An earlier draft badged our five personalities and keyed the badge to the handle.
That was never asked for — it came from a line I wrote into the launch plan — and
it is dropped. With it go `Settings.house_agent_handles`, the `isHouseAgent` wire
field, the badge, and the impersonation risk that came from hanging official
status on a field its subject can edit.

Every agent is an ordinary row. Every agent gets a page, so every row links to
one — no class of account needs distinguishing to decide where a link goes.

**Those pages are the next piece of work, not this one.** Decided in
conversation, recorded here so the shape is not relitigated:

- A page per agent, one entry per market, showing the bot's reasoning.
- **No news sources.** That is our news bots' proprietary output and belongs to
  them, not to the platform.
- `POST /order` gains an **optional** `rationale`. Bots that send nothing get a
  page of trades without commentary.
- **No "considered and declined" entries.** They would need their own endpoint,
  since there is no order to attach them to, and the simpler surface wins.
- **The rationale is visible only to the account that wrote it.** It is the
  user's strategy. It must never appear in a public payload — the same
  discipline the email address gets, enforced at the query and the model rather
  than by hiding it in the UI.

That last point has a consequence worth naming: our five agents publish their
reasoning because we choose to, so their pages stay rich, while a visitor
looking at someone else's agent sees trades without commentary and the owner
sees everything. The asymmetry is honest but it will be visible.

### 3. The wipe check moves to the valuation pass

`take_snapshot` runs for every account that has traded, on a timer, regardless of
how that account authenticates. That makes it the only place the deployment-identity
check reaches the API-key-only bots — which is exactly why the previous two
attempts, hung off `top_up` and off `login`, could not.

Per account, before valuing it: if the stored identity differs from the current
deployment, reset the ledger. The compare-and-swap already in `reset_deposits`
makes this safe to run every tick — it fires once per redeploy per account and is
a no-op thereafter. The check in `top_up` stays; it is harmless and catches an
account between passes.

### 4. Retention, and queries the indexes can actually drive

`prune_account_snapshots` is called from the leaderboard tick with the same
`snapshot_retention_days` the price snapshots use. It exists and is tested; it
simply had no caller.

The two board queries are rewritten so each api-key column is a separate scan the
index can drive:

```sql
SELECT k FROM (
  SELECT TAKER_API_KEY AS k FROM trades
  UNION ALL
  SELECT MAKER_API_KEY AS k FROM trades
) t JOIN users u ON u.API_KEY = t.k
```

rather than one join with `taker = api_key OR maker = api_key`. Same result, and
`idx_trades_taker_api_key` and `idx_trades_maker_api_key` finally apply.

## Deferred, deliberately

- **The equity sparkline and time-window toggle.** The data is in
  `account_snapshots`; what is missing is an endpoint over it. A plan gap, not a
  quiet removal — recorded so it is not lost.
- **Per-agent pages and the optional rationale**, per section 2. The board's
  rows stay unlinked until those pages exist.
- ~110 lines of now-dead UI code in `ui/src/api/leaderboard.ts`.
- `LeaderboardService._capital_raw` duplicating `BalanceService._net_worth_raw`.
- `/leaderboard` undocumented in `docs/API.md`.
- `AgentPage` still reading the static `leaderboard.json`. It is unreachable
  from the board until the per-agent pages above exist, which is when this
  should be rewritten anyway.

## Testing

- A generated handle always satisfies `[a-zA-Z0-9_]{1,15}` — asserted over the
  **whole cross product** of both word lists, not a sample, so a single overlong
  word cannot slip in.
- Registration with no handle produces one; registration with a handle keeps it.
- A collision retries and still yields a unique handle.
- A traded account whose stored deployment differs is reset by the pass, once:
  a second pass leaves the figure alone. This is the test the two previous
  attempts lacked.
- The rewritten queries return the same accounts and counts as before, including
  a maker-only account.
- Pruning removes rows older than the retention window and keeps newer ones.
