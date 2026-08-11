# WorkOS AuthKit — foundation (plan 1 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make agentpit able to accept WorkOS AuthKit sessions and carry every existing account's WorkOS identity — without changing how anybody signs in yet.

**Architecture:** A WorkOS client behind a Protocol so no test reaches the network; AuthKit access tokens verified against the published JWKS and accepted *alongside* the existing `JwtCoder` tokens; a `WORKOS_USER_ID` column linking our row to theirs; a one-shot idempotent script that imports the existing users with their bcrypt hashes intact.

**Tech Stack:** Python 3.13, FastAPI, psycopg3/Postgres, PyJWT (already a dependency, and its `PyJWKClient` does the JWKS fetching), the `workos` Python SDK.

**Scope:** This is plan 1 of 2, covering steps 1–3 of `docs/superpowers/specs/2026-08-11-workos-authkit-design.md`. Everything here is additive: after it ships, both token kinds authenticate and every sign-in flow is byte-identical to today. Plan 2 moves registration, sign-in, verification and Google onto AuthKit and then removes the old scheme.

## Global Constraints

- Read the spec first: `docs/superpowers/specs/2026-08-11-workos-authkit-design.md`. It is the source of truth.
- Backend tests: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`. **NEVER source `.env`** — the conftest setdefaults get defeated and the live-sync tests flake. The local anvil must be running.
- **No test may reach the network.** The WorkOS client is a Protocol with a fake in tests; JWKS fetching is injected, never live.
- `X-API-Key` authentication is untouched by this plan. Bots trading through it must keep working.
- Nothing is deleted in this plan. `JwtCoder`, `PASSWORD_HASH`, and the Google verifier all stay and keep working.
- Commit messages must NOT carry a `Co-Authored-By` trailer.
- Follow the surrounding code's comment style: comments explain *why*, and cite measured facts where they exist.

---

### Task 1: The WorkOS client, behind a Protocol

**Files:**
- Modify: `requirements.txt`
- Modify: `agentpit/config.py`
- Create: `agentpit/auth/workos_client.py`
- Create: `tests/auth/test_workos_client.py`

**Interfaces:**
- Consumes: `Settings` from `agentpit/config.py`.
- Produces: `WorkOsClient` (Protocol), `RealWorkOsClient`, `FakeWorkOsClient`, `WorkOsUser`, and `build_workos_client(settings) -> WorkOsClient | None`. Later tasks and plan 2 depend on these exact names.

- [ ] **Step 1: Install the SDK and pin what you actually got**

```bash
cd /Users/yavorsky/dev/agentpit
.venv/bin/pip install workos
.venv/bin/pip show workos | head -2
```

The code below targets the v6 client API (`WorkOSClient`, `client.user_management`, `PasswordHashed`). If `pip show` reports a major version other than 6, **stop and report it** rather than adapting the code — the method surface changed at v6 and guessing would produce code that imports cleanly and fails at runtime.

Append the exact version you installed to `requirements.txt`, beside the other auth dependencies:

```
workos==<the version pip reported>
```

- [ ] **Step 2: Write the failing test**

Create `tests/auth/test_workos_client.py`:

```python
from agentpit.auth.workos_client import (
    FakeWorkOsClient,
    WorkOsUser,
    build_workos_client,
)
from agentpit.config import Settings


def _settings(**over) -> Settings:
    base = {
        "workos_api_key": "sk_test_123",
        "workos_client_id": "client_123",
        "workos_authkit_domain": "https://example.authkit.app",
    }
    base.update(over)
    return Settings(**base)  # type: ignore[arg-type]


def test_build_returns_none_when_unconfigured():
    # An absent key means the feature is simply not present, exactly as
    # GOOGLE_CLIENT_ID behaves. It must not raise at import or startup.
    assert build_workos_client(_settings(workos_api_key="")) is None


def test_build_returns_a_client_when_configured():
    assert build_workos_client(_settings()) is not None


def test_fake_creates_and_finds_users():
    fake = FakeWorkOsClient()
    created = fake.create_user(email="a@b.com", password_hash="$2b$12$abc")
    assert isinstance(created, WorkOsUser)
    assert created.email == "a@b.com"
    assert fake.find_user_by_email("a@b.com") is not None
    assert fake.find_user_by_email("nobody@b.com") is None


def test_fake_create_is_idempotent_on_email():
    # The migration script runs this against every existing row and may be
    # re-run; a second create for the same address must return the first user
    # rather than a duplicate identity.
    fake = FakeWorkOsClient()
    first = fake.create_user(email="a@b.com", password_hash=None)
    second = fake.create_user(email="a@b.com", password_hash=None)
    assert first.workos_user_id == second.workos_user_id
```

- [ ] **Step 3: Run it and watch it fail**

```bash
.venv/bin/python -m pytest tests/auth/test_workos_client.py -q
```

Expected: `ModuleNotFoundError: No module named 'agentpit.auth.workos_client'`.

- [ ] **Step 4: Add the settings**

In `agentpit/config.py`, beside `google_client_id`:

```python
    # WorkOS AuthKit. An absent api key means the feature is simply not
    # present, the same shape as GOOGLE_CLIENT_ID above -- nothing raises at
    # startup and every AuthKit path answers as unconfigured. The authkit
    # domain is the issuer that signs access tokens and publishes the JWKS;
    # it is NOT api.workos.com.
    workos_api_key: str = Field(default="", validation_alias="WORKOS_API_KEY")
    workos_client_id: str = Field(default="", validation_alias="WORKOS_CLIENT_ID")
    workos_authkit_domain: str = Field(
        default="", validation_alias="WORKOS_AUTHKIT_DOMAIN"
    )
```

- [ ] **Step 5: Write the client**

Create `agentpit/auth/workos_client.py`:

```python
"""The WorkOS surface agentpit uses, and nothing more.

A Protocol rather than the SDK client itself, for one reason: every test in
this repo runs offline, and a service that reaches out to api.workos.com from
a unit test is a test that fails on a train. `FakeWorkOsClient` is the double
every test uses; `RealWorkOsClient` is the only place the SDK is touched.

The surface is deliberately narrow. Plan 2 widens it; this plan needs exactly
what the migration script needs.
"""
from dataclasses import dataclass
from typing import Protocol

from agentpit.config import Settings


@dataclass(frozen=True)
class WorkOsUser:
    workos_user_id: str
    email: str
    email_verified: bool


class WorkOsClient(Protocol):
    def create_user(
        self, *, email: str, password_hash: str | None
    ) -> WorkOsUser:
        """Create the user, or return the existing one for this address.

        `password_hash` is a bcrypt hash lifted straight out of our `users`
        table -- WorkOS accepts foreign hashes on create, so an imported
        account signs in with the password it already had and nobody is asked
        to reset anything. `None` is the Google-sourced account that never had
        one.
        """
        ...

    def find_user_by_email(self, email: str) -> WorkOsUser | None:
        ...


class RealWorkOsClient:
    def __init__(self, api_key: str, client_id: str):
        from workos import WorkOSClient

        self._client = WorkOSClient(api_key=api_key, client_id=client_id)

    def create_user(self, *, email: str, password_hash: str | None) -> WorkOsUser:
        from workos.types.user_management import PasswordHashed

        existing = self.find_user_by_email(email)
        if existing is not None:
            # Idempotent by construction: the migration script is re-runnable
            # and a second call for the same address must not mint a second
            # identity for one person.
            return existing
        password = (
            PasswordHashed(password_hash=password_hash, password_hash_type="bcrypt")
            if password_hash
            else None
        )
        created = self._client.user_management.create_user(
            email=email,
            email_verified=True,
            password=password,
        )
        return WorkOsUser(
            workos_user_id=created.id,
            email=created.email,
            email_verified=bool(created.email_verified),
        )

    def find_user_by_email(self, email: str) -> WorkOsUser | None:
        page = self._client.user_management.list_users(email=email, limit=1)
        for user in page.data:
            return WorkOsUser(
                workos_user_id=user.id,
                email=user.email,
                email_verified=bool(user.email_verified),
            )
        return None


class FakeWorkOsClient:
    """In-memory double with the same contract, including the idempotency."""

    def __init__(self) -> None:
        self._by_email: dict[str, WorkOsUser] = {}
        self._next = 1

    def create_user(self, *, email: str, password_hash: str | None) -> WorkOsUser:
        existing = self.find_user_by_email(email)
        if existing is not None:
            return existing
        user = WorkOsUser(
            workos_user_id=f"user_fake_{self._next}",
            email=email,
            email_verified=True,
        )
        self._next += 1
        self._by_email[email.lower()] = user
        return user

    def find_user_by_email(self, email: str) -> WorkOsUser | None:
        return self._by_email.get(email.lower())


def build_workos_client(settings: Settings) -> WorkOsClient | None:
    """The configured client, or None when WorkOS is not set up.

    None is a first-class answer, not a failure: an environment without
    WORKOS_API_KEY is every developer machine until the account exists, and
    startup must not depend on it.
    """
    if not settings.workos_api_key or not settings.workos_client_id:
        return None
    return RealWorkOsClient(settings.workos_api_key, settings.workos_client_id)
```

- [ ] **Step 6: Create the test package marker if it is missing**

```bash
ls tests/auth/__init__.py 2>/dev/null || (mkdir -p tests/auth && touch tests/auth/__init__.py)
```

- [ ] **Step 7: Run the tests**

```bash
.venv/bin/python -m pytest tests/auth/test_workos_client.py -q
```

Expected: 4 passed.

- [ ] **Step 8: Run the whole suite**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
```

Expected: green. Report the exact summary line.

- [ ] **Step 9: Commit**

```bash
git add requirements.txt agentpit/config.py agentpit/auth/workos_client.py tests/auth/
git commit -m "feat(auth): the WorkOS surface agentpit uses, behind a protocol"
```

---

### Task 2: Verify AuthKit access tokens against the JWKS

**Files:**
- Create: `agentpit/auth/authkit_tokens.py`
- Create: `tests/auth/test_authkit_tokens.py`

**Interfaces:**
- Consumes: `Settings.workos_authkit_domain`, `Settings.workos_client_id` from Task 1.
- Produces: `AuthKitVerifier` with `verify(token: str) -> str` returning the WorkOS user id (`sub`), raising `InvalidCredentialsError` on any failure. Task 3 and plan 2 depend on this exact name and signature.

- [ ] **Step 1: Write the failing test**

Create `tests/auth/test_authkit_tokens.py`. It signs its own tokens with a generated RSA key and hands the verifier a key-resolver, so nothing fetches a JWKS over the network:

```python
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from agentpit.auth.authkit_tokens import AuthKitVerifier
from agentpit.domain.exceptions import InvalidCredentialsError

ISSUER = "https://example.authkit.app"
AUDIENCE = "client_123"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key=_KEY, *, sub="user_01", iss=ISSUER, aud=AUDIENCE, exp_delta=3600):
    now = int(time.time())
    return jwt.encode(
        {"sub": sub, "iss": iss, "aud": aud, "iat": now, "exp": now + exp_delta},
        key,
        algorithm="RS256",
    )


def _verifier() -> AuthKitVerifier:
    # The resolver stands in for the remote JWKS: same contract, no network.
    return AuthKitVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        key_resolver=lambda _token: _KEY.public_key(),
    )


def test_valid_token_returns_the_workos_user_id():
    assert _verifier().verify(_token(sub="user_abc")) == "user_abc"


def test_token_signed_by_an_unknown_key_is_rejected():
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(_token(key=_OTHER_KEY))


def test_wrong_issuer_is_rejected():
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(_token(iss="https://evil.example"))


def test_wrong_audience_is_rejected():
    # Without this check a token minted for ANOTHER WorkOS application, signed
    # by the same provider and verifying perfectly, would authenticate here.
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(_token(aud="client_someone_else"))


def test_expired_token_is_rejected():
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(_token(exp_delta=-1))


def test_garbage_is_rejected_rather_than_raising_something_else():
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify("not-a-jwt")


def test_token_without_sub_is_rejected():
    now = int(time.time())
    token = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 60},
        _KEY,
        algorithm="RS256",
    )
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(token)
```

- [ ] **Step 2: Run it and watch it fail**

```bash
.venv/bin/python -m pytest tests/auth/test_authkit_tokens.py -q
```

Expected: `ModuleNotFoundError: No module named 'agentpit.auth.authkit_tokens'`.

- [ ] **Step 3: Write the verifier**

Create `agentpit/auth/authkit_tokens.py`:

```python
"""Verification of AuthKit access tokens.

AuthKit signs its access tokens asymmetrically and publishes the public keys
at `<authkit-domain>/oauth2/jwks`. That is the whole difference from
`JwtCoder`, which signs symmetrically with a secret we hold: here we can only
verify, never mint, which is the point.

Two claims are checked beyond the signature, and neither is optional.
`issuer` pins the tokens to our AuthKit domain. `audience` pins them to our
client id -- without it, a token minted for a DIFFERENT WorkOS application
would carry a valid signature from the same provider and authenticate here.
"""
from collections.abc import Callable
from typing import Any

import jwt

from agentpit.domain.exceptions import InvalidCredentialsError

KeyResolver = Callable[[str], Any]


def remote_jwks_resolver(authkit_domain: str) -> KeyResolver:
    """Resolve signing keys from the live JWKS, with PyJWT's own caching.

    `PyJWKClient` caches keys and refetches on an unknown `kid`, so a key
    rotation upstream costs one extra request rather than an outage.
    """
    client = jwt.PyJWKClient(f"{authkit_domain.rstrip('/')}/oauth2/jwks")
    return lambda token: client.get_signing_key_from_jwt(token).key


class AuthKitVerifier:
    def __init__(
        self, *, issuer: str, audience: str, key_resolver: KeyResolver
    ):
        self._issuer = issuer
        self._audience = audience
        self._resolve = key_resolver

    def verify(self, token: str) -> str:
        """The WorkOS user id this token belongs to.

        Every failure is one failure: a bad signature, a wrong audience, an
        expired token and outright garbage all raise `InvalidCredentialsError`,
        because a caller that could tell them apart could use the difference to
        probe.
        """
        try:
            key = self._resolve(token)
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
            )
        except Exception as exc:
            raise InvalidCredentialsError("invalid session") from exc
        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise InvalidCredentialsError("invalid session")
        return sub
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/auth/test_authkit_tokens.py -q
```

Expected: 7 passed.

- [ ] **Step 5: Run the whole suite**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
```

Expected: green. Report the exact summary line.

- [ ] **Step 6: Commit**

```bash
git add agentpit/auth/authkit_tokens.py tests/auth/test_authkit_tokens.py
git commit -m "feat(auth): verify AuthKit access tokens against the published JWKS"
```

---

### Task 3: `WORKOS_USER_ID` on users, and the lookup

**Files:**
- Modify: `agentpit/db/table_create.py` (`create_users_table` / `_migrate_users_table`)
- Modify: `agentpit/db/table_read.py`
- Modify: `agentpit/db/table_write.py`
- Create: `tests/db/test_workos_user_id.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `TableRead.get_user_by_workos_id(conn, workos_user_id) -> User | None` and `TableWrite.set_workos_user_id(conn, user_id, workos_user_id) -> bool`. Task 4 depends on both.

- [ ] **Step 1: Write the failing test**

Create `tests/db/test_workos_user_id.py`. There is no shared connection fixture in this repo — each test builds its own `DbSession`, and the autouse `_isolated_db_session` fixture in `tests/conftest.py` truncates every table between tests. This is the idiom used by `tests/db/test_cost_basis.py`; match it exactly.

```python
from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite


def test_set_and_read_back():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        user_id, _acct, _api_key = TableWrite.create_user(
            conn, email="w@example.com", password_hash="$2b$12$x", handle=None
        )
        assert TableRead.get_user_by_workos_id(conn, "user_01") is None
        assert TableWrite.set_workos_user_id(conn, user_id, "user_01") is True

    with db.read() as conn:
        found = TableRead.get_user_by_workos_id(conn, "user_01")
    assert found is not None
    assert found.user_id == user_id


def test_set_on_a_missing_row_reports_false():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        assert TableWrite.set_workos_user_id(conn, "nope", "user_02") is False


def test_lookup_is_exact_not_fuzzy():
    # A WorkOS id is an opaque token, not an address: it must match exactly or
    # not at all. A LIKE or case-folded lookup here would let one identity
    # answer for another.
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        user_id, _acct, _api_key = TableWrite.create_user(
            conn, email="x@example.com", password_hash=None, handle=None
        )
        TableWrite.set_workos_user_id(conn, user_id, "user_ABC")

    with db.read() as conn:
        assert TableRead.get_user_by_workos_id(conn, "user_abc") is None
        assert TableRead.get_user_by_workos_id(conn, "user_ABC") is not None
```

- [ ] **Step 2: Run it and watch it fail**

```bash
.venv/bin/python -m pytest tests/db/test_workos_user_id.py -q
```

Expected: failure on the missing column or the missing method.

- [ ] **Step 3: Add the column**

In `agentpit/db/table_create.py`, add `WORKOS_USER_ID TEXT` to the `CREATE TABLE users` body (after `GOOGLE_SUB`), add `("WORKOS_USER_ID", "TEXT")` to the `additions` list in `_migrate_users_table` so existing databases gain it, and add the uniqueness index beside the existing email index:

```python
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_workos_user_id "
            "ON users(WORKOS_USER_ID)"
        )
```

A partial index is not needed: Postgres treats NULLs as distinct in a unique index, so every not-yet-migrated row coexists happily while no two rows can ever share one WorkOS identity.

- [ ] **Step 4: Add the reader**

In `agentpit/db/table_read.py`, add `WORKOS_USER_ID` to `_USER_COLS`, add the field to whatever `_row_to_user` builds, and add:

```python
    @staticmethod
    def get_user_by_workos_id(
        db: psycopg.Connection, workos_user_id: str
    ) -> "User | None":
        """The account this WorkOS identity belongs to, matched exactly.

        Deliberately not case-insensitive, unlike `get_user_by_email_ci`: an
        address is something a person types and gets wrong, while this is an
        opaque id we stored ourselves.
        """
        row = db.execute(
            f"SELECT {TableRead._USER_COLS} FROM users WHERE WORKOS_USER_ID = %s",
            (workos_user_id,),
        ).fetchone()
        return TableRead._row_to_user(row) if row else None
```

Add `workos_user_id: str | None = None` to the `User` model in `agentpit/datastructures/user.py` so the row maps cleanly.

- [ ] **Step 5: Add the writer**

In `agentpit/db/table_write.py`:

```python
    @staticmethod
    def set_workos_user_id(
        db: psycopg.Connection, user_id: str, workos_user_id: str
    ) -> bool:
        """Link this account to its WorkOS identity. False when no row matched."""
        cur = db.execute(
            "UPDATE users SET WORKOS_USER_ID = %s WHERE USER_ID = %s",
            (workos_user_id, user_id),
        )
        return cur.rowcount > 0
```

- [ ] **Step 6: Run the tests**

```bash
.venv/bin/python -m pytest tests/db/test_workos_user_id.py -q
```

Expected: 3 passed.

- [ ] **Step 7: Run the whole suite**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
```

Expected: green. The `User` model gained an optional field, so watch for any test asserting an exact model dump. Report the exact summary line.

- [ ] **Step 8: Commit**

```bash
git add agentpit/db/ agentpit/datastructures/user.py tests/db/test_workos_user_id.py
git commit -m "feat(db): link a user row to its WorkOS identity"
```

---

### Task 4: The migration script

**Files:**
- Create: `scripts/migrate_users_to_workos.py`
- Create: `tests/test_migrate_users_to_workos.py`

**Interfaces:**
- Consumes: `FakeWorkOsClient`, `WorkOsClient`, `build_workos_client` (Task 1); `TableRead.get_user_by_workos_id`, `TableWrite.set_workos_user_id` (Task 3).
- Produces: `migrate_users(db, client, *, dry_run: bool = False) -> MigrationReport` — a pure-ish function the test drives directly, plus a `__main__` wrapper.

- [ ] **Step 1: Write the failing test**

Create `tests/test_migrate_users_to_workos.py`:

```python
from agentpit.auth.workos_client import FakeWorkOsClient
from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from scripts.migrate_users_to_workos import migrate_users


def _make_user(conn, email, password_hash):
    user_id, _acct, _api_key = TableWrite.create_user(
        conn, email=email, password_hash=password_hash, handle=None
    )
    return user_id


def test_imports_a_password_account_with_its_hash():
    db = DbSession(Settings().database_url)
    fake = FakeWorkOsClient()
    with db.write() as conn:
        user_id = _make_user(conn, "a@example.com", "$2b$12$realhash")
        report = migrate_users(conn, fake)

    assert report.migrated == 1
    created = fake.find_user_by_email("a@example.com")
    assert created is not None
    with db.read() as conn:
        linked = TableRead.get_user_by_workos_id(conn, created.workos_user_id)
    assert linked is not None and linked.user_id == user_id


def test_a_google_account_without_a_password_still_migrates():
    db = DbSession(Settings().database_url)
    fake = FakeWorkOsClient()
    with db.write() as conn:
        _make_user(conn, "g@example.com", None)
        report = migrate_users(conn, fake)

    assert report.migrated == 1
    assert fake.find_user_by_email("g@example.com") is not None


def test_running_twice_changes_nothing_the_second_time():
    db = DbSession(Settings().database_url)
    fake = FakeWorkOsClient()
    with db.write() as conn:
        _make_user(conn, "a@example.com", "$2b$12$realhash")
        first = migrate_users(conn, fake)
    with db.write() as conn:
        second = migrate_users(conn, fake)

    assert first.migrated == 1
    # Already linked, so the second pass has nothing to do -- this is what
    # makes the script safe to re-run after a partial failure.
    assert second.migrated == 0
    assert second.skipped == 1


def test_dry_run_writes_nothing():
    db = DbSession(Settings().database_url)
    fake = FakeWorkOsClient()
    with db.write() as conn:
        user_id = _make_user(conn, "a@example.com", "$2b$12$realhash")
        report = migrate_users(conn, fake, dry_run=True)

    assert report.migrated == 1  # what it WOULD do
    assert fake.find_user_by_email("a@example.com") is None
    with db.read() as conn:
        assert TableRead.get_user_by_userid(conn, user_id).workos_user_id is None


def test_one_failure_does_not_stop_the_rest():
    class Exploding(FakeWorkOsClient):
        def create_user(self, *, email, password_hash):
            if email == "bad@example.com":
                raise RuntimeError("upstream said no")
            return super().create_user(email=email, password_hash=password_hash)

    db = DbSession(Settings().database_url)
    with db.write() as conn:
        _make_user(conn, "bad@example.com", "$2b$12$h")
        _make_user(conn, "good@example.com", "$2b$12$h")
        report = migrate_users(conn, Exploding())

    # 17 accounts and one bad address must not cost the other 16 their identity.
    assert report.migrated == 1
    assert report.failed == 1
```

- [ ] **Step 2: Run it and watch it fail**

```bash
.venv/bin/python -m pytest tests/test_migrate_users_to_workos.py -q
```

Expected: `ModuleNotFoundError: No module named 'scripts.migrate_users_to_workos'`.

- [ ] **Step 3: Write the script**

Create `scripts/migrate_users_to_workos.py`:

```python
"""Give every existing account a WorkOS identity, keeping its password.

WorkOS accepts a foreign bcrypt hash on user creation, so an imported account
signs in with the password it already had and nobody is asked to reset
anything. That is the whole reason this is a script and not an email to 17
people.

Idempotent by two mechanisms, because it will be re-run: a row that already
carries WORKOS_USER_ID is skipped outright, and `create_user` returns the
existing WorkOS user for an address rather than minting a second one. A failure
on one account is logged and the run continues -- one unusable address must not
cost the others their identity.

    .venv/bin/python -m scripts.migrate_users_to_workos --dry-run
    .venv/bin/python -m scripts.migrate_users_to_workos
"""
import argparse
import logging
import sys
from dataclasses import dataclass

from agentpit.auth.workos_client import WorkOsClient, build_workos_client
from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite

log = logging.getLogger("migrate_users_to_workos")


@dataclass
class MigrationReport:
    migrated: int = 0
    skipped: int = 0
    failed: int = 0


def migrate_users(
    conn, client: WorkOsClient, *, dry_run: bool = False
) -> MigrationReport:
    report = MigrationReport()
    rows = conn.execute(
        "SELECT USER_ID, EMAIL, PASSWORD_HASH, WORKOS_USER_ID FROM users "
        "ORDER BY CREATED_AT"
    ).fetchall()
    for row in rows:
        user_id, email, password_hash, existing = (
            row["USER_ID"], row["EMAIL"], row["PASSWORD_HASH"], row["WORKOS_USER_ID"]
        )
        if existing:
            report.skipped += 1
            continue
        if dry_run:
            log.info("would migrate %s (%s)", email, user_id)
            report.migrated += 1
            continue
        try:
            workos_user = client.create_user(
                email=email, password_hash=password_hash
            )
            if not TableWrite.set_workos_user_id(
                conn, user_id, workos_user.workos_user_id
            ):
                raise RuntimeError(f"no row to link for {user_id}")
        except Exception:
            log.exception("migrating %s failed", email)
            report.failed += 1
            continue
        log.info("migrated %s -> %s", email, workos_user.workos_user_id)
        report.migrated += 1
    return report


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = Settings()  # type: ignore[call-arg]
    client = build_workos_client(settings)
    if client is None:
        log.error("WORKOS_API_KEY / WORKOS_CLIENT_ID are not set")
        return 1

    # create_tables=False: this script is a second writer against a live API,
    # and running the schema creation from here has deadlocked production
    # before (see scripts/backfill_trade_match_kind.py for the same guard).
    db = DbSession(settings.database_url, create_tables=False)
    try:
        with db.write() as conn:
            report = migrate_users(conn, client, dry_run=args.dry_run)
    finally:
        db.close()
    log.info(
        "migrated=%d skipped=%d failed=%d%s",
        report.migrated, report.skipped, report.failed,
        " (dry run)" if args.dry_run else "",
    )
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

Both names above are verified against the current code: `DbSession(dsn, *, create_tables=True, ...)` at `agentpit/db/session.py:23` and `Settings.database_url` at `agentpit/config.py:14`. `scripts/backfill_trade_match_kind.py` is the pattern this follows, including the `create_tables=False` guard.

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/test_migrate_users_to_workos.py -q
```

Expected: 5 passed.

- [ ] **Step 5: Verify the dry run works end to end against a real database**

```bash
.venv/bin/python -m scripts.migrate_users_to_workos --dry-run
```

Expected without WorkOS configured: exits 1 with `WORKOS_API_KEY / WORKOS_CLIENT_ID are not set`. That is the correct behaviour on a machine with no WorkOS account, and is what proves the guard works. Report what you saw.

- [ ] **Step 6: Run the whole suite**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
```

Expected: green. Report the exact summary line.

- [ ] **Step 7: Commit**

```bash
git add scripts/migrate_users_to_workos.py tests/test_migrate_users_to_workos.py
git commit -m "feat(auth): import existing accounts into WorkOS with their passwords"
```

---

## What this plan deliberately does not do

- It does not change how anybody signs in. `register`, `login`, `google_sign_in` and `JwtCoder` are untouched, and the dialog is untouched.
- It does not wire `AuthKitVerifier` into `get_current_user`. The verifier exists and is tested; accepting AuthKit tokens in the request path is the first task of plan 2, where it lands together with something that issues them.
- It does not remove `PASSWORD_HASH` or the Google verifier.

Those are plan 2: `docs/superpowers/specs/2026-08-11-workos-authkit-design.md` steps 4–7.
