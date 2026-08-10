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

### 3. An unredeemed win is invisible

`AccountService.list_closed_positions` reconstructs won positions **from REDEEM
transactions**. Until the redeem happens there is no row anywhere saying the
user is owed money. Today auto-redeem hides that gap by always firing. Turn it
off without fixing it and winnings silently vanish from the interface.

That ordering constraint is the load-bearing part of this design: **visibility
must ship with the switch-off, not after it.**

## Design

### The top-up is sized to the job

Replace the flat `gas_topup_wei = 10**18` with a floor-and-target top-up
following `house_accounts.gas_topup_wei`: send nothing when the holder already
has enough, otherwise top up to a target sized on the measured cost of a redeem
(91,743 gas, so a target of a few hundred thousand gas leaves generous room).

This alone takes an auto-redeem from $0.2516 to about $0.0016. It is a bug fix
and lands regardless of everything else below.

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

### Unredeemed winnings become a number the user can see

For each RESOLVED market where the account still holds a winning outcome token,
the amount owed is that token's balance — a winning token is worth exactly $1.
Sum it, show it, and put a button next to it.

The redeem endpoint already exists: `POST /markets/{market_id}/redeem_position`
(`api/routes/positions.py:35`). Nothing new is needed on the write side.

### Two things to show in Settings

**Credits balance.** On SKALE the account's native balance *is* its credit
balance. We already read it (`_maybe_reonboard` uses `native_balance`). Show it
beside the address, where the export button now lives.

**The auto-redeem toggle**, with a line saying plainly what it spends: that
claiming a win costs a small amount of gas from this wallet, and that leaving
this off means claiming them yourself.

## Ordering

1. The top-up fix — independent, and the largest saving.
2. Unredeemed winnings: compute, expose, show, with the redeem button.
3. Only then the per-account flag and the toggle.

Steps 2 and 3 may ship together but never in the opposite order.

## Out of scope

- Changing what a redeem does on chain.
- The signup gas grant (`signup_gas_grant_wei`, also 1 coin, also ~150x
  oversized). Same class of problem, separately decided, separately measured.
- Withdrawal of any kind. Redeeming converts a resolved token into apUSD inside
  agentpit; it does not move money out.

## Testing

- The top-up sends nothing to a holder already above the floor, and tops up to
  the target for one below it.
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
