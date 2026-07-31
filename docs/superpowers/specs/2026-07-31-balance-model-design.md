# Paper balance: $100k per user, a top-up button, and one house mint — Design

**Date:** 2026-07-31 · **Repo:** agentpit, branch `mvp` · **Status:** approved in
conversation (redeploy accepted, contract change preferred over a new constant)

## Problem

Signup mints **1 quadrillion apUSD**. Ben's note from the launch rundown: it
should feel "realistic yet obtainable", like a broker's demo account, with a
button to restore the balance no more than once a day. He asked for $100k.

Three things follow that are not obvious.

**A quadrillion makes the leaderboard meaningless.** Ranking accounts that all
start at 1e15 and trade in hundreds ranks rounding error. Any account ordering
has to wait for this change.

**The grant cannot be re-sized in config.** `Faucet.drip(address)` takes no
amount — the figure is `immutable`, fixed in the constructor — and
`AgentpitUSD.mint` is `onlyMinter` with the minter permanently set to that
faucet (`setMinter` is itself `onlyMinter`, and the faucet never calls it). So
the only lever is *how many times* you call drip.

**One constant cannot serve both sides.** The house needs ~150bn apUSD to seed
every mirrored market and we want 1e18 for headroom; a user needs 1e5. A single
drip amount cannot be both, whatever it is set to.

## Design

Redeploy is already accepted, so change the contract rather than pick a
compromise constant.

### 1. Faucet gains an operator and an arbitrary mint

```solidity
address public immutable operator;

modifier onlyOperator() { require(msg.sender == operator, "only operator"); _; }

function drip(address to) external onlyOperator { token.mint(to, amount); }
function mintTo(address to, uint256 value) external onlyOperator { token.mint(to, value); }
```

`operator` is the same `admin` the deployment script already promotes on the
exchange, so no new key.

`drip` keeps the fixed signup grant — self-documenting, and the amount lives in
one place. `mintTo` covers the two cases a fixed amount cannot: the house, and
topping an account up to a target.

**`drip` becomes operator-gated, and that is a fix, not a side effect.** Today
it is permissionless: anyone who can reach the chain mints themselves a grant.
That was harmless when the grant was a quadrillion — nobody wants a second one —
but the moment users are capped at $100k, a permissionless mint is a way around
the daily limit. Production does not publish the anvil port, so this is belt and
braces rather than a live hole, but the cap belongs in the contract rather than
in the network topology. Every existing caller is our own backend
(`auth_service`, `house_accounts`), so nothing legitimate loses access.

### 2. The three flows

| | before | after |
|---|---|---|
| signup | `drip` → 1e15 apUSD | `drip` → **1e5** apUSD, exactly the grant |
| house | `drip` × `liquidity_funding_drips` | one `mintTo(house, 1e18)` |
| top-up | did not exist | `mintTo(user, target − balance)` |

`SIGNUP_GRANT_RAW` becomes `100_000 * 10**6 = 100_000_000_000`.

`liquidity_funding_drips` loses its purpose and goes; the house is one mint of a
stated size rather than N repetitions of someone else's grant.

**No treasury.** The earlier plan — drip, then transfer the excess to a holding
account, and pay top-ups out of it — existed only because the mint amount was
fixed. With `mintTo` the excess never exists, signup loses a transaction, and
there is no second account to fund, monitor or explain.

### 3. Top-up: to the target, not by the grant

`POST /balance/top-up`, authenticated, mints `target − balance` and returns the
new balance.

- **Above the target already?** No-op with the balance unchanged, not an error.
  Someone who traded their way past $100k has nothing to restore, and the
  button should say so rather than fail.
- **Once per 24h**, enforced server-side on a new `users.LAST_TOPUP_AT` column.
  The response carries the next eligible time so the button can show it.
- This is why it is a *top-up to* rather than a *grant of*: a fixed +100k would
  reward losing over winning, and Ben's ask was explicitly to restore the demo
  balance.

The button lives on the profile page beside the balance, disabled with a
countdown while the limit is in effect.

## What a redeploy costs

New contracts mean a new CTF, which means new ERC-1155 token ids, which the
database references throughout. The established recipe applies: fresh anvil,
`deploy_exchange.sh`, `db_reset.sh`, restart, resync.

**Every position, order and trade is lost, including the Arena's history.** On
production that is three accounts and a demo record. This is the last cheap
moment: after launch the same reset costs real users their track record.

## Testing

- `mintTo` from a non-operator reverts; from the operator mints exactly the
  amount asked.
- `drip` from a non-operator reverts — the regression that matters, since it is
  permissionless today.
- Top-up arithmetic as a pure function: below target mints the difference, at or
  above target mints nothing, and the result never exceeds the target.
- The 24h limit: a second call inside the window is refused and mints nothing;
  a call after it succeeds. Clock injected, not slept.
- Signup leaves exactly the grant — the assertion that would have caught the
  old behaviour.
- The existing on-chain suite must stay green: it covers the exchange and CTF,
  which this does not touch.

## Out of scope

- The leaderboard. It depends on this landing but is its own piece of work.
- Any change to the exchange, CTF, or matching. Only the mock faucet moves.
- Buying balance for SKL, which Ben floated as a revenue model. Later, and a
  product decision rather than an engineering one.
