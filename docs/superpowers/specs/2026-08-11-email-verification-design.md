# Email verification at registration — design

**Status:** approved 2026-08-11

## Problem

`AuthService.register` (`auth_service.py:53`) takes an email address entirely on
trust. It hashes the password, writes the `users` row, mints a wallet, runs
on-chain onboarding, and hands back a session — without ever establishing that
the person registering can read the address they typed.

The codebase already knows this. `google_sign_in` clears the password when a
Google identity links to an existing row, and says why (`auth_service.py:108-112`):

> Google verified this address; we never did — registration takes any address on
> trust — so a password already sitting on it is not evidence that whoever set it
> owns the address.

That reasoning is correct and was never carried back to registration itself.

Two things follow from the gap. An address nobody controls can hold an account,
so password reset can never be built on top of it and any mail we send is
undeliverable by construction. And every unverified signup spends money: the
onboarding run is 138,946 gas of `approve` × 2 plus `setApprovalForAll`, free on
a disposable anvil and real once the chain is SKALE on Base.

### There is no way to send mail today

Verified before designing: `requirements.txt` carries no SMTP library and no
mail-provider SDK, nothing under `agentpit/` references SMTP, and production's
`.env` has no mail-related variable. The feature therefore begins with a
delivery channel, not with verification. `httpx` is the HTTP client this
codebase already uses (`liquidity/feed.py:17`), so a provider with an HTTP API
costs no new dependency.

## Design

### Nothing exists until the address answers

A registration that has not been confirmed is not an account. No `users` row, no
wallet, no handle, no on-chain onboarding. It lives in its own table and is
promoted to an account by the confirmation, or expires unnoticed.

```sql
CREATE TABLE pending_registrations (
    EMAIL          TEXT NOT NULL UNIQUE,
    PASSWORD_HASH  TEXT NOT NULL,
    CODE_HASH      TEXT NOT NULL,
    ATTEMPTS       INTEGER NOT NULL DEFAULT 0,
    SENDS          INTEGER NOT NULL DEFAULT 1,
    CREATED_AT     BIGINT NOT NULL,
    EXPIRES_AT     BIGINT NOT NULL,
    LAST_SENT_AT   BIGINT NOT NULL
)
```

Neither secret is stored in the clear. The password is bcrypt-hashed at the
moment it arrives, exactly as `register` hashes it today — a pending row is not a
lesser place to keep it. The code is hashed too: it is a six-digit credential
that grants an account, and a readable column would make a database dump enough
to claim every address waiting in it.

The handle is deliberately absent. Today `register` picks one before the insert;
here it is picked at confirmation, so an abandoned registration cannot squat a
name for anyone who wanted it.

**`users` gains no column.** Not a saving — a consequence. If the check stands
before the row exists, then every existing row is by definition past it. That
buys two things for free: the 17 production accounts need no migration and no
backfill, and there is no `EMAIL_VERIFIED` flag that every future endpoint must
remember to consult. A flag of that shape is only ever as good as the newest
code path that forgot it.

### Three endpoints

**`POST /register`** keeps its request body and its existence check — a taken
address still returns 409, so nothing leaks that did not leak before. It hashes
the password, generates a code, writes the pending row, and sends the mail. It
returns **202 with no token**.

This is the one breaking change to the API contract: the endpoint currently
returns `AuthResponse`. Callers that expect a token from `/register` must be
updated — in this repo that is `ui/src/components/auth/AuthDialog.tsx` and the
auth hook behind it.

**`POST /register/verify {email, code}`** does what `register` used to do once
the code matches: picks a handle, creates the user and wallet, runs
`_onboard_new_account`, deletes the pending row, and returns the same
`AuthResponse` as before. The UI's post-login path is therefore unchanged.

**`POST /register/resend {email}`** issues a **new** code and kills the old one.
Two live codes for one address is a needless second key, and the user who never
found the first mail is not helped by it still working.

Thresholds: a code lives **30 minutes**; **5** wrong attempts kill it and force a
resend; **60 seconds** between sends; at most **5** sends per pending
registration. Since a row lives 30 minutes, the last of those is in practice five
mails per address per half hour, and it is expressed against the row rather than
against a clock because the row is the thing that can hold a counter.

**`/register` against an address that already has a pending row is a resend, not
a new row.** It re-uses the existing row — same `SENDS`, same `LAST_SENT_AT` —
and is refused by the same cooldown and the same cap. Replacing the row instead
would reset both counters, and the send limit would be bypassed by anyone who
called `/register` in a loop rather than `/register/resend`. The password on the
row is updated, because a second registration attempt is where someone corrects
the password they mistyped.

Every one of these fails closed. An expired or exhausted code leaves the pending
row in a state that only a fresh send can move, and when the row's send budget is
gone the address waits for the row to expire.

### Confirmation is what logs you in

The account and the session are created by the same call. A code entered in the
tab where registration started puts the user into the product in that tab —
which is why this is a code and not a link. A link creates the session wherever
the mail was opened: read it on a phone and the desktop tab the user was sitting
in stays empty. The signup surface is a dialog
(`ui/src/components/auth/AuthDialog.tsx`, `dialogMode: "login" | "signup"`), so
the code step is a third mode in a dialog the user never leaves.

A code is also immune to the corporate mail scanners that fetch every link in a
message before the human sees it.

### Google sign-in is untouched

Google verified the address; verifying it again would be theatre. `google_sign_in`
creates its user directly, as it does today, and never touches
`pending_registrations`.

### Sending

One `httpx` POST to Resend's HTTP API, behind a small interface so tests never
reach the network and the provider can be replaced without touching the auth
service.

Resend's free tier is 3,000 emails per month, **100 per day**, one domain. The
daily figure is the binding one — one mail per registration means at most 100
signups a day before sending fails. That is ample for normal traffic and a real
ceiling on a launch day; the Pro tier ($20/mo, 50,000/mo, no daily limit) is a
same-day upgrade and is not worth paying for in advance.

**A failed send must fail the request.** If the mail did not go, the caller gets
an error, not a 202 — otherwise the user waits on an empty inbox believing
something is in flight. The pending row must not be left behind by a failed send
either, or the address is locked out of retrying by its own unique constraint.

Sender is an address on `agentpit.dev`, which requires SPF and DKIM records in
that domain's DNS. That is an operator step, not a code change, and it must be
done before the first send or every message lands in spam.

The message carries the code, its lifetime, and one line saying that if this was
not you, ignore it. That line is accurate rather than polite: no account exists
yet, so ignoring it really is sufficient.

### What this does not fix

Anyone can type a stranger's address and cause us to mail them. The per-address
send cap makes that an annoyance rather than a weapon, but no email verification
scheme removes it — the mail must go to the claimed address to be worth
anything.

## Ordering

1. The sender: the provider client, its interface, its configuration, and a test
   double. Independently testable and blocks everything else.
2. `pending_registrations` and the pure logic over it — code generation, hashing,
   expiry, attempt and send accounting.
3. The three endpoints, and `register` losing its token.
4. The UI: a third dialog mode, the code field, the resend button and its
   cooldown.

Steps 3 and 4 ship together. Between them the product cannot register anyone.

## Out of scope

- Password reset. It becomes buildable once addresses are proven, and it is its
  own feature.
- Re-verifying the 17 existing accounts.
- Any verification of Google-sourced addresses.
- Changing what `/login` does.

## Testing

Backend: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`. Never
source `.env` — the conftest setdefaults get defeated and the live-sync tests
flake. The local anvil must be running.

Cases that must hold:

- The right code creates the user, the wallet, and returns a session; the
  pending row is gone afterwards.
- A wrong code does not create anything and increments `ATTEMPTS`.
- The 5th wrong attempt kills the code; a 6th attempt with the *correct* code
  still fails.
- An expired code fails even when correct.
- Resend issues a different code and the previous one stops working.
- Resend inside the 60-second cooldown is refused.
- The 6th send on one pending registration is refused.
- A send failure returns an error AND leaves no pending row behind.
- Registering an address that already has a confirmed account still returns 409.
- Registering an address that already has a *pending* row re-uses that row: it
  does not raise a unique-constraint error, it does not reset `SENDS` or
  `ATTEMPTS`, it is refused inside the cooldown, and it updates the stored
  password hash.
- `/register` cannot be looped to exceed the send cap that `/register/resend`
  enforces.
- Google sign-in creates its user without any pending row.
- No test reaches the network: the sender is a double throughout.

UI, from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run
build`. `ui/` vitest runs in node with no `@testing-library/react`, so components
cannot be render-tested — the cooldown countdown and the code-input validation
belong in pure helpers. `tsconfig` has `exactOptionalPropertyTypes`.

Commits carry no `Co-Authored-By` trailer.
