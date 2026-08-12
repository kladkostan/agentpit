# Finishing the WorkOS migration — design

**Status:** approved 2026-08-12.

**Extends:** `2026-08-11-workos-authkit-design.md`, which is still the governing
design. That spec built plans 1 and 2 and sketched steps 4–6 of its Ordering in
a paragraph each. This one turns those into buildable detail and **corrects one
of its claims, which was written from documentation and is false** — see
"Measured against the live account" below.

Two plans come out of this spec:

- **Plan 3 — finish it.** Google becomes a WorkOS redirect, the five findings
  parked from plan 2's review are fixed, private-key export re-authenticates
  with a mailed code, and the cutover stops our own JWT being issued or
  accepted.
- **Plan 4 — remove it.** `JwtCoder`, `PASSWORD_HASH`, `change_password`, the
  Google verifier and the bcrypt import come out.

They are two plans and not one because between them is the only point where
production runs on WorkOS and a single revert still takes it back.

## Measured against the live account, 2026-08-12

Read out of the WorkOS control plane, not out of documentation. The project has
already paid once for the difference: the first token verifier was inferred
from docs, was wrong in two ways, and every test passed anyway because the
tests minted their own tokens carrying exactly the claims the code assumed.

**Google has no credentials in either environment.** The 2026-08-11 spec says
"Staging works on WorkOS's demo credentials". It does not. Both environments
hold a `GoogleOAuth` credential in state `Invalid` with a null `clientId`:

| Environment | `state` | `clientId` | AuthKit toggle |
|---|---|---|---|
| Staging | `Invalid` | `null` | `isUserlandEnabled: true` |
| Production | `Invalid` | `null` | `isGoogleOauthEnabled: false` |

Staging is the worse of the two: the toggle is on with nothing behind it, so
the provider is offered and fails. **Google cannot be built or verified until
real Google OAuth client credentials are supplied**, which is why plan 3 puts
that step first and blocks on it rather than building against a double.

The callback WorkOS expects registered on the Google side differs per
environment, and the identifier in it contains characters that mis-transcribe
(`1`/`l`/`I`, `0`/`O`) — copy, never retype:

- Staging: `https://auth.workos.com/sso/oauth/google/lKuLqgowoUQq1qygbeyfuEJq1/callback`
- Production: `https://auth.workos.com/sso/oauth/google/aceN1OYh0PviHcYaWNvumSv4y/callback`

**Redirect URIs already registered with WorkOS.** Staging: `http://localhost:5173/auth/callback`
(default) and `https://agentpit.dev/auth/callback`. Production:
`https://agentpit.dev/auth/callback` only, deliberately — development belongs
in Staging. Local development of the redirect flow is therefore possible, and
only against Staging.

**Production is configured as the design assumed** — `isMagicAuthEnabled: true`,
`isPasswordAuthEnabled: false`, `isEmailVerificationRequired: true`,
`allowSignUp: true` — and holds **zero users**, so nothing has been migrated and
no cutover has begun. `accessTokenExpiry` is `300`, confirming the 300 seconds
measured off a staging token on 2026-08-11 as a configured value rather than an
accident. `maxSessionTime` is a year and `inactivityTimeout` 48 hours.

Client ids, which are public: Staging `client_01KZRZ1QQXA15KX04VQBZPE0DZ`,
Production `client_01KZRZ1R41ZC4RB72CDE45508Y`.

**The application is still named `skalelabs.com's Application`.** That name is
what a person reads on the email carrying their code.

### Two issuers, and only one of them is ours

`https://<authkit-domain>/.well-known/openid-configuration` advertises
`"issuer": "https://supportive-banquet-05.authkit.app"`. The access tokens this
product verifies say `iss = https://api.workos.com/user_management/<client_id>`.
Both are true: they are different flows.

| Flow | Endpoints | `iss` |
|---|---|---|
| OIDC | `<authkit-domain>/oauth2/authorize`, `/oauth2/token` | the AuthKit domain |
| User Management | `api.workos.com/user_management/authorize`, `/authenticate` | `api.workos.com/user_management/<client_id>` |

`AuthKitVerifier` derives both the issuer and the JWKS URL from `client_id`
(`auth/authkit_tokens.py`) and pins the second. **The Google redirect must
therefore go through `/user_management/authorize` and `/user_management/authenticate`,
not through the `/oauth2/*` endpoints on the AuthKit domain.** Taking the
apparently-more-standard OIDC path yields tokens with the other issuer, and
every Google sign-in would be rejected — while the tests, which mint their own
tokens, stayed green. This is the same failure mode as the original verifier
and is recorded here so it is not walked into a second time.

For the same reason, `WORKOS_ISSUER` and `WORKOS_JWKS_URL` must not be
introduced as configuration. Neither is read today; both are derived. An
operator who sets `WORKOS_ISSUER` to the AuthKit domain — the value the
discovery document hands them — breaks every sign-in.

## Google becomes a redirect

The in-page Google Identity Services button shipped on 2026-08-06 goes away.
This is a visible regression and it is unavoidable: WorkOS has no grant that
accepts a Google ID token, so social login is a redirect or it is nothing.

1. The UI navigates to `https://api.workos.com/user_management/authorize` with
   `client_id`, `redirect_uri`, `response_type=code`, `provider=GoogleOAuth`
   and a random `state` it has just written to `sessionStorage`.
2. WorkOS sends the browser to Google and back to `/auth/callback` — a **front-end**
   route, because that is the URI registered with WorkOS.
3. The callback page compares `state` with what it stored, and on a match posts
   the code to `POST /auth/callback`.
4. The backend exchanges it at `/user_management/authenticate` with
   `grant_type: authorization_code` and hands the resulting `WorkOsSession` to
   `AuthKitService._resolve_account(create=True)` — the same method the mailed
   code already uses.

**The exchange is server-side because `client_secret` is our API key.** That is
the whole reason the redirect lands on a page rather than on an API route: the
browser may carry the code, never the secret.

**The route is provider-agnostic on purpose.** `authorization_code` is not a
Google grant. `POST /auth/callback` will accept a code from any provider WorkOS
is configured with, and from the AuthKit Hosted UI, without a line of new code.
Hence `/auth/callback` and not `/auth/google/callback`.

**`state` is checked, and checked in the browser.** The value never reaches our
API; the callback page refuses to post a code whose `state` does not match what
it stored. Without it, a link crafted by somebody else can complete a sign-in
in a victim's browser.

Today's Google accounts need no special handling. Their rows carry `GOOGLE_SUB`
and a null `PASSWORD_HASH`, and `AuthKitService._link_existing_account` already
adopts a row by case-insensitive email and stamps `WORKOS_USER_ID` on it. A
returning Google user lands on the account they already had; no second wallet,
no second onboarding. `GOOGLE_SUB` simply stops being read.

## The cutover

- `make_current_user_dep` loses its legacy branch. A bearer token is verified
  by `AuthKitVerifier` or it is refused.
- **`X-API-Key` is not touched.** It is checked first, before either token path,
  and every bot trading through it keeps working across the cutover. This is
  the single most important thing the cutover must not break.
- `/register`, `/login` and the old `POST /auth/google` answer **410 Gone**. The
  code stays where it is: 410 is a one-line change per route and reverting it
  restores a working legacy sign-in. Plan 4 deletes them.
- The dialog loses the password form and the `login`/`signup` modes entirely.

**Everybody is logged out once, and it happens cleanly without migration code.**
A returning browser holds a legacy JWT in `localStorage` and no refresh token.
Its first request 401s, `refreshAccessToken` finds `refreshTokenRef` empty and
returns null, the `UNAUTHORIZED_EVENT` handler runs `logout()`, and the person
sees the sign-in dialog. Sessions already die every 24 hours today, so this is
a disruption the product inflicts daily already.

### The migration script is no longer a prerequisite

Plan 1 built `scripts/migrate_users_to_workos.py` to create a WorkOS user per
existing row and store the id. That was designed as a precondition of the
cutover. It is not one any more: `_link_existing_account` adopts an
unmigrated row by email on its owner's first sign-in and stamps the identity
then.

Running it is still worth doing — it makes the 17 first sign-ins ordinary
lookups instead of adoptions, and it surfaces a bad address while somebody is
watching rather than while somebody is signing in. But if it fails halfway it
does not block anything, and the spec should stop implying otherwise.

## Private key export re-authenticates with a mailed code

`AuthService.export_private_key` chooses its second factor today by what the
account has: a `PASSWORD_HASH` means "prove the password", its absence means
"prove the Google identity". After the cutover no account has either.

It becomes two calls:

- `POST /me/private-key/code` mails a Magic Auth code to the account's address
  and answers 202.
- `POST /me/private-key` takes `{code}`, calls `authenticate_with_code`, and
  **requires `session.workos_user_id == user.workos_user_id`** before returning
  the key.

That pin is the load-bearing line. Without it, any valid code for any address
would satisfy the check and the key would go to whoever authenticated last —
exactly the reasoning behind the existing Google-identity check it replaces.
It also closes the stale-address case for free: `users.EMAIL` is a cached copy,
so if the address has changed hands upstream the code reaches a stranger, and
the code that stranger presents returns a different `workos_user_id` and is
refused.

`KEY_EXPORT_COOLDOWN_S` and the conditional-UPDATE claim behind it are
untouched. They are a guessing floor on our side and never depended on who
stores what.

**What this factor is worth, stated plainly.** It is not a second factor in the
strict sense: sign-in is also a mailed code, so this is the same factor a second
time. What it buys is **freshness**. A stolen `localStorage` token no longer
suffices to export a key that cannot be revoked — the holder must also be at the
mailbox at that moment. That is the entire argument for it, and it is written
down so that nobody later reads the symmetry as an oversight.

**Where that argument stops: the mail cannot say what the code is for.**
`send_key_export_code` and `AuthKitService.send_code` both post to the same
`POST /user_management/magic_auth` with `{"email": email}` — no scope, no
purpose, no audience. The six digits that sign a person in and the six digits
that release an unrevocable private key are one credential, and the message
carrying them is the generic AuthKit sign-in mail from an application still
named `skalelabs.com's Application`.

The cryptographic half of the freshness argument is unaffected: the holder of a
stolen token still cannot export without reaching the mailbox. The human-facing
half is weaker than it looks. Somebody phished with "confirm your sign-in" reads
a plausible mail, types the code, and has authorised a key export instead —
nothing in front of them distinguishes the two purposes. There is no in-product
mitigation for this while both flows share one WorkOS primitive; the
**application rename** listed under Plan 3's prerequisites is most of what is
available, since it at least puts our name on the mail the user is deciding
about. Recorded as a known limit rather than a solved problem.

## The five findings parked from plan 2's review

All five were re-checked against the code on 2026-08-12 and all five are still
open.

**The code is not redacted from error bodies.** `_redact` takes the literal
secrets a request carried, but `authenticate_with_code` passes only the API key
and the refresh token — the six-digit code is in the body and not in the list.
A WorkOS error that quotes the request back writes a live sign-in code into a
log. One entry added to the tuple.

**A WorkOS 429 is collapsed into 401.** Everything WorkOS refuses becomes
`WorkOsError`, and the handler answers 401 "request a new code" — which tells a
rate-limited caller to do precisely the thing that rate-limited them.
`WorkOsRateLimitedError(WorkOsError)` and a handler answering 429, following
`WorkOsUnavailableError` exactly. The UI copy for 429 is **already written** and
currently unreachable, so this fix switches on dead code rather than adding any.

**`refresh()` can trigger on-chain onboarding.** `_resolve_account` calls
`_finish_onboarding` on every resolution, including refresh, and that runs
`fund_gas` + `faucet_drip` + three approvals when `ONBOARDED_AT` is null.
Refresh is a background call every five minutes with nobody watching, and the
whole page's requests queue behind the shared in-flight refresh while it waits.
**Decision: `_finish_onboarding` runs on the `sign_in` path only.** The repair
is not lost — the next sign-in performs it, with a person at the screen who is
already paying that second.

**Code sign-in skips `_maybe_reonboard`.** The chain-wipe repair hangs off
`login` and `google_sign_in`; `AuthKitService` never calls it. On the local
anvil, whose state is wiped on restart while the database persists, whoever
signs in by code stays unfunded. It gets called for rows that are already
onboarded — which is the exact complement of `_finish_onboarding`, and the two
together cover both halves.

**Two concurrent first sign-ins for one new address answer 500.** `EMAIL TEXT
NOT NULL UNIQUE`: both requests miss the lookup, both reach `create_user`, one
takes a `UniqueViolation` to an unhandled 500. Catch it, re-read the row, and
return it — the loser of the race gets the winner's account, which is the right
answer.

## Ordering

Plan 3, in order, and the order matters:

0. **Google credentials in Staging.** Waiting on a person; nothing about the
   redirect can be verified without it, and building it against a double is how
   the verifier went wrong. Blocks step 3 only, so steps 1–2 proceed meanwhile.
1. The five findings. Independent of everything else and each small.
2. Key export by mailed code.
3. Google as a redirect, verified against a real Google round trip in Staging,
   with the claims of a real authorization-code token printed and compared to
   what `AuthKitVerifier` pins.
4. **The cutover, last.** Everything before it is additive and reverts without
   consequence; after it, everyone is signed out.

The cutover must not ship before step 3 works. Cutting over without Google
leaves email as the only door, and a mail outage then locks out everybody —
the one cost the 2026-08-11 spec accepted precisely because Google would remain.

## Waiting on a person

- **Google OAuth credentials**, per environment. In Google Cloud Console, add
  the environment's callback (above) to the client's authorized redirect URIs;
  in WorkOS, enable the Google provider and paste the client id and secret.
  Production takes a **new** OAuth client, not the live one, so the two flows
  cannot break each other during the transition. Staging may reuse an existing
  client — adding a redirect URI is additive and breaks nothing.
- **Rename the WorkOS application** from `skalelabs.com's Application`.
- **Production environment variables on the box**: `WORKOS_API_KEY`,
  `WORKOS_CLIENT_ID`, `WORKOS_AUTHKIT_DOMAIN`, and for the UI build
  `VITE_WORKOS_CLIENT_ID`, `VITE_WORKOS_REDIRECT_URI`. Not `WORKOS_ISSUER` or
  `WORKOS_JWKS_URL` — see above.

## Plan 4 — removal

After the cutover has stood in production long enough to trust: `JwtCoder` and
`JWT_SECRET` as an authentication secret, the `PASSWORD_HASH` column,
`change_password` and its Settings row, `agentpit/auth/passwords.py`, the Google
verifier with the dead `/auth/google`, the bcrypt-hash import in
`migrate_users_to_workos.py`, `has_password` on `UserPublic` and the branch on
it in `SettingsPage`, and the 410 stubs left by plan 3. `GOOGLE_SUB` stops being
read; the column can stay, since an unread column costs nothing and dropping it
is not reversible.

**`passwords.py` has a second consumer, and it is not authentication.**
`liquidity/house_accounts.py` creates each house account with
`hash_password("house-bot-fixed-secret-pw")` while its own comment records that
house accounts never log in over HTTP — they act through `X-API-Key`. The hash
is vestigial, so plan 4 passes `password_hash=None` there rather than keeping
bcrypt alive for it. Missing this turns "delete `passwords.py`" into a broken
liquidity engine, which is the loudest possible way to find out.

While there: `TableWrite.create_user`'s docstring still claims every account has
either a password hash or a `google_sub`. Accounts created by `AuthKitService`
have neither, so the invariant is already gone and the comment is a lie that
plan 4 should correct rather than preserve.

## Out of scope

- MFA, passkeys, enterprise SSO, organizations, the paid Custom Domain add-on.
- Any change to `X-API-Key`, to what a wallet is, or to on-chain onboarding.
- The `api_key` sitting in browser storage. It is a permanent credential and
  deserves a look; that look is not this spec.
- The catalogue churn filter, which is an unrelated stream that will ride along
  with whatever deploy carries this.

## Testing

Backend: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`. **Never
source `.env`** — the conftest setdefaults get defeated and the live-sync tests
flake. The local anvil must be running.

Cases that must hold:

- `X-API-Key` resolves its user after the cutover, without consulting either
  token path. If one test survives this work, it is this one.
- A legacy `JwtCoder` token is refused after the cutover, and `/register`,
  `/login` and `POST /auth/google` answer 410.
- A Google authorization code creates the account, wallet and onboarding on the
  first pass, and lands on the same row on the second.
- A callback whose `state` does not match is refused in the browser and never
  posted.
- An existing Google account (has `GOOGLE_SUB`, no password) signing in through
  the redirect lands on its existing row: same `USER_ID`, same `ETH_ADDRESS`,
  no second onboarding.
- Key export succeeds with a freshly mailed code; fails with a stale one, a
  wrong one, and **a valid code belonging to a different account**.
- Nothing in the **sign-in path** reads `PASSWORD_HASH` after the cutover. The
  column itself is still read on purpose, by `change_password` and by
  `AuthService.login`, and both are covered by tests: they are what makes the
  cutover commit a clean revert, so removing them is plan 4's job, not this
  one's. `link_workos_identity` preserves the hash for the same reason.
- A WorkOS 429 reaches the caller as 429, not 401.
- A six-digit code never appears in a `WorkOsError` message.
- `refresh` never calls the onboarder; `sign_in` does when `ONBOARDED_AT` is
  null.
- Two concurrent first sign-ins for one address produce one account and two
  successful responses.
- No test reaches the network: the WorkOS client is a double throughout.

UI, from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run
build`. `ui/` vitest runs in node with no `@testing-library/react`, so
components cannot be render-tested — the `state` check and the callback's
decisions belong in pure helpers. `tsconfig` has `exactOptionalPropertyTypes`.
`/auth/callback` is a `BrowserRouter` route, so the static host must already
serve `index.html` for unknown paths; it does, since `/markets` works.

Commits carry no `Co-Authored-By` trailer.
