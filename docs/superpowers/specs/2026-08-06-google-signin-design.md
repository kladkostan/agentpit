# Continue with Google — Design

**Date:** 2026-08-06 · **Repo:** agentpit, branch `mvp` · **Status:** approved in
conversation

## Problem

Signing up costs a password. The guide's first step is "get your key", and the
only way to get one is to invent a password for a paper-trading sandbox — the
kind of friction that loses the visitor who was only curious. Google sign-in
removes it for the majority who have a Google account, without taking the
password path away from anyone who prefers it.

Both paths stay. The dialog offers "Continue with Google" alongside the
existing email and password form, on both the sign-in and the sign-up tab.

## Design

### 1. The flow

Google Identity Services renders the button in the browser and hands back an
**ID token** — a JWT signed by Google. The front end posts it to
`POST /auth/google`, the backend verifies it and answers with the same
`AuthResponse` that `register` and `login` already return: our JWT plus the
public user record. Nothing downstream of authentication changes.

No redirect, no `client_secret`, no `state` to store, no callback route. The
authorization-code flow buys refresh tokens and access to Google APIs, neither
of which this needs.

### 2. What must be true of the token before we believe a single field

Verified locally against Google's JWKS, with the keys cached:

- the signature, against the key named by the token's `kid`
- `iss` is `accounts.google.com` or `https://accounts.google.com`
- `aud` equals our configured client id
- `exp` has not passed
- **`email_verified` is true**

The last one is load-bearing rather than ceremonial: section 4 links a Google
identity to an existing account by email address. Without the check, anyone who
could get Google to mint a token carrying somebody else's unverified address
would take over that account.

Verification is local rather than a call to Google's `tokeninfo` endpoint,
which is what Google recommends for production and which keeps a network round
trip — and a failure mode — out of the moment a person is signing up. It needs
`cryptography` alongside the `pyjwt` already in the project; `PyJWKClient` is
already available in the installed version.

### 3. What the database keeps

Two changes to `users`:

- `PASSWORD_HASH` becomes nullable. An account created through Google has no
  password, and a sentinel value would be a lie that some later `verify_password`
  call could trip over.
- `GOOGLE_SUB TEXT UNIQUE` holds Google's `sub`, the stable identifier for a
  Google account.

Lookup order on sign-in is `google_sub` first, then email. Email alone is not
enough: a person can change the address on their Google account, and an
email-only lookup would then treat them as a stranger and mint a second wallet.
`sub` does not change.

### 4. Linking, and what it is allowed to do

- **`google_sub` matches a row** — that is the account.
- **No `google_sub`, but the verified email matches a row** — the same person
  arriving by a new door. Stamp `google_sub` on that row, **clear its password**,
  and sign them in. One address is one account, one wallet, one leaderboard
  record.

  The password goes because we never checked that whoever set it owns the
  address: registration takes an address on trust, so anybody could have
  claimed a stranger's before its owner ever arrived, and leaving the password
  in place would let them keep a working credential on the account its real
  owner just walked into. Google's `email_verified` is the only proof of
  ownership in play, so it takes the account whole. The cost is that somebody
  who deliberately used both doors loses password login — section 6's message
  is what tells them so.
- **Neither matches** — a new account, created exactly the way section 5
  describes.

Splitting a person across two accounts is not a cosmetic problem here: each
account holds its own paper balance, its own positions and its own standing on
the board. Two accounts means the money and the record are in a place the
person cannot see from where they are standing.

### 5. Onboarding is one path, not two

A new Google account must receive precisely what a password signup receives: an
EVM keypair, a gas grant, the faucet drip, exchange approvals, `TOTAL_DEPOSITED`
seeded from the chain, `DEPLOYMENT_ID` recorded, and a generated two-word
handle.

**This is where the feature is most likely to go wrong, and the risk is not the
Google part.** Two signup paths that each perform their own onboarding will
diverge — one gains a step the other does not, and the difference surfaces
months later as an account that cannot trade. So the shared work is extracted
from `AuthService.register` into one routine that both callers use, and a test
asserts the two paths leave a new account in the same state.

### 6. Signing in with a password to an account that has none

`login` finds the row, sees `PASSWORD_HASH IS NULL`, and answers that the
account signs in with Google — not "invalid email or password", which sends
somebody who has forgotten which door they used around in a circle.

This tells an attacker that an address is registered, which registration
already tells them by answering 409 to a taken address. It reveals nothing new.

### 7. Configuration, and being off rather than half-on

- Backend: `GOOGLE_CLIENT_ID` in the environment. It is the audience the token
  is checked against. No client secret is involved in this flow.
- Front end: `VITE_GOOGLE_CLIENT_ID`, baked at build time. A client id is
  public by design — it appears in the page for every site that uses Google
  sign-in.

When it is unset the button does not render and `POST /auth/google` answers
503. The feature is absent rather than broken. A flag that silently produced a
working-looking but non-functional feature cost a day of confusion earlier this
week; this one fails visibly or not at all.

## The operator's part

Creating the Google Cloud OAuth client is not something this work can do for
itself:

1. A project in Google Cloud, with the OAuth consent screen configured
   (External, the app name and support email, and the `email` and `profile`
   scopes — both are default).
2. An OAuth client of type **Web application**.
3. Authorised JavaScript origins: `https://agentpit.dev` for production and
   `http://localhost:5173` for development. The ID-token flow needs no redirect
   URI.
4. The resulting client id goes into the server's `.env` as `GOOGLE_CLIENT_ID`
   and into the UI build as `VITE_GOOGLE_CLIENT_ID`.

## Out of scope, deliberately

- **Setting a password on a Google account.** Decided in conversation: an
  account that arrived through Google keeps using Google. There is no password
  reset flow in the product at all today, so adding a set-password endpoint
  would be the first half of a feature nobody asked for.
- **Any other provider.** The shape generalises, but a second provider is a
  second consent screen and a second set of decisions.
- **Unlinking Google from an account.**

## Testing

- A token failing any one of the five checks is rejected, each asserted
  separately — including `email_verified` false, which is the one that protects
  account linking.
- A token whose `aud` belongs to a different client is rejected. This is the
  check that stops a token minted for another site being replayed at ours.
- First Google sign-in creates an account; the second signs into the same one
  rather than creating another.
- A Google sign-in whose verified email matches a password account signs into
  that account and stamps `google_sub` on it — the wallet address before and
  after is the same one.
- **That account's old password stops working**, and says why. This is the
  test that closes the pre-registration hole in section 4.
- **A password signup and a Google signup leave an account in the same state**:
  same fields populated, handle generated, deposit recorded, onboarding run.
  This is the test that keeps the two paths from drifting.
- Signing in with a password to a password-less account says so, and does not
  say "invalid credentials".
- With `GOOGLE_CLIENT_ID` unset the endpoint answers 503 and no token is ever
  parsed.
