# Top up against net worth, and record what was granted — Design

**Date:** 2026-08-04 · **Repo:** agentpit, branch `mvp` · **Status:** approved in
conversation

## Problem

The top-up mints `target − cash`. Measured on a live instance, three clicks:

```
start                    cash $100,000   positions $      0   net worth $100,000
day 1 (minted $100,000)  cash $100,000   positions $100,000   net worth $200,000
day 2 (minted $100,000)  cash $100,000   positions $200,000   net worth $300,000
day 3 (minted $100,000)  cash $100,000   positions $300,000   net worth $400,000
```

The "top up **to** a target rather than **by** a fixed sum" rule is not what
failed — it is measuring the wrong quantity. The difference is taken against
cash, and cash is zero at click time because it was moved into positions. So the
shortfall is the full grant every single time, while the previous grant sits in
positions and is never counted. Net worth grows without limit, with no skill
involved.

Separately, the leaderboard needs to rank by what a trader *earned*, which is
capital minus what they were handed. Nothing records the second number today, so
that column cannot be computed at all.

Both are one change to the same service, so they land together.

## Design

### 1. The threshold moves from cash to net worth

`topup_amount_raw(balance_raw, target_raw)` stays exactly as it is — a pure
`max(0, target − balance)`. What changes is the argument:

```
net_worth = onchain.usd_balance(address) + position_value(address)
minted    = topup_amount_raw(net_worth, target)
```

The mint is still **cash**, and it is still a top-up **to** the target. Only the
decision changes.

| cash | positions | net worth | minted |
|---|---|---|---|
| $0 | $100k | $100k | **0** — nothing was lost |
| $0 | $60k | $60k | $40k |
| $0 | $0 | $0 | $100k |
| $50k | $90k | $140k | **0** — ahead of target |

Position value comes from `AccountService.total_value(address)`, which already
exists and already backs `GET /value`. `BalanceService` gains it as a
constructor dependency rather than growing its own copy.

**It stays off the GET.** `GET /me/top-up` is a database read that the profile
page makes on load; `total_value` walks positions on chain. The POST can afford
that — it happens at most once a day and only when a human clicks. The GET
cannot.

**The consequence worth stating plainly:** a user fully invested has no cash to
trade with and the button will correctly offer nothing. They are not broke, they
are invested, and selling frees cash. A demo account at a real broker behaves
the same way.

### 2. Deposits are recorded, not derived

New column `users.TOTAL_DEPOSITED`, raw 6-decimal integer.

**Set at onboarding from the balance actually on chain**, read after the grant
transaction lands — not from a config constant. The signup grant lives in
`SIGNUP_GRANT_RAW`, a shell variable in `scripts/deploy_exchange.sh` baked into
an immutable contract at deploy time; `Settings.paper_balance_target_raw` is a
separate Python field. They are documented to agree and today they do, but they
are two sources and either can move. Reading the chain is exact and cannot drift.

**Incremented by every successful top-up**, in the same write that stamps the
cooldown, so a mint can never be recorded without its deposit or vice versa.

**NULL means "predates this column"** and reads as the signup grant. Two
production accounts and the house are in that state; a backfill migration would
have to invent the same number, so the default does it at the read instead.

That gives the leaderboard both numbers it needs:

| column | from |
|---|---|
| capital | cash + position value |
| earned | capital − deposited |
| return | (capital − deposited) / deposited |

Counting the signup grant as the first deposit matters twice: without it every
account shows a free $100k of "earnings", and relative return divides by zero
for anyone who never pressed the button.

## Why not restrict the button instead

Considered and rejected: leave the button alone and let the leaderboard's
ranking make farming pointless, since a farmer's return on deposits is ~0%.

That works for the ranking but not for the board itself. The user asked for
several sort orders — capital, absolute earnings, relative return — and under
the ranking-only approach the capital column becomes a clicking contest: the
demonstration above reaches $400k in three presses and would show millions
within a month. A number that came from nowhere sitting at the top of a public
board is not something a sort order can explain away.

So both: the threshold keeps the numbers real, and the deposit record makes the
ranking honest about the capital each trader was given.

## Out of scope

The leaderboard itself, its endpoint and its sort orders. This change lands the
two quantities it will read; ranking is its own piece of work.

## Testing

- Net worth, not cash, drives the threshold: positions at target with zero cash
  mints nothing. **This is the test that would have caught the bug** — it fails
  against the current code.
- The three-day loop from the Problem section, as an automated test: split all
  cash into positions and top up, three times, and assert net worth never
  exceeds the target.
- Below target by way of positions losing value mints exactly the shortfall.
- Deposits accumulate across several top-ups and equal grant + sum(minted).
- A NULL `TOTAL_DEPOSITED` reads as the signup grant.
- Already at or above target still does not consume the day's allowance.
- The GET makes no chain call — the existing tripwire fake already asserts this
  and must stay green.
