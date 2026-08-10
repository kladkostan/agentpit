# Private-key export — design

**Status:** approved 2026-08-10

## Why

agentpit generates a wallet per account and holds its key. When the chain moves
to SKALE on Base, funding an address means buying CREDITS through a portal that
asks you to connect a wallet — and our users cannot, because the key is ours.
Export closes that gap: the account holder can put their own wallet into
MetaMask and top it up.

Independently of the migration, letting someone take the key to a wallet that is
theirs is the right default for a custodial system.

### What this does and does not change

Keys are already stored in plaintext: `users.ETH_PRIVATE_KEY TEXT NOT NULL
UNIQUE`, written from `Account.create()` + `Web3.to_hex` at signup. Export
therefore does not weaken our storage posture — anyone with database access can
already read every key. What changes is the **user's** exposure: after export
they can be phished, and we can no longer assume we are the only holder.

Nothing exposes the key today. Verified by grep across `agentpit/api/routes/`
and `agentpit/datastructures/`.

## The endpoint

`POST /account/private-key`. Never GET — a key in a URL lands in proxy logs,
browser history and `Referer`.

The body carries exactly one factor, chosen by what the account has:

| account | factor | verified with |
| --- | --- | --- |
| has `password_hash` (7 of 17 on production) | `password` | `verify_password`, the same call `change_password` already uses |
| `password_hash IS NULL` — Google-only (10 of 17) | `google_credential` | `self._google.verify(credential)` |

**For the Google path, a valid token is not enough.** The `sub` it returns must
equal the `google_sub` stored on the account. Accepting any valid Google token
would hand this account's key to whoever signed in last.

An account is offered only the factor it has. Supplying the wrong one is a 400,
not a fallback.

Response: `{ private_key, eth_address }`, with `Cache-Control: no-store`.

### Rules the implementation must hold

- The key never enters the session `user` payload. The API-key row in Settings
  reads its secret straight off that object; a private key must not travel that
  way, or every page load ships it to the browser.
- Never logged — including the exception path, which must not echo the request
  body into a traceback.
- Rate-limited. Guessing a password here must be no easier than at login, and
  the prize is larger: not a session that can be revoked, but a key that cannot.

## What we record, and what follows from it

`users.KEY_EXPORTED_AT` — a nullable timestamp, set on first successful export.

It exists for one operational reason beyond support questions: **an account that
has exported its key never receives a gas re-grant again.**

`_maybe_reonboard` (`auth_service.py:204`) re-grants the signup gas to any
account whose native balance has hit zero. While we hold the key, a user cannot
empty their own wallet, so the only way to reach zero is a chain wipe — which is
what that code is for. Once they hold the key they can empty it deliberately,
and every login becomes another free grant. On production that is $0.25 a turn.

The existing `simulated_chain` flag already gates this and must be `False` on a
durable chain. The export check is a second, narrower lock that does not depend
on remembering to set a flag.

## The interface

A button in the **Address** row of `SettingsPage.tsx`, on the right, matching the
`Edit` and `Change` buttons already in that card. Under the address, one line
naming the purpose:

```
Address
0x933B442e9A78e3C3a567B86ee595Eb9BcEb15215        [ Export private key ]
Import it into MetaMask to fund this wallet.
```

The button is labelled for what it does — the key leaves us — while the line
below says what it is for. Calling the button "Import" would name an action it
does not perform; the importing happens in MetaMask.

Clicking opens a dialog:

1. The warning, stated plainly, no drama:
   **"Anyone with this key controls the wallet and everything in it. We cannot
   undo an export or move the funds back."**
2. The factor the account has — a password field, or the Google button.
3. On success the key appears once, monospace, with copy-to-clipboard reusing
   the `navigator.clipboard` + `toast` idiom already in `ApiKeyRow`.

Closing the dialog drops the key from component state. Seeing it again means
re-authenticating; there is no "reveal" toggle holding it in memory, which is
exactly where this differs from the API-key row.

## Testing

The one that matters most: **a valid Google token belonging to a different
`sub` gets 401, not a key.**

Alongside it: right password returns the key; wrong password 401; the wrong
factor for the account type 400; the key is absent from every other API
response that carries the user; `KEY_EXPORTED_AT` is set on success and left
alone on failure; an account with `KEY_EXPORTED_AT` set receives no gas
re-grant from `_maybe_reonboard`.

Backend: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain` (never
source `.env`; the local anvil must be running). UI, from `ui/`:
`npx vitest run && npm run typecheck && npm run lint && npm run build`. Note
`ui/` vitest runs in a node environment with no `@testing-library/react`, so the
dialog cannot be render-tested — any decision worth testing belongs in a pure
helper.

## Out of scope

- **Importing an external key into agentpit.** The reverse direction is a
  different feature with product questions this spec does not answer: what
  happens to the balance and open positions on the old address, whether the
  account's address changes, and whether we should hold the key to a wallet
  that may contain a user's real money.
- Encrypting keys at rest. Worth doing, unrelated to this, and it would not
  change any decision here.
- Rotating a key, or revoking one after export. Once a key is out it is out;
  the honest answer is the warning text, not a button.
