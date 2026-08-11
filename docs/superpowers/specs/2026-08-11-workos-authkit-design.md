# WorkOS AuthKit owns authentication — design

**Status:** approved 2026-08-11, amended the same day — **there are no passwords
at all.** Sign-in is a six-digit code emailed by WorkOS (their Magic Auth), or
Google. Every section below reflects the amendment; what it removed is recorded
in "What passwords cost us" near the end.

**Supersedes:** `2026-08-11-email-verification-design.md`. That spec built email
verification on our own auth with Resend as the mail channel. The decision
changed: authentication moves to WorkOS entirely, which brings verification with
it. The dialog flow designed there — the code step, the resend button, the
cooldown — is reused; only the party generating the code and sending the mail
changes.

## Why

Registration takes any email address on trust (`auth_service.py:53`), and the
codebase already says so in the one place it mattered
(`auth_service.py:108-112`): *"Google verified this address; we never did."*
Fixing that ourselves means owning a mail channel, a code lifecycle, deliverability,
and — next — password reset and MFA.

WorkOS AuthKit provides all of it on a free tier of **1,000,000 monthly active
users** ($2,500/mo per additional million): email + password, social login,
passkeys, MFA, magic auth, enterprise SSO. Email verification is handled out of
the box and the mail is sent from WorkOS infrastructure, so `agentpit.dev` needs
no SPF/DKIM and no sender reputation. Sending from our own domain is their paid
Custom Domain add-on and is deliberately not taken.

### A daily logout comes along for free

`jwt_expires_seconds` defaults to `60 * 60 * 24` (`config.py:178`) and nothing
refreshes it. `AuthContext` keeps the token in `localStorage` and logs out on the
first 401. Every session therefore dies at 24 hours; it reads as a Google-only
bug because a password manager makes the re-login invisible while a Google
account has to walk through Google's window again.

AuthKit issues a short-lived access token plus a refresh token, so this class of
failure disappears with the old scheme rather than being fixed separately.

## Division of ownership

**WorkOS owns:** passwords and their hashing, email verification, password
reset, the emails, and — available but out of scope here — MFA and passkeys.

**We keep:** the wallet (`ETH_ADDRESS`, `ETH_PRIVATE_KEY`), `API_KEY`, handles,
positions, balances, everything that makes the account an agentpit account.

**The link:** one new column, `users.WORKOS_USER_ID TEXT UNIQUE`. Our `USER_ID`
stays the primary key and every foreign relationship in the product keeps
pointing at it.

## The session

AuthKit's access token is a JWT signed by a key published at
`https://<authkit-domain>/oauth2/jwks`. The API verifies it against that JWKS
with the expected `issuer` and `audience` (the client id), and reads
`sub` — the WorkOS user id — to find our row.

This replaces `JwtCoder` (`agentpit/auth/jwt.py`) in the request path. The symmetric
`JWT_SECRET` stops being an authentication secret.

**The `X-API-Key` path is untouched.** It is our own key for bots and the API, not
a session, and nothing about it moves to WorkOS. Every agent currently trading
through it keeps working across this migration without changes.

## Sign-up and sign-in stay in our dialog

Custom UI on the AuthKit API, not the Hosted UI. `AuthDialog.tsx` keeps its
design and the user never leaves the site.

**There is one flow, not two.** The dialog loses its `login` / `signup` modes
entirely. A person types their address, receives a six-digit code, types it in,
and is inside — whether or not they have been here before. WorkOS calls this
Magic Auth and it is two calls: `POST /user_management/magic_auth` sends the
code, `POST /user_management/authenticate` with
`grant_type: urn:workos:oauth:grant-type:magic-auth:code` returns the session.

The dialog therefore has two states — address, then code — plus a resend button
with a cooldown. That is strictly less UI than it has today.

A code rather than a link, and WorkOS agrees: they deprecated Magic Links
because security scanners fetch every link in a message and invalidate them
before the human arrives. It also keeps the session in the tab where it started.

**Verification stops being a step.** It is not possible to sign in without
reading the email, so every address in the system is proven by construction.
The problem this whole spec started from dissolves rather than being solved.

### Google becomes a redirect

This is the one visible regression and it is unavoidable. Today the Google button
uses Google Identity Services in-page: the credential arrives in the browser and
is posted to us, with no navigation. AuthKit routes social login through
`GET /user_management/authorize?provider=GoogleOAuth`, which is a redirect to
WorkOS, then to Google, then back to a callback of ours that exchanges the code.

The in-page button is therefore replaced by a link that navigates. This undoes
the shape of the Google sign-in shipped on 2026-08-06 while keeping the feature.

### First sign-in is the sign-up

A verified WorkOS identity with no `WORKOS_USER_ID` match is a new account, and
whichever door it arrived through — a Magic Auth code or the Google callback —
creates the local row, the wallet, and runs on-chain onboarding, exactly what
`_onboard_new_account` does today. There is no separate registration for anyone,
which is already true for Google users and is now true for everyone.

The gate the superseded spec was built around is preserved, and by a stronger
mechanism: **the account is created by a successful authentication, never by an
address being typed.** Somebody who enters a stranger's address and never reads
the mail causes a code to be sent and nothing else — no row, no wallet, no gas.
Where that spec enforced the rule with its own `pending_registrations` table, it
now falls out of what authentication means.

### The address lives at WorkOS

`users.EMAIL` becomes a cached copy, not the source of truth: WorkOS is where an
address can be changed. The row is refreshed from the token's claims on every
sign-in, so a change upstream lands on our side at the next visit rather than
never. Nothing in the product keys off the address — every relationship uses
`USER_ID` — so a stale copy between visits costs only a display.

## Private key export re-authenticates the same way for everyone

`export_private_key` (`auth_service.py:207`) re-authenticates before handing over
a key that cannot be revoked. It does that today by verifying a password hash we
hold, and we will hold none.

Passwordless makes this simpler rather than harder: **send a fresh Magic Auth
code and require it.** One mechanism for every account, password-era or Google,
because there is no longer any such distinction. An earlier draft of this spec
had password accounts re-auth one way and Google accounts another — a redirect
with `max_age` to force a re-prompt — and that asymmetry is now gone along with
the passwords that caused it.

The existing `KEY_EXPORT_COOLDOWN_S` claim (`auth_service.py:241`) stays exactly
as it is. It is a guessing floor on our side and does not depend on who stores
what.

## Migration

For each existing row: create the WorkOS user with the address and
`emailVerified: true` — these accounts predate verification and belong to
colleagues — then store the returned id in `WORKOS_USER_ID`. That is the whole
migration.

**No password hashes move.** WorkOS does accept a foreign bcrypt hash on user
creation, and the plan was to use it so nobody had to reset anything. With no
passwords anywhere there is nothing to carry: the 17 accounts sign in by code to
the addresses they already have. The hash-import path built in plan 1 becomes
dead weight and is removed rather than left to rot.

`PASSWORD_HASH` stops being read at the cutover, is kept through it as a rollback
path, and is dropped afterwards in a separate change.

**Everyone is logged out at the cutover.** Our JWTs stop being accepted and
AuthKit's have not been issued yet. This is accepted: sessions already die every
24 hours, so the disruption is one the product inflicts daily already.

## What passwords cost us

Recorded because the amendment deleted work that was already designed, and the
list is the argument for it. Removing passwords removes: password storage,
length rules, `change_password` and its Settings row, password reset (never
built, now never needed), the bcrypt hash import in the migration, the
`login` / `signup` split in the dialog, email verification as a separate step,
and the password-versus-Google asymmetry in key export. It adds two API calls.

**It costs one thing, and the cost is real: email becomes the only door.** Today
a person with a password gets in even while our mail is broken. Passwordless
means a mail outage locks out everybody, not just new arrivals. Google sign-in
stays precisely as the second door that does not touch email — which is why it
is not optional here.

## Ordering

0. **Establish what an AuthKit access token actually contains.** Mint one in
   staging, print its claims, and pin `AuthKitVerifier` to them. Plan 1 built
   that verifier to require `iss` = the AuthKit domain and `aud` = the client
   id; WorkOS's own session library verifies with neither, so if the real token
   omits `aud` the verifier rejects every sign-in. The tests cannot settle it —
   they mint their own tokens carrying exactly the assumed claims. Nothing below
   is worth building until this is checked against a real token.
1. Magic Auth send + verify behind the existing `WorkOsClient` protocol, with the
   double extended to match. No UI yet.
2. First sign-in creates the account: local row, wallet, on-chain onboarding.
3. The dialog: address, then code, then in. `login`/`signup` modes removed.
4. Google becomes the redirect flow.
5. Cutover: our JWT issuance removed, only AuthKit tokens accepted.
6. Afterwards, separately: drop `PASSWORD_HASH`, remove `JwtCoder`, the Google
   verifier, `change_password`, and the hash-import path in the migration.

Nothing is removed before step 5.

## Out of scope

- MFA and passkeys. Available on the free tier; enabling them is a later choice.
- Enterprise SSO and organizations. This product has individual users.
- The paid Custom Domain add-on.
- Any change to `X-API-Key`, to what a wallet is, or to on-chain onboarding —
  which still runs on first sign-up exactly as it does today.

## Testing

Backend: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`. Never
source `.env` — the conftest setdefaults get defeated and the live-sync tests
flake. The local anvil must be running.

Cases that must hold:

- A valid AuthKit access token authenticates the matching `users` row.
- A token with the wrong issuer, the wrong audience, an expired `exp`, or a
  signature from an unknown key is rejected.
- A valid token whose `sub` matches no `WORKOS_USER_ID` is rejected rather than
  silently creating an account.
- Until step 5, a legacy `JwtCoder` token still authenticates; after it, not.
- A first-time address gets a code, and entering it creates the local row, the
  wallet, and runs on-chain onboarding — one flow, no separate registration.
- A returning address gets a code and lands on its EXISTING row: no second
  wallet, no second onboarding, no second `USER_ID`.
- A wrong code, an expired code, and a code for a different address each fail
  without creating anything.
- Key export re-auth succeeds with a freshly-mailed code and fails with a stale
  or wrong one, with no password hash existing anywhere.
- Nothing anywhere reads `PASSWORD_HASH` after the cutover.
- The migration script is idempotent: running it twice does not create a second
  WorkOS user for the same address.
- No test reaches the network: the WorkOS client is a double throughout.

UI, from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run
build`. `ui/` vitest runs in node with no `@testing-library/react`, so components
cannot be render-tested — the resend cooldown and code-input validation belong in
pure helpers. `tsconfig` has `exactOptionalPropertyTypes`.

Commits carry no `Co-Authored-By` trailer.
