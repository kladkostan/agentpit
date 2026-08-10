# Private-Key Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an account holder take the private key of the wallet agentpit generated for them, so they can import it into MetaMask and fund it.

**Architecture:** One re-authenticated POST endpoint that returns the key and stamps the account as exported. The stamp is load-bearing, not bookkeeping: an exported account stops receiving gas re-grants. The UI is a button in the Address row that opens a dialog and shows the key once.

**Tech Stack:** Python 3.13, FastAPI, psycopg3 + Postgres, pytest; Vite/React 18/TS, vitest.

## Global Constraints

- **The key never enters the session payload.** `UserPublic` (`agentpit/datastructures/auth_response.py`) is a whitelist that excludes `eth_key`; it must stay that way. The key travels only in the response of the endpoint below.
- **POST only.** A key in a URL lands in proxy logs, browser history and `Referer`.
- **Never logged**, including the exception path — no request body in a traceback.
- The response carries `Cache-Control: no-store`.
- Exactly one factor per account, decided by what the account has: `password` when `PASSWORD_HASH` is set (7 of 17 accounts on production), `google_credential` when it is NULL (10 of 17). Supplying the wrong one is a 400, never a fallback to the other.
- **For the Google path a valid token is not enough — its `sub` must belong to THIS account.** Accepting any valid Google token hands this account's key to whoever signed in last. This is the single most dangerous path in the feature.
- `InvalidCredentialsError` → 401 and `BusinessRuleError` → 400 are already wired in `agentpit/api/exception_handlers.py`; use them rather than raising `HTTPException`.
- Keys are already plaintext at rest (`users.ETH_PRIVATE_KEY`); this feature does not change that and must not be read as making it acceptable.
- Backend tests: `cd /Users/yavorsky/dev/agentpit && .venv/bin/python -m pytest tests -q --ignore=tests/onchain`. NEVER source `.env` — `tests/conftest.py` uses `os.environ.setdefault` and a sourced `.env` defeats every default. The local anvil must be running.
- UI checks, from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`. `ui/` vitest runs in **node** with no `@testing-library/react` — components cannot be render-tested.
- `tsconfig` sets `exactOptionalPropertyTypes` — optional props need `foo?: T | undefined`.
- Commit messages must NOT carry a `Co-Authored-By` trailer. Commit on branch `mvp`.

## File Structure

| File | Responsibility |
| --- | --- |
| `agentpit/db/table_create.py` | Two new nullable columns on `users`. |
| `agentpit/db/table_read.py` / `table_write.py` | Read/stamp them. |
| `agentpit/services/auth_service.py` | `export_private_key`, and the re-grant lock in `_maybe_reonboard`. |
| `agentpit/datastructures/private_key_request.py` (new) | Request + response wire shapes. |
| `agentpit/api/routes/users.py` | `POST /me/private-key`. |
| `tests/api/test_private_key_export.py` (new) | Every path, including the wrong-`sub` one. |
| `ui/src/api/auth.ts` | `exportPrivateKeyRequest`. |
| `ui/src/pages/SettingsPage.tsx` | The button and the dialog. |

---

### Task 1: The endpoint

**Files:**
- Modify: `agentpit/db/table_create.py` (`_migrate_users_table`, the `additions` list ~line 173)
- Modify: `agentpit/db/table_read.py`, `agentpit/db/table_write.py`
- Modify: `agentpit/services/auth_service.py` (add `export_private_key`; edit `_maybe_reonboard` ~line 204)
- Create: `agentpit/datastructures/private_key_request.py`
- Modify: `agentpit/api/routes/users.py`
- Test: `tests/api/test_private_key_export.py`

**Interfaces:**
- Produces: `AuthService.export_private_key(*, user_id: str, password: str | None = None, google_credential: str | None = None) -> str` — returns the `0x`-prefixed key.
- Produces: `TableRead.get_key_export_state(db, user_id) -> tuple[int | None, int | None]` — `(exported_at, last_attempt_at)`, both epoch seconds or None.
- Produces: `TableWrite.mark_key_export_attempt(db, user_id, at: int) -> bool` and `TableWrite.mark_key_exported(db, user_id, at: int) -> bool`.
- Produces: `POST /me/private-key`, body `PrivateKeyRequest`, response `PrivateKeyResponse`.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_private_key_export.py`. Follow the neighbouring API tests for how they build a client and register a user — read one first and match it:

```python
"""Taking the key to a wallet that is yours.

agentpit generates the wallet and holds its key. Export is what lets the
account holder put it in MetaMask and fund it. The dangerous path is the
Google one: a valid token proves somebody signed in, not that THIS account's
owner did.
"""

from __future__ import annotations

from unittest.mock import patch

from agentpit.auth.google import GoogleIdentity


def test_a_password_account_exports_with_its_password(client, registered_user):
    r = client.post(
        "/me/private-key",
        json={"password": registered_user.password},
        headers=registered_user.auth_header,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["private_key"].startswith("0x")
    assert len(body["private_key"]) == 66
    assert body["eth_address"] == registered_user.eth_address


def test_a_wrong_password_is_rejected(client, registered_user):
    r = client.post(
        "/me/private-key",
        json={"password": "not-the-password"},
        headers=registered_user.auth_header,
    )
    assert r.status_code == 401
    assert "private_key" not in r.text


def test_a_password_account_cannot_use_the_google_door(client, registered_user):
    r = client.post(
        "/me/private-key",
        json={"google_credential": "anything"},
        headers=registered_user.auth_header,
    )
    assert r.status_code == 400
    assert "private_key" not in r.text


def test_a_google_token_for_a_DIFFERENT_account_gets_nothing(
    client, google_user, other_google_sub
):
    """The one that matters. A valid Google token proves somebody signed in;
    it must also be THIS account's identity, or the key goes to whoever
    authenticated last."""
    with patch(
        "agentpit.auth.google.GoogleTokenVerifier.verify",
        return_value=GoogleIdentity(sub=other_google_sub, email="someone@else.com"),
    ):
        r = client.post(
            "/me/private-key",
            json={"google_credential": "a-valid-token-for-someone-else"},
            headers=google_user.auth_header,
        )
    assert r.status_code == 401
    assert "private_key" not in r.text


def test_a_google_account_exports_with_its_own_token(client, google_user):
    with patch(
        "agentpit.auth.google.GoogleTokenVerifier.verify",
        return_value=GoogleIdentity(sub=google_user.google_sub, email=google_user.email),
    ):
        r = client.post(
            "/me/private-key",
            json={"google_credential": "a-valid-token"},
            headers=google_user.auth_header,
        )
    assert r.status_code == 200
    assert r.json()["private_key"].startswith("0x")


def test_the_key_is_absent_from_every_other_response(client, registered_user):
    """UserPublic is a whitelist and must stay one."""
    r = client.get("/me", headers=registered_user.auth_header)
    assert r.status_code == 200
    assert "private_key" not in r.text
    assert "eth_key" not in r.text


def test_a_successful_export_is_stamped(client, registered_user, db_conn):
    client.post(
        "/me/private-key",
        json={"password": registered_user.password},
        headers=registered_user.auth_header,
    )
    row = db_conn.execute(
        "SELECT KEY_EXPORTED_AT FROM users WHERE USER_ID = %s",
        (registered_user.user_id,),
    ).fetchone()
    assert row["KEY_EXPORTED_AT"] is not None


def test_the_response_is_not_cacheable(client, registered_user):
    r = client.post(
        "/me/private-key",
        json={"password": registered_user.password},
        headers=registered_user.auth_header,
    )
    assert r.headers.get("cache-control") == "no-store"
```

The fixtures `client`, `registered_user`, `google_user`, `other_google_sub` and `db_conn` may not exist under these names. Read the existing API tests and use whatever they provide; adapt these tests to that shape rather than inventing a parallel fixture set. If a Google-account fixture genuinely does not exist, add one next to the existing ones.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/test_private_key_export.py -q`
Expected: FAIL — 404, the route does not exist.

- [ ] **Step 3: Add the two columns**

In `agentpit/db/table_create.py`, `_migrate_users_table`, append to the `additions` list:

```python
            ("KEY_EXPORTED_AT", "BIGINT"),
            ("KEY_EXPORT_ATTEMPT_AT", "BIGINT"),
```

Both nullable, both additive — the list is already an idempotent `ADD COLUMN IF NOT EXISTS` loop.

- [ ] **Step 4: Read and write them**

In `agentpit/db/table_read.py`, beside the other user readers:

```python
    @staticmethod
    def get_key_export_state(
        db: psycopg.Connection, user_id: str
    ) -> "tuple[int | None, int | None]":
        """`(exported_at, last_attempt_at)` for one user, epoch seconds."""
        row = db.execute(
            "SELECT KEY_EXPORTED_AT, KEY_EXPORT_ATTEMPT_AT FROM users "
            "WHERE USER_ID = %s",
            (user_id,),
        ).fetchone()
        if row is None:
            return (None, None)
        exported = row["KEY_EXPORTED_AT"]
        attempted = row["KEY_EXPORT_ATTEMPT_AT"]
        return (
            int(exported) if exported is not None else None,
            int(attempted) if attempted is not None else None,
        )
```

In `agentpit/db/table_write.py`, matching `update_user_password_hash`'s shape:

```python
    @staticmethod
    def mark_key_export_attempt(
        db: psycopg.Connection, user_id: str, at: int
    ) -> bool:
        cur = db.execute(
            "UPDATE users SET KEY_EXPORT_ATTEMPT_AT = %s WHERE USER_ID = %s",
            (at, user_id),
        )
        return cur.rowcount > 0

    @staticmethod
    def mark_key_exported(db: psycopg.Connection, user_id: str, at: int) -> bool:
        """First export only — a later one must not move the stamp, or the
        re-grant lock would appear to lapse."""
        cur = db.execute(
            "UPDATE users SET KEY_EXPORTED_AT = %s "
            "WHERE USER_ID = %s AND KEY_EXPORTED_AT IS NULL",
            (at, user_id),
        )
        return cur.rowcount > 0
```

- [ ] **Step 5: The service method**

In `agentpit/services/auth_service.py`, beside `change_password`:

```python
    #: Seconds between export attempts on one account. This endpoint sits
    #: behind an authenticated session, so an attacker needs the session
    #: before they can guess at all — but the prize is a key that cannot be
    #: revoked, unlike the session itself, so online guessing gets a floor.
    #: The project has no rate limiting anywhere else, including /login.
    KEY_EXPORT_COOLDOWN_S = 5

    def export_private_key(
        self,
        *,
        user_id: str,
        password: str | None = None,
        google_credential: str | None = None,
    ) -> str:
        """The account's own private key, after proving it is the account.

        Exactly one factor, chosen by what the account HAS rather than by what
        the caller offers: a password account cannot authenticate with a Google
        token and a Google account has no password to give.
        """
        now = int(time.time())
        with self._db.write() as conn:
            user = TableRead.get_user_by_userid(conn, user_id)
            if user is None:
                raise UserNotFoundError()
            _, last_attempt = TableRead.get_key_export_state(conn, user_id)
            if last_attempt is not None and now - last_attempt < self.KEY_EXPORT_COOLDOWN_S:
                raise BusinessRuleError("too many attempts — wait a moment")
            TableWrite.mark_key_export_attempt(conn, user_id, now)

            password_hash = TableRead.get_password_hash_by_userid(conn, user_id)
            if password_hash is not None:
                if password is None:
                    raise BusinessRuleError("this account exports with its password")
                if not verify_password(password, password_hash):
                    raise InvalidCredentialsError("invalid password")
            else:
                if google_credential is None:
                    raise BusinessRuleError("this account exports with Google")
                if self._google is None:
                    raise FeatureDisabledError("Google sign-in is not configured")
                identity = self._google.verify(google_credential)
                owner = TableRead.get_user_by_google_sub(conn, identity.sub)
                # A valid token proves somebody signed in with Google. It has
                # to be THIS account's Google identity, or the key goes to
                # whoever authenticated last.
                if owner is None or owner.user_id != user_id:
                    raise InvalidCredentialsError("that Google account is not this one")

            TableWrite.mark_key_exported(conn, user_id, now)
        return Web3.to_hex(user.eth_key.key)
```

Add `import time` and `from web3 import Web3` if they are not already imported in that module — check first. `BusinessRuleError`, `InvalidCredentialsError`, `FeatureDisabledError` and `UserNotFoundError` are already imported there for the other methods; confirm rather than assume.

Note the cooldown is stamped BEFORE the factor is checked, so a wrong password costs the same wait as a right one.

- [ ] **Step 6: Lock the re-grant**

In `_maybe_reonboard`, before it re-grants, skip an account that has exported:

```python
        with self._db.read() as conn:
            exported_at, _ = TableRead.get_key_export_state(conn, user.user_id)
        if exported_at is not None:
            # While we hold the key the only way to a zero balance is a chain
            # wipe, which is what this repair is for. Once the holder has the
            # key they can empty the wallet deliberately, and every login would
            # be another free grant.
            return
```

Place it beside the existing `simulated_chain` guard and extend that method's docstring with one sentence naming this second lock. Read the method first — the guard's exact position matters, and it must run before any chain read.

- [ ] **Step 7: The wire shapes and the route**

Create `agentpit/datastructures/private_key_request.py`:

```python
from pydantic import BaseModel


class PrivateKeyRequest(BaseModel):
    """Exactly one of these, matching how the account signs in."""

    password: str | None = None
    google_credential: str | None = None


class PrivateKeyResponse(BaseModel):
    private_key: str
    eth_address: str
```

The dialog in Task 2 has to know which factor to show, and inferring it
client-side would be guesswork. Add one field to `UserPublic` in
`agentpit/datastructures/auth_response.py`:

```python
    has_password: bool
```

It leaks nothing — it says how you sign in, which you already know — and it
keeps `UserPublic` a whitelist. Populate it wherever `UserPublic` is built from
a user record: `has_password` is `PASSWORD_HASH IS NOT NULL`. `User` does not
carry the hash, so this needs the value threading through — read how
`UserPublic.model_validate(user.model_dump())` is called in `users.py` and in
`auth_service._issue`, and add the field at each construction site rather than
inventing a second path. Add a test that a Google account reports
`has_password: false` and a password account `true`.

In `agentpit/api/routes/users.py`, beside `update_me_password`:

```python
@router.post("/me/private-key", response_model=PrivateKeyResponse)
def export_me_private_key(
    payload: PrivateKeyRequest,
    user: CurrentUserDep,
    service: AuthServiceDep,
    response: Response,
) -> PrivateKeyResponse:
    """The account's own wallet key, to import into a wallet app.

    POST rather than GET on purpose: a key in a URL lands in proxy logs,
    browser history and the Referer header.
    """
    key = service.export_private_key(
        user_id=user.user_id,
        password=payload.password,
        google_credential=payload.google_credential,
    )
    response.headers["Cache-Control"] = "no-store"
    return PrivateKeyResponse(private_key=key, eth_address=user.eth_address)
```

Import `Response` from `fastapi` and the two new models. Do not add any logging to this route.

- [ ] **Step 8: Run the tests**

Run: `.venv/bin/python -m pytest tests/api/test_private_key_export.py -q`
Expected: PASS.

Then the full suite: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
Expected: PASS. If an existing test asserts `_maybe_reonboard` re-grants, read whether its fixture has an export stamp before touching it.

- [ ] **Step 9: Commit**

```bash
git add agentpit/db/table_create.py agentpit/db/table_read.py \
        agentpit/db/table_write.py agentpit/services/auth_service.py \
        agentpit/datastructures/private_key_request.py \
        agentpit/api/routes/users.py tests/api/test_private_key_export.py
git commit -m "feat(account): export the wallet key you already own"
```

---

### Task 2: The button in the Address row

**Files:**
- Modify: `ui/src/api/auth.ts`
- Modify: `ui/src/pages/SettingsPage.tsx` (the Address row ~lines 34-45)
- Test: `ui/src/api/auth.test.ts` if one exists; otherwise no new test file — see below.

**Interfaces:**
- Consumes: `POST /me/private-key` from Task 1.
- Produces: `exportPrivateKeyRequest(factor: { password: string } | { googleCredential: string }): Promise<{ private_key: string; eth_address: string }>`.

**On testing:** `ui/` vitest runs in node with no `@testing-library/react`, so the dialog cannot be render-tested. There is no pure decision worth extracting here — the component is a form and a fetch. Cover the request shape if `ui/src/api/auth.ts` already has a test file; otherwise the four UI checks are the gate. Do not invent a testing framework for this.

- [ ] **Step 1: The API call**

In `ui/src/api/auth.ts`, beside `changePasswordRequest`:

```ts
export function exportPrivateKeyRequest(
  factor: { password: string } | { googleCredential: string },
): Promise<{ private_key: string; eth_address: string }> {
  const body =
    "password" in factor
      ? { password: factor.password }
      : { google_credential: factor.googleCredential };
  return apiFetch<{ private_key: string; eth_address: string }>(
    "/me/private-key",
    { method: "POST", body: JSON.stringify(body) },
  );
}
```

- [ ] **Step 2: The row**

In `ui/src/pages/SettingsPage.tsx`, the Address row currently renders the icon, the label and the address. Add the button on the right and one line of purpose beneath the address, so the row becomes:

```tsx
            <div className="flex items-center gap-4 border-b p-4">
              <Lock className="size-5 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">Address</p>
                <p className="break-all font-mono text-sm text-muted-foreground">
                  {user.eth_address}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Import it into MetaMask to fund this wallet.
                </p>
              </div>
              <ExportKeyButton />
            </div>
```

- [ ] **Step 3: The dialog**

Add an `ExportKeyButton` component in the same file, beside `ChangePasswordRow`, using `@/components/ui/dialog` (it exists) and following `ChangePasswordRow`'s state style — `useState` for the form, `ApiError` for the failure message, `toast` for success.

Behaviour, in order:

1. A `Button variant="outline"` labelled `Export private key` opens the dialog.
2. The dialog opens on the warning, verbatim: **"Anyone with this key controls the wallet and everything in it. We cannot undo an export or move the funds back."**
3. Below it, one factor. `useAuth()` exposes the session user; an account with no password shows `GoogleSignInButton` from `@/components/auth/GoogleSignInButton` (its `onCredential` hands you the token), otherwise a password `Input` of `type="password"`. Task 1 adds `has_password: boolean` to `UserPublic` for exactly this; read it off the session user. If it is missing, Task 1 is incomplete — stop and say so rather than inferring.
4. On success the key replaces the form: monospace, `break-all`, with a copy button reusing `navigator.clipboard.writeText` + `toast.success` exactly as `ApiKeyRow` does.
5. Closing the dialog resets every piece of state, the key included. There is no reveal toggle and no caching — seeing it again means re-authenticating. This is deliberately unlike `ApiKeyRow`, which holds its secret in memory because the session already carries it.

- [ ] **Step 4: Run every UI check**

Run, from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`
Expected: all four pass.

- [ ] **Step 5: Commit**

```bash
git add ui/src/api/auth.ts ui/src/pages/SettingsPage.tsx
git commit -m "feat(settings): take your wallet key to MetaMask"
```

---

## Self-Review

**Spec coverage.** Spec "the endpoint" → Task 1 Steps 5-7, including POST-only, the one-factor rule and `no-store`. Spec's `sub`-must-match requirement → Step 5's `owner.user_id != user_id` check and the test named for it. Spec "what we record, and what follows" → Steps 3-4 and 6, with the re-grant lock as its own step because it is the reason the column exists. Spec "the interface" → Task 2. Spec's rate-limiting line → the cooldown in Step 5, sized honestly: the project has no rate limiting anywhere, so this is a floor for one endpoint, not a framework.

**Placeholders.** None. Every code step carries the code. Task 1 Step 1 tells the implementer to adapt fixture names to what the test suite actually provides rather than inventing a parallel set — that is an instruction with a named method, not a deferred decision.

**Type consistency.** `export_private_key`'s keyword names (`user_id`, `password`, `google_credential`) are identical in the service (Step 5), the route (Step 7) and the request model. `get_key_export_state` returns `(exported_at, last_attempt_at)` and both call sites unpack it in that order. `PrivateKeyResponse`'s two fields match the TS return type in Task 2 Step 1 and the assertions in Step 1's tests.

**A cross-task dependency, resolved rather than noted.** The dialog has to know whether the account has a password, and inferring it client-side would be guesswork. That is a Task 1 change discovered while writing Task 2, so it is now written INTO Task 1 Step 7 with its own test, not left as a warning for the Task 2 implementer to trip over.
