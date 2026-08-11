# Where things stand — 2026-08-11

Written to hand this work to a fresh session. Everything below is on branch
`mvp`; **nothing here is deployed**. Production runs `mvp` at `1d7484d`, which
predates all of it.

## Two streams of work, both finished-but-unshipped

### 1. Catalogue churn filter — done, waiting to deploy

Stops syncing two upstream series: the daily temperature markets and sports
props. Commits `1d024a7`, `3e1ff72`, `3ae4ea7`.

`3ae4ea7` is the **last commit before the WorkOS work begins**, which makes it
the clean point to deploy from: prod gets the filter without a line of
half-built authentication.

Why it matters, in the order the reasons actually weigh:

1. The product does not render these markets. A set handicap
   (`atp-halys-kwon-2026-08-11-set-handicap-home-1pt5`) has no reading on the
   site.
2. `CONDITION_ID` is `keccak(question)`, and upstream reuses prop question text
   between games. **251 of 529 sync attempts in three hours died on
   `UniqueViolation`**, and the row squatting on each reused string is a market
   from a game weeks past. Props are those strings.
3. The two series are 89% of new market creations, and creations plus
   resolutions are ~71% of ~870M gas/day. The same churn is what grows anvil's
   memory ~350MB/day — the reason the box needed 16GB.

Only new syncs are affected; markets already in the catalogue drain as they
resolve, over 2–8 days.

### 2. WorkOS AuthKit — plans 1 and 2 built, plan 3 unwritten

Sign-in moves to a six-digit code mailed by WorkOS. **No passwords at all.**

- Spec: `docs/superpowers/specs/2026-08-11-workos-authkit-design.md`
- Plan 1 (done): `docs/superpowers/plans/2026-08-11-workos-authkit-foundation.md`
- Plan 2 (done): `docs/superpowers/plans/2026-08-11-workos-magic-auth.md`

What exists: the WorkOS client, JWKS verification of their tokens,
`users.WORKOS_USER_ID`, a migration script, `/auth/code`, `/auth/session`,
`/auth/refresh`, AuthKit tokens accepted **alongside** the legacy JWT, and the
dialog's code step. 836 backend tests and 331 UI tests pass.

Nothing is removed yet: `/register`, `/login`, Google, `JwtCoder` and
`PASSWORD_HASH` all still work.

## Facts that were measured, not read

The first version of the token verifier was written from documentation and was
wrong in two ways that **every test still passed**, because the tests minted
their own tokens carrying exactly the claims the code assumed. These came off a
real staging token:

- `iss` is `https://api.workos.com/user_management/<client_id>` — **not** the
  AuthKit domain, which only hosts the sign-in surface and a JWKS.
- **There is no `aud` claim.** Passing `audience=` to `jwt.decode` rejects every
  valid token. Application pinning is done against the `client_id` claim.
- The access token lives **300 seconds**; the refresh token does **not** rotate.
- `POST /user_management/magic_auth` **creates the user** when the address is
  new and **returns the code in its response** — so the API key alone can sign
  in as anybody, and tests need no mailbox.

## The trap to not walk into

`export_private_key` picks its second factor by whether a password hash exists:
a hash means "prove the password", none means "prove the Google identity".
**Clearing `PASSWORD_HASH` on an account with no Google identity — the shape of
all 17 production accounts — locks the holder out of their own wallet key
permanently.** A reviewer caught this after it had already been written and
committed.

Adoption therefore leaves the hash alone. It goes only in plan 3, together with
the replacement: re-authentication by mailed code, one mechanism for everyone.

## Plan 3, when someone writes it

1. Google moves to the WorkOS redirect (`?provider=GoogleOAuth`). Staging works
   on WorkOS's demo credentials; production needs our own Google client — and
   a **new** OAuth client, not the live one, so the two flows cannot break each
   other during the transition.
2. Cutover: stop issuing our own JWT, accept only AuthKit tokens. Everyone is
   logged out once.
3. Removal: `JwtCoder`, `PASSWORD_HASH`, `change_password`, the Google verifier,
   the bcrypt-hash import in the migration script.
4. `export_private_key` re-auth becomes a mailed code.

Plus five Minor findings parked from plan 2's final review: the six-digit code
is not redacted from error bodies; a WorkOS 429 is collapsed into 401, telling a
rate-limited caller to do the throttled thing and leaving the UI's 429 copy
unreachable; `refresh()` can trigger on-chain onboarding; code sign-in skips
`_maybe_reonboard`, so the chain-wipe repair never runs for it; and two
concurrent first sign-ins for one new address answer 500 instead of a clean
retry.

## Waiting on a person

- **Deploy.** `3ae4ea7` to prod is the safe, valuable step.
- **47GB on prod.** `agentpit-anvil-1`'s writable layer holds anvil's temp
  files — recreating the container (not restarting) frees it; the chain lives
  in a 263MB volume and survives.
- **WorkOS Production** needs a card. Staging covers all development.
- **Rename** the WorkOS team/application from `skalelabs.com's Application` to
  AgentPit before any real user gets a code from it.
- **The SKALE operator key.** The configured `ADMIN` is anvil's account #0,
  whose private key is in every Foundry install — credits sent there are swept
  within seconds. A fresh key is needed before SKALE.

## Also stale

`README.md` still documents `POST /orders`, `/mint_usdc`, `/usdc_balance` and
`/transfer_usdc`, none of which exist, and predates the liquidity mirror, the
Arena, Google sign-in and everything above.
