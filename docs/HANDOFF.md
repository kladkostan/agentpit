# Where things stand — 2026-08-12

Written to hand this work to a fresh session. Everything below is on branch
`mvp`; **nothing here is deployed**. Production runs `mvp` at `1d7484d`, which
predates all of it by 55 commits.

## The WorkOS migration is finished in code

Sign-in is a six-digit code mailed by WorkOS, or Google through a WorkOS
redirect. There are no passwords anywhere in the sign-in path.

Plans 1–2 shipped earlier. **Plan 3 completed 2026-08-12** — all eight tasks,
each through an independent review, with a fix round wherever one found
something:

- `/register`, `/login` and the old in-page `POST /auth/google` answer **410**.
- A bearer token is verified by `AuthKitVerifier` or refused. The legacy
  `JwtCoder` path is gone from the request path.
- **`X-API-Key` is untouched.** Checked first, before any bearer path. Every
  trading bot keeps working across the cutover.
- Private-key export re-authenticates with a code mailed to the account's own
  address, pinned to `WORKOS_USER_ID`.
- Google is `GET /user_management/authorize?provider=GoogleOAuth` → our
  `/auth/callback` page → `POST /auth/callback` → `grant_type=authorization_code`.

Spec: `docs/superpowers/specs/2026-08-12-workos-cutover-design.md`.
Plan: `docs/superpowers/plans/2026-08-12-workos-cutover.md`.
Rollback: `docs/ROLLBACK.md` — read it before reverting, there is one expected
conflict and the instinct to hand-merge it is wrong.

**853 backend tests, 360 UI, all four UI gates green.**

## Verified against the live account, not inferred

Task 7 ran the Google redirect end to end against WorkOS Staging with a real
Google account. This is the class of check this project has already paid for
skipping once — the first token verifier was written from documentation, was
wrong in two ways, and every test passed because the tests minted their own
tokens.

- The access token carries `iss = https://api.workos.com/user_management/<client_id>`,
  **no `aud`**, `client_id` matching, lifetime exactly 300s, and exactly these
  claims: `auth_time, client_id, exp, iat, iss, jti, sid, sub`.
- WorkOS's own `state` JWT to Google decodes to `{"api": "user_management", …}` —
  WorkOS confirming the flow is User Management, not OIDC. **The `/oauth2/*`
  endpoints on the AuthKit domain issue a different issuer and must never be
  used.** Never introduce `WORKOS_ISSUER` or `WORKOS_JWKS_URL` as config: both
  are derived from `client_id`, and the value the OIDC discovery document hands
  an operator is the wrong one.
- Adoption was measured, not assumed: nulling `WORKOS_USER_ID` on a real row —
  the shape of all 17 production accounts — and signing in again produced the
  **same** `USER_ID`, the **same** `ETH_ADDRESS`, the same `ONBOARDED_AT`, no
  second wallet, and no change in the user count.

## Before the deploy, in this order

1. **`WORKOS_API_KEY` and `WORKOS_CLIENT_ID` on the box**, in the prod `.env` —
   they reach the api container through `env_file`, which is the only route.
   Use the **Production** client id, not staging's. Partial configuration is
   worse than none: api key alone means nobody can get a token, client id alone
   means everyone is signed in and then 401'd. Before this branch, a
   misconfigured deployment still worked on legacy JWTs; now it is a total
   human lockout, with `X-API-Key` still serving the bots.
2. **`WORKOS_AUTHKIT_DOMAIN`: set it correctly or leave it blank.** Nothing
   reads it. It used to crash-loop the whole API on a schemeless value; that now
   logs instead, but a wrong value still buys nothing.
3. **Google in WorkOS Production.** Decided 2026-08-12: use the **same** Google
   OAuth client as Staging. The reason a separate client was once required —
   protecting the live in-page flow — died with the cutover, which turns
   `/auth/google` into a 410. Add the production callback to that client:
   `https://auth.workos.com/sso/oauth/google/aceN1OYh0PviHcYaWNvumSv4y/callback`,
   then enable Google in WorkOS Production. **Deploying without this leaves the
   mailed code as the only door, which the spec forbids** — one WorkOS mail
   outage locks out all 17 accounts at once.
4. **`VITE_WORKOS_CLIENT_ID` and `VITE_WORKOS_REDIRECT_URI` in the prod `.env`.**
   `deploy/docker-compose.prod.yml` now refuses to build `caddy` without them,
   deliberately. Vite bakes them at build time, so a rebuild is required.
5. **Rename the WorkOS application** from `skalelabs.com's Application`. It is
   the sender name on the email that is now the only way anyone gets in, and the
   only thing distinguishing a sign-in code from a key-export code.

Not a prerequisite: `scripts/migrate_users_to_workos.py`. It cannot run before
the deploy — it selects `WORKOS_USER_ID` with `create_tables=False`, and the
column is added by the new image at startup. Run it after, or not at all:
`_link_existing_account` adopts an unmigrated row on its owner's first sign-in,
which is the path task 7 measured.

## What the deploy does to each kind of visitor

- **A returning browser** holding a legacy JWT: signed out exactly once,
  cleanly. `/me` 401s, there is no refresh token to try, `logout()` runs. The
  product already killed every session at 24 hours, so this is a disruption it
  inflicted daily anyway.
- **A browser already on an AuthKit session:** unaffected.
- **A bot on `X-API-Key`:** unaffected.
- **The 17 production accounts:** email → six digits → their existing row, wallet
  and positions. Their `PASSWORD_HASH` is deliberately preserved, which is what
  makes the rollback work.

## Known gaps, in the order they matter

- **`tests/onchain/` is dark.** Nine files POST `/register`: `_helpers.py:37`,
  `test_trade_flow.py:34,66,69,160,163`, `test_data_positions.py:31,33`,
  `test_data_trades.py:32,34,90`, `test_activity.py:32,34`,
  `test_balance_allowance.py:27,37`, `test_trade_enrichment.py:33,35`. Plus
  `scripts/seed_*.py`. That is the tier that catches trading regressions.
- **No programmatic account creation.** A bot author must now create the account
  in a browser and copy the key from Settings. `docs/API.md` says so; whether
  that is acceptable is a product decision nobody has made.
- **No server-side session revocation.** Measured: `maxSessionTime` is a year,
  `inactivityTimeout` 48 hours, the refresh token does not rotate and lives in
  `localStorage`. `logout` clears storage only. A leaked refresh token cannot be
  killed short of deleting the WorkOS user.
- **No rate limit on either code-mailing endpoint.** `/auth/code` is
  unauthenticated and is now the only door; the only ceiling is WorkOS's own
  429, and tripping it locks everybody out at once.
- **Not measured:** whether a second `magic_auth` send invalidates the first.
  `FakeWorkOsClient` assumes "latest wins" without evidence. Measure before
  relying on it.
- **Nobody is greeted on first sign-in.** `showWelcomeToast` is reachable only
  from `signInWithGoogle`, which no UI path calls any more.

## Plan 4 — the removal

`JwtCoder`, `JWT_SECRET` as an auth secret, the `PASSWORD_HASH` column,
`change_password` and its Settings row, `agentpit/auth/passwords.py`, the Google
verifier, `GoogleSignInButton.tsx`, `googleAuth.ts`, `loginRequest`/
`registerRequest`, and the 410 stubs.

**Doing it is what makes the rollback stop being cheap** — do not start until
the cutover has stood in production long enough to trust.

Two traps recorded for it: `liquidity/house_accounts.py` hashes a fixed constant
for accounts that never log in over HTTP, so deleting `passwords.py` without
changing it breaks the liquidity engine; and `TableWrite.create_user`'s docstring
still claims every account has a password hash or a `google_sub`, which
AuthKit-created accounts disprove.

## Still waiting on a person, unrelated to auth

- **62 GB in `~/.foundry/anvil/tmp`**, ~15 GB free. It is already flaking the
  local suite with `Web3RPCError -32003 replacement transaction underpriced`.
- **47 GB on prod's `agentpit-anvil-1`** writable layer — recreating the
  container (not restarting) frees it; the chain lives in a 263 MB volume.
- **The SKALE operator key.** The configured `ADMIN` is anvil's account #0, whose
  private key ships with every Foundry install.
- **The catalogue churn filter** (`1d024a7`, `3e1ff72`, `3ae4ea7`) is still
  undeployed and will ride along with whatever carries this.
