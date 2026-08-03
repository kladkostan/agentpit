# Launch plan

Working plan after the 2026-07-30 launch rundown with Ben and Ines. Ordered by
what blocks what, not by importance — several things here are more valuable than
the ones above them but cannot start yet.

## Done

**Getting a bot running.** [skalenetwork/agentpit-examples](https://github.com/skalenetwork/agentpit-examples)
is public: a single-file reference agent and the same logic as an OpenClaw skill.
Verified end to end against a local instance — install from the public repo,
prep, reason, finalize, order, fill, position. Five bugs surfaced only by running
it, including the one worth remembering: an agent answering "0.5" for "I don't
know" reads as a 28-point disagreement with a confident market and bets against
it. Abstention is now `probability: null`.

**The builder guide.** The landing page ends in five steps to a running bot —
key, install OpenClaw, add the agent, give it the key, dry run then schedule —
plus the whole thing as one paste. `/get-started` is deleted; the guide had been
duplicated across both pages and had already begun to differ.

Not yet deployed. Six commits sit on `mvp` ahead of production.

## Next, in order

### 1. Domain and TLS — half a day, blocked on DNS

Production is `http://23.88.62.130` with no certificate. Nothing public can
happen first: not the docs URLs, not the demo video, not the announcement.

Jack owns `agentpit.dev` (GoDaddy). Two A records to `23.88.62.130` — `@`
replacing the two parking entries, and `api`. Caddy issues certificates itself
once they resolve; the server config can be prepared beforehand so there is no
window where the site is unreachable over HTTPS.

### 2. Paper balance: 1 quadrillion → $100k — done, redeploy not yet live

Ben's ask, and a prerequisite for anything that ranks accounts.

We looked for a way to avoid a chain redeploy — since we custody user keys,
onboarding could in principle transfer the excess above $100k to a treasury
account and leave the user with exactly that much. We rejected it: with an
arbitrary mint amount the excess never exists in the first place, so there is
nothing to sweep, signup does not pay for an extra transaction, and there is no
second account that now needs its own funding and monitoring. So the faucet
mints a fixed amount baked into the contract, and its minter role cannot be
rotated — the redeploy the treasury idea was meant to dodge turned out to be
the only way to change the number, so we did it properly instead. `drip` is
now operator-only rather than permissionless, which was harmless when every
grant was a quadrillion but would otherwise be a way to route around the daily
cap now that balances are capped at $100k. The faucet gained a second entry
point, `mintTo(address, amount)`, that the operator alone can call for
one-off, non-drip mints.

The user's signup grant is now $100,000 flat, minted the same way it always
was. The house no longer draws from that figure at all — it gets a single
`mintTo` of 10^18 apUSD at deploy time, once, rather than repeated drips, so
the setting that used to keep it topped up is gone. "Refresh balance" is
`POST /me/top-up`: it mints the gap up to $100k, is rate limited to once per
24h by an atomic conditional update on the user's row (so two requests racing
each other can't both mint), and is a no-op that does not spend the day's
allowance if the account is already at or above target. `GET /me/top-up`
reports the same cooldown so the button can show a countdown instead of only
failing after a click.

All of this is code-complete and merged, but none of it is live: the new
faucet contract, the new grant amount, and the operator-only `drip` only take
effect once the chain is redeployed, and that has not happened yet.
Production is still handing out the old quadrillion-apUSD grant today.

### 3. A real leaderboard — three to four days, depends on 2

Today's Arena is a static `leaderboard.json` written by our own bot and shipped
as a frontend asset. No agentpit endpoint ranks anything, so a user who installs
the reference agent never appears.

Rank accounts by cash plus position value; both pieces exist per account and
have simply never been aggregated. **Only accounts that have traded appear** —
the natural filter, and it sidesteps putting every registered address on a
public board by default.

This has to follow the balance change. While everyone starts with a quadrillion
and trades in hundreds, the differences vanish into rounding and the board ranks
noise.

Compute it on a timer, not on read. `list_positions` reads the chain per
account, and pagination does not rescue that: to know who belongs on page one
you must value everyone, so paging limits what is sent and not what is
computed. A background pass writes each trading account's value to a column and
the endpoint becomes an ordinary `ORDER BY … LIMIT` — at which point paging is
free. `SnapshotService` already does exactly this shape for market mids, on a
timer, and is the thing to copy. It also fixes a second problem: the page polls
every four seconds, which on-read would mean walking every account, on-chain,
four times a minute, per open tab.

The five house personalities become ordinary rows, so they should be labelled
as ours — they fork one shared analysis rather than reasoning independently, and
they will be sitting next to agents that do.

### 4. Documentation — five to seven days, independent

Self-hosted at `agentpit.dev/docs`, no vendor. Guides in Markdown; the API
reference generated from the OpenAPI schema the backend already serves, so it
cannot drift. Measured before planning this: 40 of 41 endpoints documented, zero
stale entries — the reference exists and is accurate, it is only invisible.

Can run in parallel with anything above it.

## Blocked on other people

- **Jack** — the two DNS records.
- **Ben** — whether the launch targets developers or a mass audience. The
  written positioning says "the development platform… engineers use it"; the
  rundown said DGEN traders who will not read documentation. The two lead to
  different products, and the question worth putting to him is what a
  non-technical visitor gets out of paper money that brings them back tomorrow.
- **Ines** — landing copy, beta label, the SKALE section, demo video, logo.

## Deliberately not doing

**Hosting agents for users.** Each user runs their own reasoning on their own
machine; we do not hold anyone's model key and we are not a compute provider.

**A chat that trades.** The interface already does it in two clicks, and better.

**MCP.** It serves conversational trading, which is the thing above.

## Before a real chain

Not launch work, but it must not be discovered late. `AGENTPIT_SIMULATED_CHAIN`
must be set false first. It gates re-onboarding on a zero native balance, which
on a disposable chain means "the chain forgot this account" and on a durable one
means "this account spent its gas" — an ordinary state, reachable deliberately.
Left true, login mints a fresh gas grant on demand, repeatedly.
