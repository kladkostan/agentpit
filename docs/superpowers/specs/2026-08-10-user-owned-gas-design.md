# Your wallet, your gas — design

**Status:** approved 2026-08-10
**Context:** the chain is moving to SKALE on Base, where the native coin is a
CREDIT bought with USDC — 21,000,000 gas per credit at $0.25. Everything below
is priced at that rate.

## Problem

Three things that cost nothing on a disposable anvil and are wrong on a chain
where gas is money.

### 1. Every auto-redeem gives away a whole coin

`polymarket_sync.py:1027`:

```python
def auto_redeem_resolved_markets(db, admin, *, gas_topup_wei: int = 10**18)
```

`10**18` is one full native coin. Neither call site in `app.py` overrides it,
and `fund_gas` fires unconditionally — before any check of whether the holder
needs gas at all. So each auto-redeem costs:

| | | |
| --- | --- | --- |
| the gas grant | 1.0 credit | **$0.2500** |
| the transfer itself | 21,000 gas | $0.0005 |
| the redeem | 91,743 gas | $0.0011 |
| | | **$0.2516** |

We hand over **227 times** what the operation consumes, and 99.6% of the cost
is the giveaway. The correct shape already exists eleven files away:
`liquidity/house_accounts.py:23` computes a top-up against a floor and a target
rather than a flat grant. The user path simply does not use it.

### 2. Auto-redeem spends someone else's gas without asking

A redeem is settlement, not a decision — a resolved outcome token is worth
exactly $1 and converting it involves no choice of price or timing. That is the
case for doing it automatically, and it is a good one.

It is outweighed by this: the wallet is the user's, and we have just built key
export precisely so they can hold it. Telling someone "this is your wallet" and
then transacting from it on their behalf is a contradiction that grows sharper
the more the native coin is worth. On a paper chain it meant nothing. On this
one it does.

### 3. An unredeemed win is mislabelled as a live position

`AccountService.list_positions` filters on `bal > 0` and nothing else — there is
no market-state check. So a resolved market whose winning token the account
still holds appears among **open positions**, priced by `_cur_price`. A resolved
market has no live book (the mirror cancels its orders once the market leaves
the active set), so that falls through to the last trade print: a share worth
exactly $1 is displayed at whatever it last changed hands for.

`list_closed_positions` cannot help, because it reconstructs won positions
**from REDEEM transactions** — until the redeem happens there is no closed row
either.

So the money is not hidden; it is worse than hidden. It is shown as a live
position at a stale price, in a market that can no longer be traded. Today
auto-redeem papers over this by always firing within minutes. Turn it off
without fixing it and every unclaimed win becomes a permanent lie on the
positions list.

That ordering constraint is the load-bearing part of this design: **the correct
presentation must ship with the switch-off, not after it.**

## Design

### On a real chain the house gives away gas exactly once, and only to open the door

The rule: **no gas grants at all, except the one that makes an account able to
trade in the first place.**

Signup stays sponsored, because it has to be. Three transactions —
`approve` × 2 and `setApprovalForAll` — are signed by the USER's key and must
land before the exchange can move their collateral or their outcome tokens.
Without them the account cannot trade at all, and a wallet with zero credits
cannot send them. That is the one place a grant buys something the user cannot
buy for themselves yet.

Size it to the job: 138,946 gas measured across all 16 accounts on the chain,
so a grant covering that plus a margin. Not `10**18`, which is 21,000,000 gas —
150 times the need. Cost per signup falls from **$0.25 to about $0.002**.

**The redeem top-up goes away entirely.** `fund_gas` disappears from
`auto_redeem_resolved_markets`. Claiming a win costs 91,743 gas ≈ $0.0011 and
the holder pays it from their own credits, like any other transaction they
choose to send. An account with no credits sees its unredeemed winnings and a
button that tells it what it needs.

That is also what makes the `signup_gas_grant_wei` question disappear from the
"out of scope" list below: there is now one grant, it is sized, and it is the
only one.

### Auto-redeem becomes a per-account choice, default off

A new `users.AUTO_REDEEM_ENABLED BOOLEAN NOT NULL DEFAULT FALSE`. The redeem
loop skips any account that has not opted in.

**Off for everyone, existing accounts included.** All 17 production accounts
start off. Their behaviour does change — a future win will wait for a click —
but nothing is lost or hidden, because the same release makes unredeemed
winnings visible with a button beside them. One rule for every account is worth
more than preserving a habit that only 17 people, nearly all colleagues, have.

The existing global `AUTO_REDEEM_ENABLED` setting stays as the kill switch: the
loop runs only when it is on AND the account has opted in.

No migration sweep is needed. Turning the flag off strands nothing, because the
visibility change surfaces every unclaimed win at the same moment.

### Unclaimed becomes the third state a position can be in

A position is open, or it is closed, or it is **decided but not collected**. The
profile's filter already names the first two; the third is missing, which is why
settled money ends up sitting under "open".

So: give it its own filter beside them, and value it correctly — a winning token
is worth exactly $1, not the last price it traded at. Each row carries its own
**Claim** button. The filter's label carries the total (`Unclaimed · $12.40`)
and the filter appears only when there is something to claim, so it is both the
number and the way to act on it, in one place, and absent when irrelevant.

The endpoint already exists: `POST /markets/{market_id}/redeem_position`
(`api/routes/positions.py:35`). Nothing new is needed on the write side.

Copy: the button says **Claim**, and so does the toast when it succeeds — one
name for one action, all the way through. Not "Redeem": that is the contract's
word, not the user's.

### Two balances, each named as the currency it is

The profile shows both, side by side, as the first two cells of the metric row:

```
┌──────────┬───────────┬───────────┬─────────────┬──────────────┐
│  apUSD   │  Credits  │ Positions │ Biggest Win │ Predictions  │
│ $100.0k  │   0.94    │  $75.9k   │   $6,641    │     239      │
└──────────┴───────────┴───────────┴─────────────┴──────────────┘
```

**The trading balance is labelled `apUSD`, never USDC.** That is not a
preference — the deployed collateral contract answers `symbol() = "apUSD"`,
`name() = "Agentpit USD"`, and the backend already calls it that throughout.
Calling it USDC would be a claim about redeemability that is simply false: this
token is minted by our own faucet. The first person to believe the label would
arrive asking why it will not withdraw.

`apUSD` and `Credits` are parallel — both name a currency rather than an
abstraction, so the pair itself teaches the distinction: one is what you trade
with, the other is what you pay to transact. `Balance / Credits` would not.

Credits also appear in **Settings**, beside the address and the export button,
where facts about the wallet live. And in the unclaimed view they appear
**conditionally**: claiming costs about $0.001, so say nothing while the account
can afford it, and when it cannot, replace the claim button's helper line with
what is missing and how to fix it. An empty wallet is a moment for direction,
not a number.

### The profit chart gives its width to the numbers

`ProfilePage.tsx:176` splits the header `lg:grid-cols-2` — the account card and
the Profit/Loss chart take half the width each. That weighs one trend line
equally against everything the account holds.

Make it `lg:grid-cols-3`, the account card spanning two columns and the chart
one. The chart keeps about 330px, which is ample for a sparkline whose job is
context rather than analysis.

This is also what makes the fifth metric cell fit. At half width the row is
about 500px across four cells — 125px each. At two thirds it is about 672px
across five — 134px each. The cells get *wider* while gaining one.

### The auto-redeem toggle goes in Settings

Its own row, after Address. The line under it says what it spends rather than
what it is: claiming a win costs a small amount of gas from this wallet, and
with this off you claim them yourself.

## Ordering

1. The grant changes — the signup grant sized to 138,946 gas plus a margin,
   and `fund_gas` removed from the redeem loop. Independent, and the largest
   saving.
2. Unredeemed winnings: compute, expose, show, with the redeem button.
3. Only then the per-account flag and the toggle.

Steps 2 and 3 may ship together but never in the opposite order.

## Out of scope

- Changing what a redeem does on chain.
- Withdrawal of any kind. Redeeming converts a resolved token into apUSD inside
  agentpit; it does not move money out.

## Testing

- Signup grants the sized amount, not a whole coin, and an account can still
  complete its three approvals with it.
- The redeem loop sends no gas at all: `fund_gas` is never called from it.
- A holder with too few credits to redeem gets a clear failure, not a silent
  one — the button says what is missing.
- The redeem loop skips an account with `AUTO_REDEEM_ENABLED` false and
  processes one with it true, with the global switch on in both cases.
- The global switch off means neither is processed.
- Unredeemed winnings: a resolved market where the account holds the winning
  token reports the balance; one where it holds the losing token reports
  nothing; one already redeemed reports nothing.
- The toggle persists and is reflected in the account payload.

Backend: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain` (never
source `.env`; the local anvil must be running). UI, from `ui/`:
`npx vitest run && npm run typecheck && npm run lint && npm run build`.
`ui/` vitest runs in node with no `@testing-library/react`, so any decision
worth testing belongs in a pure helper.
