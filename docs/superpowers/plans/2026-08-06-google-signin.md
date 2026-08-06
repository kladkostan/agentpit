# Continue with Google — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a visitor create an agentpit account, or sign into the one they
already have, with a Google account instead of inventing a password.

**Architecture:** Google Identity Services renders the button in the browser and
returns an **ID token** (a JWT signed by Google). The front end posts it to
`POST /auth/google`; the backend verifies it locally against Google's JWKS and
answers with the same token-plus-user record that `register` and `login` return.
A new Google account is onboarded by the *same* routine a password signup runs —
extracted from `AuthService.register` so the two paths cannot drift.

**Tech Stack:** FastAPI · psycopg 3 / Postgres · PyJWT 2.12 + `cryptography`
(new) · React 18 + TypeScript + Vite · vitest

**Spec:** `docs/superpowers/specs/2026-08-06-google-signin-design.md`

## Global Constraints

- The five checks on every token, all required: **signature** against the JWKS
  key named by `kid`; **`iss`** ∈ `{accounts.google.com,
  https://accounts.google.com}`; **`aud`** == the configured client id;
  **`exp`** not passed; **`email_verified` is `true`**.
- Verification is **local against Google's JWKS**. Never call Google's
  `tokeninfo` endpoint.
- **One verified email is one account.** A Google identity whose verified email
  matches an existing row links to that row; it never creates a second.
- Lookup order on sign-in: **`google_sub` first, then email.**
- `users.PASSWORD_HASH` becomes **nullable**; `users.GOOGLE_SUB TEXT` is new and
  **unique**.
- **Both signup paths run one onboarding routine**, not two copies.
- **Off unless configured:** no `GOOGLE_CLIENT_ID` → the button does not render
  and `POST /auth/google` answers **503**, parsing no token.
- No set-password and no password-reset for Google accounts — out of scope.
- Backend tests: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`
  from the repo root. **NEVER source `.env` into pytest** — `conftest.py`'s
  `setdefault` calls are what keep the suite off live sync and the leaderboard
  timer, and an exported `.env` defeats every one of them.
- Anvil + the deployed exchange must be running: every `/register` in the suite
  hits the faucet and grants approvals for real.
- UI checks, from `ui/`: `npx vitest run && npm run typecheck && npm run lint &&
  npm run build`. Vitest runs in the **node** environment with no
  `@testing-library/react` — UI tests cover pure functions, not rendered
  components. Do not add test dependencies.
- Commit messages carry **no `Co-Authored-By` trailer and no AI attribution**.
- **Never `git add -A` or `git add .`** — stage the named files only.
- No secret is ever committed or printed. A Google *client id* is public by
  design and is not a secret; there is no client secret in this flow.

### The one deliberate departure from the spec

Spec §1 says the endpoint answers "the same `AuthResponse`". This plan has
`POST /auth/google` answer a **subclass**, `GoogleAuthResponse`, which adds one
field: `created: bool`. `register` and `login` are untouched.

The reason: on the password path the welcome toast ("your wallet is funded") is
how a new user learns they have money to trade with, and the Google path cannot
tell a first sign-in from a returning one without it. The alternatives were to
drop the toast for Google users or to guess from `created_at`. Nothing
downstream of authentication changes, which is what §1 is protecting.

---

## File Structure

**Backend — new**

- `agentpit/auth/google.py` — `GoogleIdentity`, `GoogleTokenVerifier`. Knows
  Google's JWKS and the five checks. Knows nothing about users or the database.
- `agentpit/datastructures/google_auth_request.py` — the request body.

**Backend — modified**

- `requirements.txt` — adds `cryptography` (PyJWT needs it for RS256).
- `agentpit/config.py` — `google_client_id`.
- `agentpit/domain/exceptions.py` — `FeatureDisabledError`.
- `agentpit/api/exception_handlers.py` — maps it to 503.
- `agentpit/datastructures/auth_response.py` — `GoogleAuthResponse`.
- `agentpit/db/table_create.py` — `GOOGLE_SUB`, nullable `PASSWORD_HASH`.
- `agentpit/db/table_read.py` — `get_user_by_google_sub`, `get_user_by_email_ci`.
- `agentpit/db/table_write.py` — `create_user(google_sub=…)`, `set_google_sub`.
- `agentpit/services/auth_service.py` — `google_sign_in`, the extracted
  `_onboard_new_account`, and the two "this account signs in with Google"
  messages.
- `agentpit/api/deps.py`, `agentpit/api/app.py`, `agentpit/api/routes/auth.py` —
  wiring.

**Front end — new**

- `ui/src/lib/googleAuth.ts` — client-id read + the GIS script loader. Pure
  enough to test in the node environment.
- `ui/src/lib/googleAuth.test.ts`
- `ui/src/components/auth/GoogleSignInButton.tsx` — the GIS button. DOM glue.
- `ui/src/auth/welcomeToast.tsx` — the funded-wallet toast, extracted so both
  signup paths raise the same one.

**Front end — modified**

- `ui/src/api/auth.ts`, `ui/src/auth/context.ts`, `ui/src/auth/AuthContext.tsx`,
  `ui/src/components/auth/AuthDialog.tsx`, `ui/src/vite-env.d.ts`.

**Deploy**

- `ui/.env.example`, `.env.example`, `deploy/Dockerfile.ui`,
  `deploy/docker-compose.prod.yml`, `deploy/env.prod.example`.

**Branch:** create `google-signin` from the current `main`
(`4b27a5e`, which holds the spec) before Task 1. Do not commit to `main` or
`mvp` during execution.

---

### Task 1: The token verifier

Everything that decides whether a Google credential is genuine, with no
knowledge of accounts. It is the piece worth testing hardest, and it can be
tested completely offline by minting tokens with a locally generated key.

**Files:**
- Modify: `requirements.txt`
- Create: `agentpit/auth/google.py`
- Test: `tests/test_google_verifier.py`

**Interfaces:**
- Consumes: `InvalidCredentialsError` from `agentpit.domain.exceptions`.
- Produces:
  - `GoogleIdentity` — frozen dataclass, fields `sub: str`, `email: str`
  - `GoogleTokenVerifier(client_id: str, jwk_client=None)` with
    `verify(credential: str) -> GoogleIdentity`, raising `InvalidCredentialsError`
    on every failure
  - module constants `GOOGLE_JWKS_URI`, `GOOGLE_ISSUERS`

- [ ] **Step 1: Add the dependency and install it**

PyJWT is already installed (2.12.1) but cannot verify RS256 without
`cryptography`, which is not present. Append to `requirements.txt`, after the
`pyjwt` line:

```
cryptography>=42,<47
```

Run:

```bash
.venv/bin/python -m pip install 'cryptography>=42,<47'
.venv/bin/python -c "import cryptography; print(cryptography.__version__)"
```

Expected: a version number, no traceback.

- [ ] **Step 2: Write the failing test**

Create `tests/test_google_verifier.py`:

```python
"""The five checks on a Google ID token, each asserted on its own.

No network: the test mints its own RS256 tokens with a locally generated key
and hands the verifier a stub JWKS client that returns the matching public key.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from agentpit.auth.google import GOOGLE_ISSUERS, GoogleIdentity, GoogleTokenVerifier
from agentpit.domain.exceptions import InvalidCredentialsError

CLIENT_ID = "1234567890-agentpit.apps.googleusercontent.com"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _StubJwkClient:
    """Stands in for PyJWKClient — hands back one fixed public key."""

    class _Key:
        def __init__(self, key):
            self.key = key

    def __init__(self, public_key):
        self._key = self._Key(public_key)

    def get_signing_key_from_jwt(self, token):
        return self._key


def _verifier(client_id: str = CLIENT_ID) -> GoogleTokenVerifier:
    return GoogleTokenVerifier(client_id, jwk_client=_StubJwkClient(_KEY.public_key()))


def _token(key=_KEY, **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "108176612345678901234",
        "email": "user@example.com",
        "email_verified": True,
        "iat": now,
        "exp": now + 600,
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256")


def test_accepts_a_well_formed_token():
    identity = _verifier().verify(_token())
    assert identity == GoogleIdentity(
        sub="108176612345678901234", email="user@example.com"
    )


def test_rejects_a_token_signed_by_another_key():
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(_token(key=_OTHER_KEY))


def test_rejects_a_token_minted_for_another_client():
    """The check that stops a token issued to a different site being replayed
    at ours. The signature is Google's and valid — only `aud` differs."""
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(_token(aud="9999-someone-else.apps.googleusercontent.com"))


def test_rejects_a_token_from_another_issuer():
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(_token(iss="https://accounts.evil.example"))


def test_accepts_both_issuer_spellings():
    """Google mints `accounts.google.com` and `https://accounts.google.com`."""
    for issuer in GOOGLE_ISSUERS:
        assert _verifier().verify(_token(iss=issuer)).sub == "108176612345678901234"


def test_rejects_an_expired_token():
    now = int(time.time())
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(_token(iat=now - 7200, exp=now - 3600))


def test_rejects_an_unverified_email():
    """Load-bearing, not ceremonial: a verified email is what makes linking a
    Google identity to an existing account by address safe."""
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(_token(email_verified=False))


def test_rejects_a_missing_email_verified_claim():
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(_token(email_verified=None))


def test_rejects_a_token_with_no_email():
    """Minted without the claim rather than with it blanked, so `require` is
    what does the rejecting."""
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": CLIENT_ID,
            "sub": "108176612345678901234",
            "email_verified": True,
            "iat": now,
            "exp": now + 600,
        },
        _KEY,
        algorithm="RS256",
    )
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(token)


def test_rejects_garbage():
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify("not.a.jwt")
```

- [ ] **Step 3: Run the test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_google_verifier.py -q
```

Expected: collection error — `ModuleNotFoundError: No module named
'agentpit.auth.google'`.

- [ ] **Step 4: Write the verifier**

Create `agentpit/auth/google.py`:

```python
"""Verification of Google Identity Services ID tokens.

The credential the browser hands us is a JWT signed by Google. It is verified
locally against Google's published JWKS rather than by calling the `tokeninfo`
endpoint: that keeps a network round trip — and its failure mode — out of the
moment somebody is signing up, and local verification is what Google
recommends for production.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

from agentpit.domain.exceptions import InvalidCredentialsError

GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"

# Google mints both spellings; a token carrying either is genuine.
GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})


@dataclass(frozen=True)
class GoogleIdentity:
    """The two claims we act on, once every check has passed."""

    sub: str
    email: str


class GoogleTokenVerifier:
    """Checks a Google ID token and returns who it says signed in.

    `jwk_client` exists so tests can supply a key without reaching the network;
    production leaves it unset and gets the caching JWKS client.
    """

    def __init__(self, client_id: str, jwk_client=None):
        self._client_id = client_id
        # Keys are cached: Google rotates them slowly, and fetching per
        # sign-in would put their availability in front of ours.
        self._jwk_client = (
            jwk_client
            if jwk_client is not None
            else PyJWKClient(GOOGLE_JWKS_URI, cache_keys=True)
        )

    def verify(self, credential: str) -> GoogleIdentity:
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(credential)
            claims = jwt.decode(
                credential,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._client_id,
                issuer=GOOGLE_ISSUERS,
                options={"require": ["exp", "iss", "aud", "sub", "email"]},
            )
        except Exception as exc:
            # Bad signature, wrong audience, expired, malformed — to the caller
            # they are one thing: this credential proves nothing. The reason
            # stays in the traceback, not in the response.
            raise InvalidCredentialsError("invalid Google credential") from exc

        # Checked after the signature rather than alongside it: `email_verified`
        # is what makes linking by address safe, so it has to be a claim Google
        # actually signed, not one we read off an unverified token.
        if claims.get("email_verified") is not True:
            raise InvalidCredentialsError("Google account email is not verified")

        return GoogleIdentity(sub=str(claims["sub"]), email=str(claims["email"]))
```

- [ ] **Step 5: Run the test to verify it passes**

Run:

```bash
.venv/bin/python -m pytest tests/test_google_verifier.py -q
```

Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt agentpit/auth/google.py tests/test_google_verifier.py
git commit -m "feat(auth): verify google id tokens against the jwks"
```

---

### Task 2: The database's side of a Google identity

`GOOGLE_SUB` on `users`, a `PASSWORD_HASH` that is allowed to be absent, and the
two lookups the service needs.

**Files:**
- Modify: `agentpit/db/table_create.py:98-140`
- Modify: `agentpit/db/table_read.py` (add after `get_user_by_email`, ~line 235)
- Modify: `agentpit/db/table_write.py:19-56` and after
  `update_user_password_hash`
- Test: `tests/db/test_google_identity.py`

**Interfaces:**
- Consumes: `fresh_test_conn()` from `tests.db_helpers`; `TableRead._USER_COLS`
  and `TableRead._row_to_user`.
- Produces:
  - `TableRead.get_user_by_google_sub(db, google_sub: str) -> User | None`
  - `TableRead.get_user_by_email_ci(db, email: str) -> User | None`
  - `TableWrite.create_user(db, email, password_hash: str | None, handle=None,
    google_sub: str | None = None) -> tuple[str, LocalAccount, str]`
  - `TableWrite.set_google_sub(db, user_id: str, google_sub: str) -> bool`

- [ ] **Step 1: Write the failing test**

Create `tests/db/test_google_identity.py`:

```python
"""users: a Google identity is a column, a unique index and two lookups."""

import psycopg
import pytest

from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from tests.db_helpers import fresh_test_conn


def test_creates_an_account_with_no_password():
    """A Google account has no password, and a sentinel would be a lie some
    later verify_password call could trip over."""
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn,
        email="nopass@example.com",
        password_hash=None,
        handle="NoPass",
        google_sub="sub-1",
    )
    assert TableRead.get_password_hash_by_userid(conn, user_id) is None
    conn.close()


def test_looks_an_account_up_by_google_sub():
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn,
        email="sub@example.com",
        password_hash=None,
        handle="SubUser",
        google_sub="sub-42",
    )
    found = TableRead.get_user_by_google_sub(conn, "sub-42")
    assert found is not None and found.user_id == user_id
    assert TableRead.get_user_by_google_sub(conn, "sub-nobody") is None
    conn.close()


def test_google_sub_is_unique():
    conn = fresh_test_conn()
    TableWrite.create_user(
        conn, email="a@example.com", password_hash=None, handle="A", google_sub="dup"
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        TableWrite.create_user(
            conn,
            email="b@example.com",
            password_hash=None,
            handle="B",
            google_sub="dup",
        )
    conn.close()


def test_many_accounts_may_have_no_google_sub():
    """NULLs do not collide — the unique index must not make Google mandatory."""
    conn = fresh_test_conn()
    TableWrite.create_user(conn, email="p1@example.com", password_hash="x", handle="P1")
    TableWrite.create_user(conn, email="p2@example.com", password_hash="x", handle="P2")
    assert TableRead.get_user_by_google_sub(conn, "anything") is None
    conn.close()


def test_stamps_a_google_sub_on_an_existing_account():
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn, email="link@example.com", password_hash="x", handle="Link"
    )
    assert TableWrite.set_google_sub(conn, user_id, "sub-linked") is True
    found = TableRead.get_user_by_google_sub(conn, "sub-linked")
    assert found is not None and found.user_id == user_id
    conn.close()


def test_email_lookup_for_linking_ignores_case():
    """Registration stores the address as typed. `Alice@Example.com` and the
    `alice@example.com` Google reports are the same person to everyone except
    `=`, and linking is the one place that difference would mint a second
    wallet."""
    conn = fresh_test_conn()
    user_id, _acct, _key = TableWrite.create_user(
        conn, email="Alice@Example.COM", password_hash="x", handle="Alice"
    )
    found = TableRead.get_user_by_email_ci(conn, "alice@example.com")
    assert found is not None and found.user_id == user_id
    # The exact-match reader is unchanged — login still compares as stored.
    assert TableRead.get_user_by_email(conn, "alice@example.com") is None
    conn.close()


def test_email_lookup_returns_none_for_a_stranger():
    conn = fresh_test_conn()
    assert TableRead.get_user_by_email_ci(conn, "nobody@example.com") is None
    conn.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/db/test_google_identity.py -q
```

Expected: failures — `create_user() got an unexpected keyword argument
'google_sub'`.

- [ ] **Step 3: Add the column and drop the NOT NULL**

In `agentpit/db/table_create.py`, inside `create_users_table`, change the
`PASSWORD_HASH` line and add `GOOGLE_SUB` as the last column:

```python
            CREATE TABLE IF NOT EXISTS users (
                USER_ID         TEXT PRIMARY KEY,
                EMAIL           TEXT NOT NULL UNIQUE,
                PASSWORD_HASH   TEXT,
                HANDLE          TEXT UNIQUE,
                ETH_ADDRESS     TEXT NOT NULL UNIQUE,
                ETH_PRIVATE_KEY TEXT NOT NULL UNIQUE,
                API_KEY         TEXT NOT NULL UNIQUE,
                ONBOARDED_AT    BIGINT,
                CREATED_AT      BIGINT NOT NULL,
                IS_BOT          INTEGER NOT NULL DEFAULT 0,
                GOOGLE_SUB      TEXT
            )
```

`GOOGLE_SUB` is declared without `UNIQUE` here on purpose: the constraint is
created as a named index in `_migrate_users_table` below, so a fresh database
and a migrated one end up with the same one index rather than two under
different names.

Then in `_migrate_users_table`, add `GOOGLE_SUB` to `additions` and append the
two statements after the loop:

```python
        additions = [
            ("EMAIL", "TEXT"),
            ("PASSWORD_HASH", "TEXT"),
            ("HANDLE", "TEXT"),
            ("ETH_ADDRESS", "TEXT"),
            ("ONBOARDED_AT", "BIGINT"),
            ("CREATED_AT", "BIGINT"),
            ("IS_BOT", "INTEGER NOT NULL DEFAULT 0"),
            ("LAST_TOPUP_AT", "BIGINT"),
            ("TOTAL_DEPOSITED", "BIGINT"),
            ("DEPLOYMENT_ID", "TEXT"),
            ("GOOGLE_SUB", "TEXT"),
        ]
        for col, col_type in additions:
            conn.execute(
                f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {col_type}"
            )
        # An account that arrived through Google has no password. Databases
        # created before this line have PASSWORD_HASH NOT NULL; dropping it is
        # idempotent, so this is safe on every run.
        conn.execute("ALTER TABLE users ALTER COLUMN PASSWORD_HASH DROP NOT NULL")
        # `sub` is Google's stable id for an account — one of them is one of
        # ours. NULLs do not collide in Postgres, so password-only accounts are
        # unaffected.
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub "
            "ON users(GOOGLE_SUB)"
        )
```

- [ ] **Step 4: Add the readers**

In `agentpit/db/table_read.py`, immediately after `get_user_by_email`:

```python
    @staticmethod
    def get_user_by_google_sub(
        db: psycopg.Connection, google_sub: str
    ) -> "User | None":
        row = db.execute(
            f"SELECT {TableRead._USER_COLS} FROM users WHERE GOOGLE_SUB = %s LIMIT 1",
            (google_sub,),
        ).fetchone()
        return TableRead._row_to_user(row) if row else None

    @staticmethod
    def get_user_by_email_ci(db: psycopg.Connection, email: str) -> "User | None":
        """Case-insensitive email lookup, used only for linking a Google identity.

        Registration stores the address as typed, so `Alice@Example.com` and the
        `alice@example.com` Google reports are the same person to everyone
        except `=`. Linking is the one place that difference would mint a second
        wallet, so it is the one place that compares case-insensitively. Login
        keeps the exact-match reader above.
        """
        row = db.execute(
            f"SELECT {TableRead._USER_COLS} FROM users "
            "WHERE LOWER(EMAIL) = LOWER(%s) ORDER BY CREATED_AT LIMIT 1",
            (email,),
        ).fetchone()
        return TableRead._row_to_user(row) if row else None
```

- [ ] **Step 5: Add the writers**

In `agentpit/db/table_write.py`, change `create_user`'s signature and INSERT:

```python
    def create_user(
        db: psycopg.Connection,
        email: str,
        password_hash: str | None,
        handle: str | None = None,
        google_sub: str | None = None,
    ) -> tuple[str, LocalAccount, str]:
        """Create a new user with an auto-generated eth keypair.

        Returns (user_id, eth_account, api_key). The caller is responsible for
        running on-chain onboarding (faucet drip + approvals) and then calling
        :func:`mark_user_onboarded` once those txns confirm.

        `password_hash` is None for an account that arrived through Google, and
        `google_sub` is None for one that arrived with a password. Every account
        has at least one of them.
        """
        acct: LocalAccount = Account.create()
        key_hex: str = Web3.to_hex(acct.key)
        user_id: str = str(uuid.uuid4())
        api_key: str = str(uuid.uuid4())
        created_at = int(_time.time())

        db.execute(
            """
            INSERT INTO users (
                USER_ID, EMAIL, PASSWORD_HASH, HANDLE,
                ETH_ADDRESS, ETH_PRIVATE_KEY, API_KEY,
                ONBOARDED_AT, CREATED_AT, GOOGLE_SUB
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, %s, %s)
            """,
            (
                user_id,
                email,
                password_hash,
                handle,
                acct.address,
                key_hex,
                api_key,
                created_at,
                google_sub,
            ),
        )
        return user_id, acct, api_key
```

And after `update_user_password_hash`:

```python
    @staticmethod
    def set_google_sub(
        db: psycopg.Connection, user_id: str, google_sub: str
    ) -> bool:
        cur = db.execute(
            "UPDATE users SET GOOGLE_SUB = %s WHERE USER_ID = %s",
            (google_sub, user_id),
        )
        return cur.rowcount > 0
```

- [ ] **Step 6: Run the new test, then the whole suite**

The `users` table in the test database already exists with `PASSWORD_HASH NOT
NULL`; `create_all_tables` runs the migration on every connection, so no manual
DDL is needed.

Run:

```bash
.venv/bin/python -m pytest tests/db/test_google_identity.py -q
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
```

Expected: the new file passes (7 tests), and the full suite is green — the
signature change is additive, so `tests/test_handles.py`,
`tests/test_leaderboard.py` and `agentpit/liquidity/house_accounts.py` keep
working unchanged.

- [ ] **Step 7: Commit**

```bash
git add agentpit/db/table_create.py agentpit/db/table_read.py \
        agentpit/db/table_write.py tests/db/test_google_identity.py
git commit -m "feat(db): users carry a google identity and may have no password"
```

---

### Task 3: `POST /auth/google`, and one onboarding path

The service method, the endpoint, the config flag, and the extraction that keeps
the two signup paths identical. This is where the feature is most likely to go
wrong, and the risk is not the Google part.

**Files:**
- Modify: `agentpit/config.py` (beside the other feature flags)
- Modify: `agentpit/domain/exceptions.py`
- Modify: `agentpit/api/exception_handlers.py`
- Create: `agentpit/datastructures/google_auth_request.py`
- Modify: `agentpit/datastructures/auth_response.py`
- Modify: `agentpit/services/auth_service.py`
- Modify: `agentpit/api/deps.py:38-52, 98-105`
- Modify: `agentpit/api/app.py:397-415, 605-624`
- Modify: `agentpit/api/routes/auth.py`
- Test: `tests/api/test_google_auth.py`
- Test: `tests/test_config_google.py`

**Interfaces:**
- Consumes: `GoogleTokenVerifier.verify(credential) -> GoogleIdentity` (Task 1);
  `TableRead.get_user_by_google_sub`, `TableRead.get_user_by_email_ci`,
  `TableWrite.create_user(…, google_sub=…)`, `TableWrite.set_google_sub`
  (Task 2).
- Produces:
  - `Settings.google_client_id: str` (default `""`)
  - `FeatureDisabledError` → HTTP 503
  - `GoogleAuthRequest{credential: str}`
  - `GoogleAuthResponse(AuthResponse)` with `created: bool`
  - `AuthService.google_sign_in(credential: str) -> GoogleAuthResponse`
  - `AuthService.__init__(db, coder, onchain_admin, settings, google_verifier=None)`
  - `get_google_verifier()` dependency placeholder, overridden by `create_app`
  - `POST /auth/google` — the shape the front end calls in Task 4

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_google_auth.py`:

```python
"""Google sign-in: linking rules, the disabled state, and the promise that a
Google signup and a password signup leave the same account behind.

Anvil + the deployed exchange must be running — a Google signup mints a wallet
and runs the same on-chain onboarding a password signup does.
"""

import pytest
from fastapi.testclient import TestClient

from agentpit.api.deps import get_google_verifier
from agentpit.api.main import app
from agentpit.auth.google import GoogleIdentity
from agentpit.db.table_read import TableRead
from agentpit.domain.exceptions import InvalidCredentialsError
from tests.db_helpers import fresh_test_conn


class _StubVerifier:
    """Maps a fake credential string to an identity; anything else is bad."""

    def __init__(self, identities: dict[str, GoogleIdentity]):
        self._identities = identities

    def verify(self, credential: str) -> GoogleIdentity:
        try:
            return self._identities[credential]
        except KeyError:
            raise InvalidCredentialsError("invalid Google credential") from None


@pytest.fixture
def google():
    """Override the app's verifier for one test and put it back afterwards.

    The app is a module-level singleton shared by the whole suite, so a leaked
    override would silently change every later test's idea of who is signing in.
    """

    def _install(identities: dict[str, GoogleIdentity]) -> None:
        app.dependency_overrides[get_google_verifier] = lambda: _StubVerifier(
            identities
        )

    previous = app.dependency_overrides.get(get_google_verifier)
    yield _install
    if previous is None:
        app.dependency_overrides.pop(get_google_verifier, None)
    else:
        app.dependency_overrides[get_google_verifier] = previous


ALICE = GoogleIdentity(sub="google-sub-alice", email="alice@example.com")


def test_first_google_sign_in_creates_an_account(google):
    google({"cred-alice": ALICE})
    with TestClient(app) as client:
        resp = client.post("/auth/google", json={"credential": "cred-alice"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["access_token"]
        assert body["token_type"] == "bearer"
        assert body["created"] is True
        assert body["user"]["email"] == "alice@example.com"
        assert body["user"]["eth_address"].startswith("0x")
        assert body["user"]["onboarded_at"] is not None
        assert body["user"]["handle"], "a Google signup must not be nameless"


def test_second_google_sign_in_returns_the_same_account(google):
    google({"cred-alice": ALICE})
    with TestClient(app) as client:
        first = client.post("/auth/google", json={"credential": "cred-alice"}).json()
        second = client.post("/auth/google", json={"credential": "cred-alice"}).json()
        assert second["created"] is False
        assert second["user"]["user_id"] == first["user"]["user_id"]
        assert second["user"]["eth_address"] == first["user"]["eth_address"]


def test_google_sign_in_links_to_a_matching_password_account(google):
    """Same person, new door. One address is one account — a second row would be
    a second wallet, a second balance and a second row on the board."""
    google({"cred-bob": GoogleIdentity(sub="google-sub-bob", email="bob@example.com")})
    with TestClient(app) as client:
        registered = client.post(
            "/register",
            json={"email": "bob@example.com", "password": "hunter22hunter22"},
        ).json()
        linked = client.post("/auth/google", json={"credential": "cred-bob"}).json()

        assert linked["created"] is False
        assert linked["user"]["user_id"] == registered["user"]["user_id"]
        assert linked["user"]["eth_address"] == registered["user"]["eth_address"]

    conn = fresh_test_conn()
    found = TableRead.get_user_by_google_sub(conn, "google-sub-bob")
    assert found is not None and found.email == "bob@example.com"
    conn.close()


def test_linking_ignores_email_case(google):
    google({"cred-carol": GoogleIdentity(sub="sub-carol", email="carol@example.com")})
    with TestClient(app) as client:
        registered = client.post(
            "/register",
            json={"email": "Carol@Example.com", "password": "hunter22hunter22"},
        ).json()
        linked = client.post("/auth/google", json={"credential": "cred-carol"}).json()
        assert linked["user"]["user_id"] == registered["user"]["user_id"]


def test_a_rejected_credential_is_unauthorized(google):
    google({"cred-alice": ALICE})
    with TestClient(app) as client:
        resp = client.post("/auth/google", json={"credential": "forged"})
        assert resp.status_code == 401


def test_endpoint_is_unavailable_when_no_client_id_is_configured():
    """Absent rather than broken: with no GOOGLE_CLIENT_ID the app builds no
    verifier, and the request is refused before any token is looked at."""
    previous = app.dependency_overrides.get(get_google_verifier)
    app.dependency_overrides[get_google_verifier] = lambda: None
    try:
        with TestClient(app) as client:
            resp = client.post("/auth/google", json={"credential": "anything"})
            assert resp.status_code == 503
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_google_verifier, None)
        else:
            app.dependency_overrides[get_google_verifier] = previous


def test_password_login_into_a_google_account_says_so(google):
    """Not "invalid email or password" — that sends somebody who has forgotten
    which door they used around in a circle."""
    google({"cred-dave": GoogleIdentity(sub="sub-dave", email="dave@example.com")})
    with TestClient(app) as client:
        client.post("/auth/google", json={"credential": "cred-dave"})
        resp = client.post(
            "/login", json={"email": "dave@example.com", "password": "hunter22hunter22"}
        )
        assert resp.status_code == 401
        assert "google" in resp.json()["detail"].lower()


def test_changing_the_password_of_a_google_account_says_so(google):
    """There is no password to change, and 404 "User not found" would be a lie
    told to somebody who is signed in."""
    google({"cred-erin": GoogleIdentity(sub="sub-erin", email="erin@example.com")})
    with TestClient(app) as client:
        token = client.post(
            "/auth/google", json={"credential": "cred-erin"}
        ).json()["access_token"]
        resp = client.patch(
            "/me/password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "current_password": "hunter22hunter22",
                "new_password": "newhunter22hunter22",
            },
        )
        assert resp.status_code == 400
        assert "google" in resp.json()["detail"].lower()


def test_login_with_an_unknown_email_is_still_generic():
    """The Google message is for accounts that exist. A stranger learns nothing
    beyond what registration's 409 already tells them."""
    with TestClient(app) as client:
        resp = client.post(
            "/login", json={"email": "ghost@example.com", "password": "hunter22hunter22"}
        )
        assert resp.status_code == 401
        assert "google" not in resp.json()["detail"].lower()


def test_google_signup_and_password_signup_leave_the_same_state(google):
    """The test that keeps the two paths from drifting. Both accounts must come
    out with a wallet, a funded chain balance, a handle, a recorded deposit and
    a recorded deployment — the difference between them is the credential and
    nothing else."""
    google({"cred-frank": GoogleIdentity(sub="sub-frank", email="frank@example.com")})
    with TestClient(app) as client:
        by_password = client.post(
            "/register",
            json={"email": "grace@example.com", "password": "hunter22hunter22"},
        ).json()["user"]
        by_google = client.post(
            "/auth/google", json={"credential": "cred-frank"}
        ).json()["user"]

    for account in (by_password, by_google):
        assert account["eth_address"].startswith("0x")
        assert account["api_key"]
        assert account["handle"]
        assert account["onboarded_at"] is not None

    default_raw = -1  # any read that falls through to the default is a failure
    conn = fresh_test_conn()
    try:
        for account in (by_password, by_google):
            user_id = account["user_id"]
            assert TableRead.get_total_deposited(conn, user_id, default_raw) > 0
            assert TableRead.get_deployment_id(conn, user_id) is not None
        assert TableRead.get_password_hash_by_userid(
            conn, by_password["user_id"]
        ) is not None
        assert TableRead.get_password_hash_by_userid(
            conn, by_google["user_id"]
        ) is None
    finally:
        conn.close()
```

Create `tests/test_config_google.py`:

```python
from agentpit.config import Settings


def _settings(monkeypatch, **env):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)


def test_google_sign_in_is_off_by_default(monkeypatch):
    """Unset is the off switch — the app builds no verifier and the endpoint
    answers 503, rather than half-working."""
    assert _settings(monkeypatch).google_client_id == ""


def test_google_client_id_is_read_from_the_environment(monkeypatch):
    s = _settings(monkeypatch, GOOGLE_CLIENT_ID="123-abc.apps.googleusercontent.com")
    assert s.google_client_id == "123-abc.apps.googleusercontent.com"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/api/test_google_auth.py tests/test_config_google.py -q
```

Expected: collection error — `cannot import name 'get_google_verifier' from
'agentpit.api.deps'`.

- [ ] **Step 3: Add the setting, the exception and its handler**

In `agentpit/config.py`, next to the other feature switches (immediately after
the `leaderboard_enabled` field):

```python
    # Google sign-in's audience check. Empty means the feature is off: no
    # verifier is built and POST /auth/google answers 503. A client id is public
    # by design — it appears in the page of every site that uses Google sign-in
    # — and this flow has no client secret at all.
    google_client_id: str = Field(default="", validation_alias="GOOGLE_CLIENT_ID")
```

In `agentpit/domain/exceptions.py`, after `InvalidCredentialsError`:

```python
class FeatureDisabledError(DomainError):
    """Raised when a feature is switched off by configuration rather than broken."""
```

In `agentpit/api/exception_handlers.py`, import it and register the handler
before the `BusinessRuleError` one:

```python
    @app.exception_handler(FeatureDisabledError)
    async def _feature_disabled(_: Request, exc: FeatureDisabledError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})
```

- [ ] **Step 4: Add the request and response models**

Create `agentpit/datastructures/google_auth_request.py`:

```python
from pydantic import BaseModel


class GoogleAuthRequest(BaseModel):
    """The ID token Google Identity Services hands the browser.

    GIS calls its callback with `{credential: "<jwt>"}`; the field keeps that
    name so the front end forwards what it was given, unrenamed.
    """

    credential: str
```

In `agentpit/datastructures/auth_response.py`, append:

```python
class GoogleAuthResponse(AuthResponse):
    """`AuthResponse` plus whether this sign-in created the account.

    The password path greets a new user with "your wallet is funded"; without
    this flag the Google path cannot tell a first sign-in from a returning one,
    and either every user gets the greeting or nobody does.
    """

    created: bool
```

- [ ] **Step 5: Extract the onboarding routine and add `google_sign_in`**

In `agentpit/services/auth_service.py`. Extend the imports:

```python
from agentpit.auth.google import GoogleTokenVerifier
from agentpit.datastructures.auth_response import (
    AuthResponse,
    GoogleAuthResponse,
    UserPublic,
)
from agentpit.domain.exceptions import (
    BusinessRuleError,
    FeatureDisabledError,
    InvalidCredentialsError,
    OnboardingError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
```

Take the verifier in the constructor:

```python
    def __init__(
        self,
        db: DbSession,
        coder: JwtCoder,
        onchain_admin: OnchainAdmin,
        settings: Settings,
        google_verifier: GoogleTokenVerifier | None = None,
    ):
        self._db = db
        self._coder = coder
        self._onchain = onchain_admin
        self._settings = settings
        self._google = google_verifier
```

Replace `register` with the version that ends at the shared routine — the body
that follows the insert moves verbatim into `_onboard_new_account`, comments
included:

```python
    def register(self, payload: RegisterRequest) -> AuthResponse:
        with self._db.write() as conn:
            if TableRead.get_user_by_email(conn, payload.email) is not None:
                raise UserAlreadyExistsError(payload.email)
            password_hash = hash_password(payload.password)
            # A supplied handle is a choice and is kept; a blank one is
            # filled. The availability check runs inside this transaction and
            # `HANDLE TEXT UNIQUE` is still the guarantee behind it -- two
            # signups landing on the same generated name in the same
            # millisecond would fail the insert rather than duplicate it,
            # which needs both a sub-millisecond overlap and the same 1-in-
            # 14,400 draw.
            handle = payload.handle or pick_handle(
                taken=lambda candidate: TableRead.handle_taken(conn, candidate)
            )
            user_id, acct, _api_key = TableWrite.create_user(
                conn,
                email=payload.email,
                password_hash=password_hash,
                handle=handle,
            )
        return self._issue(self._onboard_new_account(user_id, acct))
```

Add `google_sign_in` immediately after `login`:

```python
    def google_sign_in(self, credential: str) -> GoogleAuthResponse:
        """Sign in — or sign up — with a Google ID token.

        Lookup order is `sub` first, then the verified email. `sub` is Google's
        stable identifier; the address on a Google account can change, and an
        email-only lookup would then treat a returning user as a stranger and
        mint them a second wallet.
        """
        if self._google is None:
            raise FeatureDisabledError("Google sign-in is not configured")
        identity = self._google.verify(credential)

        with self._db.read() as conn:
            user = TableRead.get_user_by_google_sub(conn, identity.sub)
            by_email = (
                TableRead.get_user_by_email_ci(conn, identity.email)
                if user is None
                else None
            )

        if user is not None:
            self._maybe_reonboard(user)
            return self._google_response(user, created=False)

        if by_email is not None:
            # The same person arriving by a new door. Splitting them across two
            # accounts is not cosmetic: each one holds its own paper balance,
            # its own positions and its own standing on the board, so the second
            # would put their money somewhere they cannot see from where they
            # are standing. The email is verified -- that check is what makes
            # this safe.
            with self._db.write() as conn:
                TableWrite.set_google_sub(conn, by_email.user_id, identity.sub)
            self._maybe_reonboard(by_email)
            return self._google_response(by_email, created=False)

        with self._db.write() as conn:
            handle = pick_handle(
                taken=lambda candidate: TableRead.handle_taken(conn, candidate)
            )
            user_id, acct, _api_key = TableWrite.create_user(
                conn,
                email=identity.email,
                password_hash=None,
                handle=handle,
                google_sub=identity.sub,
            )
        return self._google_response(
            self._onboard_new_account(user_id, acct), created=True
        )
```

Replace `login` so a password-less account is told what it is:

```python
    def login(self, payload: LoginRequest) -> AuthResponse:
        with self._db.read() as conn:
            user = TableRead.get_user_by_email(conn, payload.email)
            password_hash = (
                TableRead.get_password_hash_by_userid(conn, user.user_id)
                if user is not None
                else None
            )
        if user is None:
            raise InvalidCredentialsError("invalid email or password")
        if password_hash is None:
            # This account arrived through Google and has no password. Saying
            # "invalid email or password" would send somebody who has forgotten
            # which door they used around in a circle. It tells an attacker the
            # address is registered, which registration's 409 already does.
            raise InvalidCredentialsError("this account signs in with Google")
        if not verify_password(payload.password, password_hash):
            raise InvalidCredentialsError("invalid email or password")
        self._maybe_reonboard(user)
        return self._issue(user)
```

In `change_password`, replace the `current_hash is None` branch:

```python
        with self._db.write() as conn:
            if TableRead.get_user_by_userid(conn, user_id) is None:
                raise UserNotFoundError()
            current_hash = TableRead.get_password_hash_by_userid(conn, user_id)
            if current_hash is None:
                # A Google account has no password to change, and 404 "User not
                # found" would be a lie told to somebody who is signed in.
                # Setting one is deliberately out of scope: there is no password
                # reset flow in the product at all.
                raise BusinessRuleError("this account signs in with Google")
```

Add the two helpers beside `_issue`:

```python
    def _onboard_new_account(self, user_id: str, acct) -> User:
        """Everything a new account needs once its row exists.

        Both signup paths call this and neither does the work inline. Two copies
        would drift -- one gains a step the other does not -- and the difference
        surfaces months later as an account that cannot trade.
        """
        # On-chain onboarding happens *outside* the DB transaction so we don't
        # hold the write lock for ~1s of network round-trips.
        try:
            self._run_onboarding(acct)
        except Exception as exc:
            log.exception("on-chain onboarding failed for user %s", user_id)
            raise OnboardingError(str(exc)) from exc
        with self._db.write() as conn:
            TableWrite.mark_user_onboarded(conn, user_id)

        # Recording the deposit is a separate transaction from marking the
        # user onboarded above. If it fails -- whether the chain read or the
        # UPDATE itself raises -- psycopg would otherwise issue COMMIT on an
        # already-aborted transaction and Postgres turns that into a
        # ROLLBACK, taking mark_user_onboarded down with it. A failure here
        # must not turn a successful signup into a failed one (same treatment
        # on-chain reads get elsewhere in this service -- see
        # _maybe_reonboard), and TOTAL_DEPOSITED staying NULL is fine: it
        # reads back as the grant via get_total_deposited's default.
        try:
            # Read the granted amount off the chain rather than from config:
            # the grant is baked into an immutable contract by
            # scripts/deploy_exchange.sh, while paper_balance_target_raw is a
            # separate Settings field. They are documented to agree and today
            # they do, but they are two sources and either can move.
            #
            # Read before opening the transaction, for the same reason the
            # onboarding above sits outside one: no DB write lock should be
            # held across a network round-trip.
            granted = self._onchain.usd_balance(acct.address)
            with self._db.write() as conn:
                TableWrite.set_total_deposited(conn, user_id, granted)
                TableWrite.set_deployment_id(
                    conn, user_id, self._onchain.deployment_id
                )
        except Exception:
            log.exception("reading granted balance failed for user %s", user_id)

        with self._db.read() as conn:
            user = TableRead.get_user_by_userid(conn, user_id)
        if user is None:
            raise RuntimeError("user disappeared between insert and read")
        return user

    def _google_response(self, user: User, *, created: bool) -> GoogleAuthResponse:
        issued = self._issue(user)
        return GoogleAuthResponse(
            access_token=issued.access_token,
            token_type=issued.token_type,
            user=issued.user,
            created=created,
        )
```

- [ ] **Step 6: Wire the dependency, the app factory and the route**

In `agentpit/api/deps.py`, import the verifier and add the placeholder beside
`get_onchain_admin`:

```python
from agentpit.auth.google import GoogleTokenVerifier
```

```python
def get_google_verifier() -> GoogleTokenVerifier | None:
    raise RuntimeError("get_google_verifier has not been overridden by the app factory")
```

Add the annotated type beside the others, and pass it into the service:

```python
GoogleVerifierDep = Annotated[
    GoogleTokenVerifier | None, Depends(get_google_verifier)
]
```

```python
def get_auth_service(
    db: SessionDep,
    coder: JwtCoderDep,
    onchain: OnchainAdminDep,
    settings: SettingsDep,
    google: GoogleVerifierDep,
) -> AuthService:
    return AuthService(db, coder, onchain, settings, google)
```

In `agentpit/api/app.py`, add `get_google_verifier` to the existing
`from agentpit.api.deps import (…)` block at line 10 (alphabetical: after
`get_db_session`), and add the verifier import beside the other `agentpit.auth`
imports:

```python
from agentpit.auth.google import GoogleTokenVerifier
```

Build the verifier next to `coder` (around line 412):

```python
    coder = JwtCoder(settings)
    onchain_admin = _build_onchain_admin(settings)
    current_user_fn = make_current_user_dep(coder)
    # One verifier per app: it caches Google's signing keys, and a per-request
    # instance would re-fetch them on every sign-in.
    google_verifier = (
        GoogleTokenVerifier(settings.google_client_id)
        if settings.google_client_id
        else None
    )
    if google_verifier is None:
        # Said out loud because the failure is otherwise invisible: with no
        # client id the button is absent and the endpoint 503s, which looks
        # exactly like a deploy that forgot the variable. It is one.
        log.info("Google sign-in disabled (set GOOGLE_CLIENT_ID to enable)")
```

And register the override beside the others:

```python
    app.dependency_overrides[get_google_verifier] = lambda: google_verifier
```

In `agentpit/api/routes/auth.py`, add the endpoint:

```python
from agentpit.datastructures.auth_response import AuthResponse, GoogleAuthResponse
from agentpit.datastructures.google_auth_request import GoogleAuthRequest
```

```python
@router.post("/auth/google", response_model=GoogleAuthResponse)
def google_sign_in(
    payload: GoogleAuthRequest, service: AuthServiceDep
) -> GoogleAuthResponse:
    return service.google_sign_in(payload.credential)
```

- [ ] **Step 7: Run the new tests, then the whole suite**

Run:

```bash
.venv/bin/python -m pytest tests/api/test_google_auth.py tests/test_config_google.py -q
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
```

Expected: both files pass, and the existing `tests/api/test_auth.py` stays green
— the rewritten `login` and `change_password` keep every prior behaviour for
accounts that have a password.

- [ ] **Step 8: Commit**

```bash
git add agentpit/config.py agentpit/domain/exceptions.py \
        agentpit/api/exception_handlers.py \
        agentpit/datastructures/google_auth_request.py \
        agentpit/datastructures/auth_response.py \
        agentpit/services/auth_service.py agentpit/api/deps.py \
        agentpit/api/app.py agentpit/api/routes/auth.py \
        tests/api/test_google_auth.py tests/test_config_google.py
git commit -m "feat(auth): sign in with google, onboarding one path not two"
```

---

### Task 4: The button

Google Identity Services in the sign-up dialog, present only when the build
knows a client id.

**Files:**
- Create: `ui/src/lib/googleAuth.ts`
- Create: `ui/src/lib/googleAuth.test.ts`
- Create: `ui/src/components/auth/GoogleSignInButton.tsx`
- Create: `ui/src/auth/welcomeToast.tsx`
- Modify: `ui/src/vite-env.d.ts`
- Modify: `ui/src/api/auth.ts`
- Modify: `ui/src/auth/context.ts`
- Modify: `ui/src/auth/AuthContext.tsx:133-168`
- Modify: `ui/src/components/auth/AuthDialog.tsx`

**Interfaces:**
- Consumes: `POST /auth/google` taking `{credential}` and answering
  `{access_token, token_type, user, created}` (Task 3).
- Produces:
  - `readGoogleClientId(env): string | null`, `GOOGLE_CLIENT_ID: string | null`,
    `loadGoogleIdentity(doc?: Document): Promise<void>`
  - `googleSignInRequest(credential: string): Promise<GoogleAuthResponse>`
  - `AuthValue.signInWithGoogle(credential: string): Promise<void>`
  - `<GoogleSignInButton onCredential onError disabled />`

- [ ] **Step 1: Write the failing test**

Create `ui/src/lib/googleAuth.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";

type FakeScript = {
  id: string;
  src: string;
  async: boolean;
  defer: boolean;
  onload: (() => void) | null;
  onerror: (() => void) | null;
};

function fakeDocument() {
  const scripts: FakeScript[] = [];
  const byId = new Map<string, FakeScript>();
  const doc = {
    getElementById: (id: string) => byId.get(id) ?? null,
    createElement: () =>
      ({
        id: "",
        src: "",
        async: false,
        defer: false,
        onload: null,
        onerror: null,
      }) as FakeScript,
    head: {
      appendChild: (node: FakeScript) => {
        scripts.push(node);
        byId.set(node.id, node);
      },
    },
  };
  return { doc: doc as unknown as Document, scripts };
}

// Each test needs a module whose loader promise has never been used: the
// singleton is the behaviour under test.
async function freshModule() {
  vi.resetModules();
  return await import("./googleAuth");
}

describe("readGoogleClientId", () => {
  it("returns the configured id", async () => {
    const { readGoogleClientId } = await freshModule();
    expect(readGoogleClientId({ VITE_GOOGLE_CLIENT_ID: "abc.apps.googleusercontent.com" }))
      .toBe("abc.apps.googleusercontent.com");
  });

  it("treats an unset variable as off", async () => {
    const { readGoogleClientId } = await freshModule();
    expect(readGoogleClientId({})).toBeNull();
  });

  it("treats an empty or blank variable as off", async () => {
    // A build arg that resolved to nothing must switch the feature off, not
    // render a button that initialises GIS with an empty client id.
    const { readGoogleClientId } = await freshModule();
    expect(readGoogleClientId({ VITE_GOOGLE_CLIENT_ID: "" })).toBeNull();
    expect(readGoogleClientId({ VITE_GOOGLE_CLIENT_ID: "   " })).toBeNull();
  });

  it("trims surrounding whitespace", async () => {
    const { readGoogleClientId } = await freshModule();
    expect(readGoogleClientId({ VITE_GOOGLE_CLIENT_ID: " abc \n" })).toBe("abc");
  });
});

describe("loadGoogleIdentity", () => {
  beforeEach(() => vi.resetModules());

  it("injects the script once, however many callers ask", async () => {
    const { loadGoogleIdentity } = await freshModule();
    const { doc, scripts } = fakeDocument();

    const first = loadGoogleIdentity(doc);
    const second = loadGoogleIdentity(doc);
    expect(scripts).toHaveLength(1);

    scripts[0]!.onload?.();
    await expect(first).resolves.toBeUndefined();
    await expect(second).resolves.toBeUndefined();
    expect(scripts).toHaveLength(1);
  });

  it("resolves once the script loads", async () => {
    const { loadGoogleIdentity } = await freshModule();
    const { doc, scripts } = fakeDocument();
    const loading = loadGoogleIdentity(doc);
    scripts[0]!.onload?.();
    await expect(loading).resolves.toBeUndefined();
  });

  it("rejects when the script fails, and lets a later caller retry", async () => {
    const { loadGoogleIdentity } = await freshModule();
    const { doc, scripts } = fakeDocument();

    const failing = loadGoogleIdentity(doc);
    scripts[0]!.onerror?.();
    await expect(failing).rejects.toThrow(/Google/);

    // A cached rejected promise would make one blocked network request
    // permanent for the tab; the next attempt gets a new script.
    const retry = loadGoogleIdentity(doc);
    expect(scripts).toHaveLength(2);
    scripts[1]!.onload?.();
    await expect(retry).resolves.toBeUndefined();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run, from `ui/`:

```bash
npx vitest run src/lib/googleAuth.test.ts
```

Expected: FAIL — cannot resolve `./googleAuth`.

- [ ] **Step 3: Write the module**

Create `ui/src/lib/googleAuth.ts`:

```ts
/**
 * Google Identity Services glue.
 *
 * The client id is public by design — it sits in the page of every site that
 * uses Google sign-in — but its absence is meaningful: no id means the feature
 * is off, and the button must not render at all.
 */

const GIS_SRC = "https://accounts.google.com/gsi/client";
const GIS_SCRIPT_ID = "google-identity-services";

export function readGoogleClientId(env: {
  VITE_GOOGLE_CLIENT_ID?: string;
}): string | null {
  const raw = env.VITE_GOOGLE_CLIENT_ID;
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/** Baked in at build time by Vite. Null when the build had no client id. */
export const GOOGLE_CLIENT_ID = readGoogleClientId(import.meta.env);

let loading: Promise<void> | null = null;

/** Load Google's script once per tab. `doc` is injectable so the loader can be
 *  tested without a DOM. */
export function loadGoogleIdentity(doc: Document = document): Promise<void> {
  if (loading) return loading;
  loading = new Promise<void>((resolve, reject) => {
    if (doc.getElementById(GIS_SCRIPT_ID)) {
      resolve();
      return;
    }
    const script = doc.createElement("script");
    script.id = GIS_SCRIPT_ID;
    script.src = GIS_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => {
      // Forget the failure: a cached rejected promise would make one blocked
      // request permanent for the tab, so a user on a flaky connection could
      // never try again without a reload.
      loading = null;
      reject(new Error("Google sign-in failed to load"));
    };
    doc.head.appendChild(script);
  });
  return loading;
}

type CredentialResponse = { credential?: string };

type GoogleIdentityApi = {
  accounts: {
    id: {
      initialize(config: {
        client_id: string;
        callback: (response: CredentialResponse) => void;
      }): void;
      renderButton(
        parent: HTMLElement,
        options: {
          type?: "standard" | "icon";
          theme?: "outline" | "filled_blue" | "filled_black";
          size?: "small" | "medium" | "large";
          text?: "signin_with" | "signup_with" | "continue_with";
          shape?: "rectangular" | "pill";
          width?: number;
        },
      ): void;
    };
  };
};

declare global {
  interface Window {
    google?: GoogleIdentityApi;
  }
}

export type { CredentialResponse, GoogleIdentityApi };
```

Add the variable to `ui/src/vite-env.d.ts`:

```ts
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_GOOGLE_CLIENT_ID?: string;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run, from `ui/`:

```bash
npx vitest run src/lib/googleAuth.test.ts
```

Expected: 7 passed.

- [ ] **Step 5: Add the API call and the auth-context method**

In `ui/src/api/auth.ts`, after `registerRequest`:

```ts
export type GoogleAuthResponse = AuthResponse & {
  /** True when this sign-in created the account. */
  created: boolean;
};

export function googleSignInRequest(
  credential: string,
): Promise<GoogleAuthResponse> {
  return apiFetch<GoogleAuthResponse>("/auth/google", {
    method: "POST",
    body: JSON.stringify({ credential }),
  });
}
```

Create `ui/src/auth/welcomeToast.tsx` by moving the toast out of
`AuthContext.tsx` verbatim, so both signup paths raise the same one:

```tsx
import { toast } from "sonner";

/** First sign-up: a prominent, top-center welcome so new users immediately see
 *  their wallet is funded. Deferred a beat so it pops after the auth dialog
 *  closes rather than behind it. */
export function showWelcomeToast(): void {
  window.setTimeout(() => {
    toast.custom(
      () => (
        <div className="flex w-[min(92vw,460px)] items-start gap-3 rounded-2xl border border-emerald-500/40 bg-card px-5 py-4 shadow-xl">
          <span className="text-3xl leading-none">🎉</span>
          <div className="min-w-0">
            <p className="text-base font-semibold tracking-tight text-foreground">
              Welcome to agentpit! Your wallet is funded.
            </p>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
              {"We've credited your account with apUSD — open any market and place your first trade."}
            </p>
            <a
              href="/#build"
              className="mt-2 inline-flex items-center gap-1 text-sm font-semibold text-emerald-600 underline-offset-4 hover:underline dark:text-emerald-400"
            >
              Connect your own trading agent →
            </a>
          </div>
        </div>
      ),
      { position: "top-center", duration: 5000, unstyled: true },
    );
  }, 300);
}
```

In `ui/src/auth/context.ts`, add to `AuthValue`:

```ts
  signInWithGoogle: (credential: string) => Promise<void>;
```

In `ui/src/auth/AuthContext.tsx`: drop the `toast` import and the inline toast
JSX, import `showWelcomeToast` and `googleSignInRequest`, call the helper at the
end of `register`, and add the new callback beside it:

```tsx
  const signInWithGoogle = useCallback<AuthValue["signInWithGoogle"]>(
    async (credential) => {
      const resp = await googleSignInRequest(credential);
      persistToken(resp.access_token);
      setUser(resp.user);
      setDialogOpen(false);
      // Only a brand-new account gets the greeting — a returning user has seen
      // it, and being told their wallet was just funded would be untrue.
      if (resp.created) showWelcomeToast();
    },
    [persistToken],
  );
```

Add `signInWithGoogle` to the `useMemo` value object and to its dependency
array.

- [ ] **Step 6: Add the button component**

Create `ui/src/components/auth/GoogleSignInButton.tsx`:

```tsx
import { useEffect, useRef } from "react";
import { GOOGLE_CLIENT_ID, loadGoogleIdentity } from "@/lib/googleAuth";

interface GoogleSignInButtonProps {
  onCredential: (credential: string) => void;
  onError: (message: string) => void;
}

/** Google's own button, rendered by their script into a host element.
 *  Renders nothing when the build has no client id. */
export function GoogleSignInButton({
  onCredential,
  onError,
}: GoogleSignInButtonProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  // GIS keeps the callback it was initialised with; the ref lets that fixed
  // callback reach the current handlers without re-initialising on every
  // render.
  const handlers = useRef({ onCredential, onError });
  handlers.current = { onCredential, onError };

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;
    let cancelled = false;

    loadGoogleIdentity()
      .then(() => {
        if (cancelled || !hostRef.current || !window.google) return;
        window.google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          callback: (response) => {
            if (response.credential) {
              handlers.current.onCredential(response.credential);
            } else {
              handlers.current.onError("Google did not return a credential.");
            }
          },
        });
        window.google.accounts.id.renderButton(hostRef.current, {
          type: "standard",
          theme: "outline",
          size: "large",
          text: "continue_with",
          shape: "rectangular",
          width: 360,
        });
      })
      .catch(() => {
        if (!cancelled) {
          handlers.current.onError(
            "Google sign-in is unavailable right now. Use email and password.",
          );
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (!GOOGLE_CLIENT_ID) return null;
  return <div ref={hostRef} className="flex justify-center" />;
}
```

- [ ] **Step 7: Put it in the dialog**

In `ui/src/components/auth/AuthDialog.tsx`: import `GOOGLE_CLIENT_ID`, the
button, and take `signInWithGoogle` from `useAuth`. Add the handler above
`onSubmit`:

```tsx
  const onGoogleCredential = async (credential: string) => {
    setError(null);
    setSubmitting(true);
    try {
      await signInWithGoogle(credential);
    } catch (err) {
      setError(extractDetail(err));
    } finally {
      setSubmitting(false);
    }
  };
```

And render it above the form, inside `<DialogContent>`, with a divider:

```tsx
        {GOOGLE_CLIENT_ID && (
          <div className="space-y-4">
            <GoogleSignInButton
              onCredential={(credential) => void onGoogleCredential(credential)}
              onError={setError}
            />
            <div className="flex items-center gap-3">
              <span className="h-px flex-1 bg-border" />
              <span className="text-xs uppercase tracking-wider text-muted-foreground">
                or
              </span>
              <span className="h-px flex-1 bg-border" />
            </div>
          </div>
        )}
```

Both tabs get it: somebody who signed up with Google needs the same button to
sign back in.

- [ ] **Step 8: Run every UI check**

Run, from `ui/`:

```bash
npx vitest run && npm run typecheck && npm run lint && npm run build
```

Expected: all green. The build has no `VITE_GOOGLE_CLIENT_ID`, so the button is
absent from that bundle — which is the off state working.

- [ ] **Step 9: Commit**

```bash
git add ui/src/lib/googleAuth.ts ui/src/lib/googleAuth.test.ts \
        ui/src/components/auth/GoogleSignInButton.tsx \
        ui/src/auth/welcomeToast.tsx ui/src/vite-env.d.ts \
        ui/src/api/auth.ts ui/src/auth/context.ts ui/src/auth/AuthContext.tsx \
        ui/src/components/auth/AuthDialog.tsx
git commit -m "feat(ui): continue with google in the auth dialog"
```

---

### Task 5: Turning it on

The client id has to reach two places — the API's environment and the UI's
build. Neither is required; both are documented.

**Files:**
- Modify: `ui/.env.example`
- Modify: `.env.example`
- Modify: `deploy/Dockerfile.ui`
- Modify: `deploy/docker-compose.prod.yml:105-113`
- Modify: `deploy/env.prod.example`

**Interfaces:**
- Consumes: `GOOGLE_CLIENT_ID` (Task 3's setting) and `VITE_GOOGLE_CLIENT_ID`
  (Task 4's build-time read).
- Produces: nothing further tasks depend on.

- [ ] **Step 1: Document the variable for local development**

Append to `ui/.env.example`:

```
# The Google OAuth client id (Web application). Leave it out and the
# "Continue with Google" button does not render.
VITE_GOOGLE_CLIENT_ID=
```

Append to `.env.example`, immediately after the `JWT_SECRET` line (line 23) so
the auth settings stay together:

```
# Google sign-in. The same client id the UI is built with — it is the audience
# every Google ID token is checked against. Unset means POST /auth/google
# answers 503 and the feature is simply absent. There is no client secret in
# this flow.
GOOGLE_CLIENT_ID=
```

- [ ] **Step 2: Pass the build arg through the UI image**

In `deploy/Dockerfile.ui`, add the arg beside the existing one. It is *not*
added to the `test -n` guard: unlike the API URL, an absent client id is a valid
state.

```dockerfile
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
# Optional: absent means the "Continue with Google" button does not render.
ARG VITE_GOOGLE_CLIENT_ID
ENV VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID
RUN test -n "$VITE_API_BASE_URL" && yarn build
```

In `deploy/docker-compose.prod.yml`, under the `caddy` service's `build.args`:

```yaml
      args:
        VITE_API_BASE_URL: ${VITE_API_BASE_URL:?set in .env}
        VITE_GOOGLE_CLIENT_ID: ${VITE_GOOGLE_CLIENT_ID:-}
```

`:-` rather than `:?` — an operator who has not created the Google client yet
must still be able to deploy.

The `api` service already loads `../.env` wholesale, so `GOOGLE_CLIENT_ID` needs
no compose change.

- [ ] **Step 3: Document both variables for the operator**

Append to `deploy/env.prod.example`, after the `VITE_API_BASE_URL` block:

```
# --- Google sign-in (optional) ---------------------------------------------
# One OAuth client id, used twice: the API checks every Google ID token's
# audience against GOOGLE_CLIENT_ID, and the UI bundle is BUILT with
# VITE_GOOGLE_CLIENT_ID. They must be the same value — a UI built with a
# different id produces tokens the API will reject.
#
# Create it at console.cloud.google.com: OAuth client → Web application, with
# https://agentpit.dev and http://localhost:5173 as authorised JavaScript
# origins and no redirect URI. Publish the consent screen: while it is in
# Testing, only listed test users can sign in. A client id is public; there is
# no client secret in this flow.
#
# Leave both unset and the feature is absent: no button, and POST /auth/google
# answers 503.
GOOGLE_CLIENT_ID=
VITE_GOOGLE_CLIENT_ID=
```

- [ ] **Step 4: Verify the build actually bakes the id in**

Run, from `ui/`:

```bash
VITE_GOOGLE_CLIENT_ID=verify-only.apps.googleusercontent.com npx vite build
grep -rl "verify-only.apps.googleusercontent.com" dist/assets | head -1
```

Expected: `grep` names one bundle file — the id reached the built JavaScript.

Then confirm the off state still builds:

```bash
npm run build
! grep -rq "verify-only.apps.googleusercontent.com" dist/assets && echo "off state clean"
```

Expected: `off state clean`.

- [ ] **Step 5: Commit**

```bash
git add ui/.env.example .env.example deploy/Dockerfile.ui \
        deploy/docker-compose.prod.yml deploy/env.prod.example
git commit -m "chore(deploy): carry the google client id to the api and the ui build"
```

---

## After the last task

1. Full backend suite: `.venv/bin/python -m pytest tests -q
   --ignore=tests/onchain`.
2. Full UI suite, from `ui/`: `npx vitest run && npm run typecheck && npm run
   lint && npm run build`.
3. Merge `google-signin` into `main`, then fast-forward `mvp` to match — the two
   branches are kept identical.
4. **Do not deploy until the operator has a client id.** Deploying without one
   ships the off state, which is safe but pointless. With one: put
   `GOOGLE_CLIENT_ID` and `VITE_GOOGLE_CLIENT_ID` in the prod `.env`, then
   `docker compose -f deploy/docker-compose.prod.yml up -d --build api caddy` —
   the UI change is baked into the caddy image, and the API change needs the api
   image rebuilt.
5. First live check: sign in with a Google account that has never used agentpit
   (expect a new funded account with a generated handle), then sign in again
   (expect the same wallet address, and no welcome toast).

## Known follow-ups, deliberately not in this plan

- **Settings still shows a change-password form to a Google account.** It now
  fails with a truthful 400 rather than a confusing 404. Hiding it would need a
  `has_password` field on `UserPublic`, which is API surface this feature does
  not otherwise need.
- **Unlinking Google from an account** — out of scope per the spec.
- **A second provider** — the shape generalises, but each one is its own consent
  screen and its own decisions.
