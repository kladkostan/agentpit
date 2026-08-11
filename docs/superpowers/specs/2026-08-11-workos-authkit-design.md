# WorkOS AuthKit owns authentication — design

**Status:** approved 2026-08-11
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
design and the user never leaves the site. Concretely:

- **Sign-up** creates the user at WorkOS unverified; WorkOS sends the code. The
  dialog gains a third mode for entering it, with a resend button and a
  cooldown — the flow already designed in the superseded spec.
- **Sign-in** calls AuthKit's password authentication.
- **Password reset** becomes possible for the first time and uses their flow.

### Google becomes a redirect

This is the one visible regression and it is unavoidable. Today the Google button
uses Google Identity Services in-page: the credential arrives in the browser and
is posted to us, with no navigation. AuthKit routes social login through
`GET /user_management/authorize?provider=GoogleOAuth`, which is a redirect to
WorkOS, then to Google, then back to a callback of ours that exchanges the code.

The in-page button is therefore replaced by a link that navigates. This undoes
the shape of the Google sign-in shipped on 2026-08-06 while keeping the feature.

### First sign-in is the sign-up

A WorkOS user with no `WORKOS_USER_ID` match is a new account, and the callback
creates the local row, the wallet, and runs on-chain onboarding — exactly what
`_onboard_new_account` does today. This is how a Google user signs up: there is
no separate registration for them, as there is none now.

The email-and-password path keeps its explicit gate: the local row is created by
successful **verification**, not by the WorkOS user existing. An unverified
address therefore still costs us no wallet and no gas — the property the
superseded spec was built around, preserved here.

### The address lives at WorkOS

`users.EMAIL` becomes a cached copy, not the source of truth: WorkOS is where an
address can be changed. The row is refreshed from the token's claims on every
sign-in, so a change upstream lands on our side at the next visit rather than
never. Nothing in the product keys off the address — every relationship uses
`USER_ID` — so a stale copy between visits costs only a display.

## Private key export needs a new second factor

`export_private_key` (`auth_service.py:207`) re-authenticates before handing over
a key that cannot be revoked. It does that today by verifying the password hash
we hold — and we will not hold one.

- **Password accounts:** re-auth by calling AuthKit's password authentication
  with the supplied password. A success is the proof; we never see a hash.
- **Google accounts:** no equivalent single call exists. Export requires a fresh
  authorization round-trip — the same redirect as sign-in, with `max_age` set so
  WorkOS re-prompts rather than reusing an old session — and the export is
  permitted only against the session that returns.

The existing `KEY_EXPORT_COOLDOWN_S` claim (`auth_service.py:241`) stays exactly
as it is. It is a guessing floor on our side and does not depend on who stores
the password.

## Migration

WorkOS accepts existing password hashes on user creation — `passwordHash` plus
`passwordHashType`, with bcrypt among the supported algorithms. **The 17
production accounts keep their passwords and nobody resets anything.**

For each existing row: create the WorkOS user with the address, `emailVerified:
true` (these accounts predate verification and are trusted colleagues), and the
bcrypt hash where one exists; store the returned id in `WORKOS_USER_ID`. Google
accounts have no hash and are created without one; they sign in through the
social path.

`PASSWORD_HASH` stops being authoritative the moment the cutover lands. It is
kept in place through the migration as a rollback path and dropped afterwards, in
a separate change.

**Everyone is logged out at the cutover.** Our JWTs stop being accepted and
AuthKit's have not been issued yet. This is accepted: sessions already die every
24 hours, so the disruption is one the product inflicts daily already.

## Ordering

1. The WorkOS client and configuration, behind an interface, with a test double —
   so no test reaches the network.
2. JWKS verification of AuthKit access tokens in the request path, accepted
   *alongside* our own JWT. Both work; nothing is broken yet.
3. The migration script: import the existing users, populate `WORKOS_USER_ID`.
4. Registration, sign-in, verification and resend move to AuthKit, and the dialog
   gains the code step.
5. Google becomes the redirect flow.
6. Cutover: our JWT issuance is removed and only AuthKit tokens are accepted.
7. Afterwards, separately: drop `PASSWORD_HASH`, remove `JwtCoder` and the Google
   verifier.

Steps 1–3 are additive and shippable on their own. Nothing is removed before
step 6.

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
- During steps 2–5, a legacy `JwtCoder` token still authenticates; after step 6
  it does not.
- Sign-up creates the WorkOS user and NO local row until verification succeeds;
  verification creates the row, the wallet, and runs on-chain onboarding.
- Key export re-auth succeeds with the correct password and fails with a wrong
  one, without any password hash existing locally.
- The migration script is idempotent: running it twice does not create a second
  WorkOS user for the same address.
- No test reaches the network: the WorkOS client is a double throughout.

UI, from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run
build`. `ui/` vitest runs in node with no `@testing-library/react`, so components
cannot be render-tested — the resend cooldown and code-input validation belong in
pure helpers. `tsconfig` has `exactOptionalPropertyTypes`.

Commits carry no `Co-Authored-By` trailer.
