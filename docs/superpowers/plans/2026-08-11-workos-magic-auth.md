# WorkOS Magic Auth — sign in with a mailed code (plan 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person types an email address, receives a six-digit code, types it in, and is signed in — creating their account, wallet and on-chain onboarding on the first time through.

**Architecture:** WorkOS Magic Auth issues and mails the code and returns a short-lived access token plus a refresh token. Our backend verifies that token against the JWKS (already built), maps `sub` to a local row via `WORKOS_USER_ID`, and creates the row + wallet + onboarding when there is no match. Nothing is removed: the existing `/register`, `/login` and Google paths keep working alongside.

**Tech Stack:** Python 3.13, FastAPI, psycopg3/Postgres, PyJWT, `httpx`. UI: Vite/React 18/TS.

## Facts established against the live staging environment on 2026-08-11

These were measured, not read. Build against them.

- `POST https://api.workos.com/user_management/magic_auth` with `{"email": ...}` and header `Authorization: Bearer <api key>` returns **201** and a body containing `id`, `user_id`, `email`, **`code`**, `expires_at` (10 minutes out). **It creates the WorkOS user if the address is new**, and WorkOS mails the code. There is no separate sign-up call.
- `POST https://api.workos.com/user_management/authenticate` with `{"client_id", "client_secret", "grant_type": "urn:workos:oauth:grant-type:magic-auth:code", "code", "email"}` returns **200** and `{user, access_token, refresh_token, authentication_method}`. `client_secret` is the API key.
- Refresh: the same endpoint with `{"client_id", "client_secret", "grant_type": "refresh_token", "refresh_token"}` returns the same shape. **The refresh token does NOT rotate** — the old value keeps working, so two concurrent refreshes are harmless.
- The access token lives **300 seconds**. Its claims are `iss` (= `https://api.workos.com/user_management/<client_id>`), `sub`, `sid`, `jti`, `auth_time`, `client_id`, `iat`, `exp`. **There is no `aud`.** `AuthKitVerifier` already handles this; do not change it.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-11-workos-authkit-design.md`. Read it first.
- Backend tests: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`. **NEVER source `.env`.** The local anvil must be running.
- **No test may reach the network.** `FakeWorkOsClient` is the double; extend it in step with the protocol.
- **Nothing is removed in this plan.** `/register`, `/login`, `google_sign_in`, `JwtCoder` and `PASSWORD_HASH` all keep working. Removal is plan 3.
- **`X-API-Key` must keep working unchanged.** Every bot currently trading depends on it.
- UI from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`. `ui/` vitest runs in node with **no `@testing-library/react`** — components cannot be render-tested, so every real decision lives in a pure helper. `tsconfig` has `exactOptionalPropertyTypes`.
- Commit messages must NOT carry a `Co-Authored-By` trailer.
- Comments explain *why*, and cite measured facts. Match the surrounding code, which is heavily commented.

---

### Task 1: Magic Auth on the WorkOS client

**Files:**
- Modify: `agentpit/auth/workos_client.py`
- Modify: `tests/auth/test_workos_client.py`

**Interfaces:**
- Produces: on the `WorkOsClient` protocol — `send_magic_auth_code(email) -> None`, `authenticate_with_code(email, code) -> WorkOsSession`, `refresh_session(refresh_token) -> WorkOsSession`; and the dataclass `WorkOsSession(workos_user_id, email, access_token, refresh_token)`. Tasks 2–5 depend on these names.

- [ ] **Step 1: Write the failing tests**

Append to `tests/auth/test_workos_client.py`. The real client is driven over `httpx.MockTransport`, as the existing tests in that file already do via `_real(handler)` — reuse that helper.

```python
from agentpit.auth.workos_client import WorkOsSession


def test_send_magic_auth_code_posts_the_address():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        return httpx.Response(201, json={
            "id": "magic_auth_01", "user_id": "user_01",
            "email": "a@b.com", "code": "515627",
        })

    _real(handler).send_magic_auth_code("a@b.com")
    assert seen["url"].endswith("/user_management/magic_auth")
    assert '"email": "a@b.com"' in seen["body"].replace("\n", "")


def test_the_returned_code_is_never_exposed():
    # WorkOS returns the code in the create response, which means anyone
    # holding the API key can sign in as anyone without reading email. That is
    # inherent to the key, but the code must not travel any further than this
    # method: `send_magic_auth_code` returns None on purpose.
    resp = {"id": "m", "user_id": "u", "email": "a@b.com", "code": "515627"}
    assert _real(lambda _r: httpx.Response(201, json=resp)).send_magic_auth_code(
        "a@b.com"
    ) is None


def test_authenticate_with_code_returns_a_session():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read().decode())
        return httpx.Response(200, json={
            "user": {"id": "user_01", "email": "a@b.com", "email_verified": True},
            "access_token": "at", "refresh_token": "rt",
            "authentication_method": "MagicAuth",
        })

    session = _real(handler).authenticate_with_code("a@b.com", "515627")
    assert session == WorkOsSession(
        workos_user_id="user_01", email="a@b.com",
        access_token="at", refresh_token="rt",
    )
    # The grant type is a magic string; a typo in it returns a 400 that reads
    # like a bad code, so pin it.
    assert seen["body"]["grant_type"] == (
        "urn:workos:oauth:grant-type:magic-auth:code"
    )
    assert seen["body"]["client_id"] == "client_123"
    assert seen["body"]["client_secret"] == "sk_test_123"
    assert seen["body"]["code"] == "515627"


def test_a_wrong_code_raises_workos_error():
    client = _real(lambda _r: httpx.Response(400, json={"code": "invalid_code"}))
    with pytest.raises(WorkOsError):
        client.authenticate_with_code("a@b.com", "000000")


def test_refresh_session_uses_the_refresh_grant():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read().decode())
        return httpx.Response(200, json={
            "user": {"id": "user_01", "email": "a@b.com", "email_verified": True},
            "access_token": "at2", "refresh_token": "rt2",
        })

    session = _real(handler).refresh_session("rt")
    assert session.access_token == "at2" and session.refresh_token == "rt2"
    assert seen["body"]["grant_type"] == "refresh_token"
    assert seen["body"]["refresh_token"] == "rt"


def test_fake_round_trips_a_code():
    fake = FakeWorkOsClient()
    fake.send_magic_auth_code("a@b.com")
    session = fake.authenticate_with_code("a@b.com", fake.last_code("a@b.com"))
    assert session.email == "a@b.com"
    assert session.workos_user_id == fake.find_user_by_email("a@b.com").workos_user_id


def test_fake_rejects_a_wrong_code():
    fake = FakeWorkOsClient()
    fake.send_magic_auth_code("a@b.com")
    with pytest.raises(WorkOsError):
        fake.authenticate_with_code("a@b.com", "000000")


def test_fake_creates_the_user_on_first_code_like_the_real_api_does():
    fake = FakeWorkOsClient()
    assert fake.find_user_by_email("new@b.com") is None
    fake.send_magic_auth_code("new@b.com")
    assert fake.find_user_by_email("new@b.com") is not None
```

Add `import json` at the top of the test file if it is not already there.

- [ ] **Step 2: Run them and watch them fail**

```bash
.venv/bin/python -m pytest tests/auth/test_workos_client.py -q
```

Expected: `ImportError: cannot import name 'WorkOsSession'`.

- [ ] **Step 3: Extend the client**

In `agentpit/auth/workos_client.py`, add beside `WorkOsUser`:

```python
@dataclass(frozen=True)
class WorkOsSession:
    workos_user_id: str
    email: str
    access_token: str
    refresh_token: str
```

Add to the `WorkOsClient` protocol:

```python
    def send_magic_auth_code(self, email: str) -> None:
        """Mail a six-digit code to this address, creating the user if new.

        Returns nothing on purpose. WorkOS hands the code back in the create
        response -- which means the API key alone is enough to sign in as
        anybody, without reading mail -- and the only defence available to us
        is that the value never leaves this method.
        """
        ...

    def authenticate_with_code(self, email: str, code: str) -> WorkOsSession:
        ...

    def refresh_session(self, refresh_token: str) -> WorkOsSession:
        ...
```

On `RealWorkOsClient`:

```python
    _MAGIC_AUTH_GRANT = "urn:workos:oauth:grant-type:magic-auth:code"

    def send_magic_auth_code(self, email: str) -> None:
        # The response body carries the code. It is deliberately discarded.
        self._request("POST", "/user_management/magic_auth", json={"email": email})

    def _authenticate(self, body: dict) -> WorkOsSession:
        payload = self._request(
            "POST",
            "/user_management/authenticate",
            json={
                "client_id": self._client_id,
                # WorkOS names the API key `client_secret` on this endpoint.
                "client_secret": self._api_key,
                **body,
            },
        )
        return WorkOsSession(
            workos_user_id=payload["user"]["id"],
            email=payload["user"]["email"],
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
        )

    def authenticate_with_code(self, email: str, code: str) -> WorkOsSession:
        return self._authenticate(
            {"grant_type": self._MAGIC_AUTH_GRANT, "code": code, "email": email}
        )

    def refresh_session(self, refresh_token: str) -> WorkOsSession:
        # Measured: WorkOS does NOT rotate the refresh token, so a client that
        # refreshes twice concurrently keeps a working credential either way.
        return self._authenticate(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )
```

`RealWorkOsClient.__init__` currently stores `api_key` only in the header. Keep `self._api_key = api_key` so `_authenticate` can send it as `client_secret`.

On `FakeWorkOsClient`, mirror the contract in memory:

```python
    def send_magic_auth_code(self, email: str) -> None:
        # The real API creates the user on this call; the double must too, or
        # the first-sign-in path is never exercised offline.
        user = self.create_user(email=email, password_hash=None)
        self._codes[email.lower()] = "515627"
        self._sessions += 1

    def last_code(self, email: str) -> str:
        """Test-only: the code the real API would have mailed."""
        return self._codes[email.lower()]

    def authenticate_with_code(self, email: str, code: str) -> WorkOsSession:
        if self._codes.get(email.lower()) != code:
            raise WorkOsError("WorkOS rejected the code")
        user = self.find_user_by_email(email)
        assert user is not None
        return WorkOsSession(
            workos_user_id=user.workos_user_id,
            email=user.email,
            access_token=f"at-{user.workos_user_id}",
            refresh_token=f"rt-{user.workos_user_id}",
        )

    def refresh_session(self, refresh_token: str) -> WorkOsSession:
        if not refresh_token.startswith("rt-"):
            raise WorkOsError("WorkOS rejected the refresh token")
        workos_user_id = refresh_token[3:]
        for user in self._by_email.values():
            if user.workos_user_id == workos_user_id:
                return WorkOsSession(
                    workos_user_id=user.workos_user_id, email=user.email,
                    access_token=f"at-{workos_user_id}",
                    refresh_token=refresh_token,
                )
        raise WorkOsError("WorkOS rejected the refresh token")
```

Initialise `self._codes: dict[str, str] = {}` and `self._sessions = 0` in `FakeWorkOsClient.__init__`.

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/auth/test_workos_client.py -q
```

Expected: all pass.

- [ ] **Step 5: Run the whole suite and commit**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
git add agentpit/auth/workos_client.py tests/auth/test_workos_client.py
git commit -m "feat(auth): magic-auth send, verify and refresh on the WorkOS client"
```

Report the exact pytest summary line.

---

### Task 2: The service that turns a code into an agentpit account

**Files:**
- Create: `agentpit/services/authkit_service.py`
- Create: `tests/services/test_authkit_service.py`

**Interfaces:**
- Consumes: `WorkOsClient`, `WorkOsSession` (Task 1); `AuthKitVerifier` (already built); `AuthService._onboard_new_account`; `TableRead.get_user_by_workos_id`; `TableWrite.set_workos_user_id`, `TableWrite.create_user`; `pick_handle`.
- Produces: `AuthKitService` with `send_code(email) -> None`, `sign_in(email, code) -> AuthKitSession`, `refresh(refresh_token) -> AuthKitSession`; and `AuthKitSession(user: User, access_token: str, refresh_token: str)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/services/test_authkit_service.py`. Build a real `DbSession(Settings().database_url)` as the neighbouring tests do — there is no shared fixture; the autouse `_isolated_db_session` in `tests/conftest.py` truncates between tests.

```python
import pytest

from agentpit.auth.workos_client import FakeWorkOsClient, WorkOsError
from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.services.authkit_service import AuthKitService


class _Onboarder:
    """Stands in for AuthService._onboard_new_account.

    The real one funds gas, drips collateral and sends three approvals -- a
    second or so of chain round-trips. These tests are about identity, so the
    chain is a spy: what matters is that it is called exactly once per NEW
    account and never for a returning one.
    """

    def __init__(self):
        self.calls = []

    def __call__(self, user_id, acct):
        self.calls.append(user_id)
        with DbSession(Settings().database_url).write() as conn:
            TableWrite.mark_user_onboarded(conn, user_id)
            return TableRead.get_user_by_userid(conn, user_id)


def _service(workos=None, onboarder=None):
    db = DbSession(Settings().database_url)
    return AuthKitService(
        db=db,
        workos=workos or FakeWorkOsClient(),
        onboard=onboarder or _Onboarder(),
    ), db


def test_first_sign_in_creates_the_account_and_onboards_it():
    workos, onboarder = FakeWorkOsClient(), _Onboarder()
    svc, db = _service(workos, onboarder)

    svc.send_code("new@example.com")
    session = svc.sign_in("new@example.com", workos.last_code("new@example.com"))

    assert session.user.email == "new@example.com"
    assert session.user.handle  # generated, never blank
    assert session.access_token and session.refresh_token
    assert onboarder.calls == [session.user.user_id]

    with db.read() as conn:
        linked = TableRead.get_user_by_workos_id(
            conn, workos.find_user_by_email("new@example.com").workos_user_id
        )
    assert linked is not None and linked.user_id == session.user.user_id


def test_a_returning_address_lands_on_the_same_row_without_a_second_wallet():
    # The failure this guards is expensive and silent: a second row means a
    # second wallet, a second onboarding paid for on chain, and a person whose
    # positions have vanished.
    workos, onboarder = FakeWorkOsClient(), _Onboarder()
    svc, _db = _service(workos, onboarder)

    svc.send_code("a@example.com")
    first = svc.sign_in("a@example.com", workos.last_code("a@example.com"))
    svc.send_code("a@example.com")
    second = svc.sign_in("a@example.com", workos.last_code("a@example.com"))

    assert first.user.user_id == second.user.user_id
    assert first.user.eth_address == second.user.eth_address
    assert onboarder.calls == [first.user.user_id]  # onboarded once, not twice


def test_an_account_migrated_by_workos_user_id_is_found_not_recreated():
    # Plan 1's migration script populated WORKOS_USER_ID for the existing
    # accounts. Those people must sign in to their own rows.
    workos, onboarder = FakeWorkOsClient(), _Onboarder()
    svc, db = _service(workos, onboarder)
    with db.write() as conn:
        user_id, _acct, _key = TableWrite.create_user(
            conn, email="old@example.com", password_hash="$2b$12$x", handle=None
        )
    created = workos.create_user(email="old@example.com", password_hash=None)
    with db.write() as conn:
        TableWrite.set_workos_user_id(conn, user_id, created.workos_user_id)

    workos.send_magic_auth_code("old@example.com")
    session = svc.sign_in("old@example.com", workos.last_code("old@example.com"))

    assert session.user.user_id == user_id
    assert onboarder.calls == []  # already had a wallet


def test_a_wrong_code_creates_nothing():
    workos, onboarder = FakeWorkOsClient(), _Onboarder()
    svc, db = _service(workos, onboarder)
    svc.send_code("a@example.com")

    with pytest.raises(WorkOsError):
        svc.sign_in("a@example.com", "000000")

    # The whole point of the design: an address that never answers costs us
    # no row, no wallet and no gas.
    with db.read() as conn:
        assert TableRead.get_user_by_email(conn, "a@example.com") is None
    assert onboarder.calls == []


def test_refresh_returns_the_same_account():
    workos = FakeWorkOsClient()
    svc, _db = _service(workos)
    svc.send_code("a@example.com")
    first = svc.sign_in("a@example.com", workos.last_code("a@example.com"))

    again = svc.refresh(first.refresh_token)
    assert again.user.user_id == first.user.user_id
    assert again.access_token


def test_refresh_for_an_identity_with_no_local_row_is_refused():
    # A valid WorkOS session whose `sub` matches nothing here must not
    # silently mint an account -- account creation belongs to sign_in alone.
    workos = FakeWorkOsClient()
    svc, _db = _service(workos)
    created = workos.create_user(email="ghost@example.com", password_hash=None)
    with pytest.raises(Exception):
        svc.refresh(f"rt-{created.workos_user_id}")
```

- [ ] **Step 2: Run them and watch them fail**

```bash
.venv/bin/python -m pytest tests/services/test_authkit_service.py -q
```

Expected: `ModuleNotFoundError: No module named 'agentpit.services.authkit_service'`.

- [ ] **Step 3: Write the service**

Create `agentpit/services/authkit_service.py`:

```python
"""Turning a WorkOS identity into an agentpit account.

WorkOS proves that somebody owns an email address. Everything that makes the
account an agentpit account -- the wallet, its private key, the API key, the
handle, the on-chain onboarding -- is made here, on the first successful
sign-in and never again.

There is no registration endpoint and no registration step. A person who has
never been here and a person who signs in daily take the same path; the only
difference is whether `WORKOS_USER_ID` already matches a row.
"""
import logging
from dataclasses import dataclass

from agentpit.datastructures.user import User
from agentpit.db.session import DbSession
from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite
from agentpit.domain.exceptions import InvalidCredentialsError
from agentpit.domain.handles import pick_handle
from agentpit.auth.workos_client import WorkOsClient, WorkOsSession

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthKitSession:
    user: User
    access_token: str
    refresh_token: str


class AuthKitService:
    def __init__(self, *, db: DbSession, workos: WorkOsClient, onboard):
        self._db = db
        self._workos = workos
        # `AuthService._onboard_new_account` -- injected rather than imported so
        # the chain stays out of these tests, and so the two services do not
        # depend on each other's construction.
        self._onboard = onboard

    def send_code(self, email: str) -> None:
        self._workos.send_magic_auth_code(email)

    def sign_in(self, email: str, code: str) -> AuthKitSession:
        session = self._workos.authenticate_with_code(email, code)
        return AuthKitSession(
            user=self._resolve_account(session, create=True),
            access_token=session.access_token,
            refresh_token=session.refresh_token,
        )

    def refresh(self, refresh_token: str) -> AuthKitSession:
        session = self._workos.refresh_session(refresh_token)
        return AuthKitSession(
            # `create=False`: a refresh proves a session is alive, not that a
            # person just proved ownership of an address. Minting an account
            # here would put a wallet behind a credential that never passed
            # through sign_in.
            user=self._resolve_account(session, create=False),
            access_token=session.access_token,
            refresh_token=session.refresh_token,
        )

    def _resolve_account(self, session: WorkOsSession, *, create: bool) -> User:
        with self._db.read() as conn:
            user = TableRead.get_user_by_workos_id(conn, session.workos_user_id)
        if user is not None:
            return user
        if not create:
            raise InvalidCredentialsError("invalid session")
        return self._create_account(session)

    def _create_account(self, session: WorkOsSession) -> User:
        with self._db.write() as conn:
            # An address that predates WORKOS_USER_ID -- an account the
            # migration missed, or one made before this shipped. Linking beats
            # creating: a second row is a second wallet and a person whose
            # positions have disappeared. Case-insensitive for the same reason
            # `get_user_by_email_ci` exists: WorkOS reports a normalised
            # address, ours was stored as typed.
            existing = TableRead.get_user_by_email_ci(conn, session.email)
            if existing is not None:
                TableWrite.set_workos_user_id(
                    conn, existing.user_id, session.workos_user_id
                )
                return existing.model_copy(
                    update={"workos_user_id": session.workos_user_id}
                )
            handle = pick_handle(
                taken=lambda candidate: TableRead.handle_taken(conn, candidate)
            )
            user_id, acct, _api_key = TableWrite.create_user(
                conn, email=session.email, password_hash=None, handle=handle
            )
            TableWrite.set_workos_user_id(conn, user_id, session.workos_user_id)

        # Outside the transaction: onboarding is ~a second of chain round-trips
        # and must not hold a write lock, exactly as AuthService.register does it.
        return self._onboard(user_id, acct)
```

- [ ] **Step 4: Run the tests, then the suite, then commit**

```bash
.venv/bin/python -m pytest tests/services/test_authkit_service.py -q
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
git add agentpit/services/authkit_service.py tests/services/test_authkit_service.py
git commit -m "feat(auth): a mailed code becomes an agentpit account, wallet and all"
```

Report the exact pytest summary line. If `_Onboarder` needs a different signature than `(user_id, acct)` to match `AuthService._onboard_new_account`, match the real one and say so in your report.

---

### Task 3: The three endpoints

**Files:**
- Modify: `agentpit/api/routes/auth.py`
- Modify: `agentpit/api/deps.py`
- Modify: `agentpit/api/app.py` (wire `AuthKitService` into the dependency)
- Modify: `agentpit/datastructures/auth_response.py`
- Create: `agentpit/datastructures/authkit_requests.py`
- Create: `tests/api/test_authkit_routes.py`

**Interfaces:**
- Consumes: `AuthKitService` (Task 2).
- Produces: `POST /auth/code`, `POST /auth/session`, `POST /auth/refresh`; `AuthResponse` gains `refresh_token: str | None = None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_authkit_routes.py`. The pattern in `tests/api/` is `TestClient(app)` against the singleton app from `agentpit.api.main`, with the autouse fixture in `tests/conftest.py` supplying an isolated database. The WorkOS client is swapped through `app.dependency_overrides`, which is why `deps.py` needs the overridable placeholder added in Step 5.

```python
"""Signing in with a mailed code, over the real app."""
import pytest
from fastapi.testclient import TestClient

from agentpit.api import deps
from agentpit.api.main import app
from agentpit.auth.workos_client import FakeWorkOsClient


@pytest.fixture
def workos():
    fake = FakeWorkOsClient()
    app.dependency_overrides[deps.get_workos_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(deps.get_workos_client, None)


def _code(workos: FakeWorkOsClient, email: str) -> str:
    return workos.last_code(email)


def test_post_auth_code_accepts_any_address_with_202(workos):
    with TestClient(app) as client:
        resp = client.post("/auth/code", json={"email": "brand-new@example.com"})
    assert resp.status_code == 202, resp.text


def test_post_auth_code_says_the_same_thing_for_known_and_unknown_addresses(workos):
    # Whether an address has an account must not be inferable here: anybody
    # can post any address. `/register` already leaks existence with its 409,
    # which is no reason to add a second oracle.
    with TestClient(app) as client:
        first = client.post("/auth/code", json={"email": "known@example.com"})
        client.post(
            "/auth/session",
            json={"email": "known@example.com", "code": _code(workos, "known@example.com")},
        )
        again = client.post("/auth/code", json={"email": "known@example.com"})
        stranger = client.post("/auth/code", json={"email": "stranger@example.com"})
    assert first.status_code == again.status_code == stranger.status_code == 202
    assert again.json() == stranger.json()


def test_the_right_code_returns_a_session_and_a_funded_account(workos):
    with TestClient(app) as client:
        client.post("/auth/code", json={"email": "a@example.com"})
        resp = client.post(
            "/auth/session",
            json={"email": "a@example.com", "code": _code(workos, "a@example.com")},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    # The wallet is the thing WorkOS cannot make for us.
    assert body["user"]["eth_address"].startswith("0x")
    assert body["user"]["email"] == "a@example.com"


def test_a_wrong_code_is_401_and_creates_nothing(workos):
    with TestClient(app) as client:
        client.post("/auth/code", json={"email": "b@example.com"})
        resp = client.post(
            "/auth/session", json={"email": "b@example.com", "code": "000000"}
        )
        assert resp.status_code == 401, resp.text
        # Nothing was created, so a correct code afterwards still works.
        ok = client.post(
            "/auth/session",
            json={"email": "b@example.com", "code": _code(workos, "b@example.com")},
        )
    assert ok.status_code == 200, ok.text


def test_a_malformed_code_is_422_and_never_reaches_workos(workos):
    with TestClient(app) as client:
        client.post("/auth/code", json={"email": "c@example.com"})
        resp = client.post(
            "/auth/session", json={"email": "c@example.com", "code": "12345"}
        )
    assert resp.status_code == 422


def test_signing_in_twice_returns_the_same_account(workos):
    with TestClient(app) as client:
        client.post("/auth/code", json={"email": "d@example.com"})
        first = client.post(
            "/auth/session",
            json={"email": "d@example.com", "code": _code(workos, "d@example.com")},
        ).json()
        client.post("/auth/code", json={"email": "d@example.com"})
        second = client.post(
            "/auth/session",
            json={"email": "d@example.com", "code": _code(workos, "d@example.com")},
        ).json()
    assert first["user"]["user_id"] == second["user"]["user_id"]
    assert first["user"]["eth_address"] == second["user"]["eth_address"]


def test_refresh_returns_a_new_access_token_for_the_same_user(workos):
    with TestClient(app) as client:
        client.post("/auth/code", json={"email": "e@example.com"})
        session = client.post(
            "/auth/session",
            json={"email": "e@example.com", "code": _code(workos, "e@example.com")},
        ).json()
        resp = client.post(
            "/auth/refresh", json={"refresh_token": session["refresh_token"]}
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["user_id"] == session["user"]["user_id"]


def test_a_garbage_refresh_token_is_401(workos):
    with TestClient(app) as client:
        resp = client.post("/auth/refresh", json={"refresh_token": "nonsense"})
    assert resp.status_code == 401, resp.text


def test_register_and_login_are_untouched(workos):
    # This plan removes nothing. If these break, the transition has no floor.
    with TestClient(app) as client:
        made = client.post(
            "/register",
            json={"email": "legacy@example.com", "password": "hunter22hunter22"},
        )
        assert made.status_code == 200, made.text
        back = client.post(
            "/login",
            json={"email": "legacy@example.com", "password": "hunter22hunter22"},
        )
    assert back.status_code == 200, back.text
    assert back.json()["access_token"]


def test_the_routes_answer_503_when_workos_is_not_configured():
    # Every developer machine before the account existed, and any deployment
    # that forgets the keys. It must be an obvious 503, not a 500.
    app.dependency_overrides[deps.get_workos_client] = lambda: None
    try:
        with TestClient(app) as client:
            resp = client.post("/auth/code", json={"email": "f@example.com"})
        assert resp.status_code == 503, resp.text
    finally:
        app.dependency_overrides.pop(deps.get_workos_client, None)
```

- [ ] **Step 2: Run them and watch them fail**

- [ ] **Step 3: Add the request models**

Create `agentpit/datastructures/authkit_requests.py`:

```python
from pydantic import BaseModel, EmailStr, Field


class SendCodeRequest(BaseModel):
    email: EmailStr


class CodeSignInRequest(BaseModel):
    email: EmailStr
    # Six digits, as WorkOS issues them. Validated here so an obviously
    # malformed code costs a 422 rather than a round-trip to WorkOS.
    code: str = Field(pattern=r"^\d{6}$")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)
```

- [ ] **Step 4: Extend `AuthResponse`**

In `agentpit/datastructures/auth_response.py`, add to `AuthResponse`:

```python
    # Present only on the AuthKit paths. The legacy `/register` and `/login`
    # issue a 24-hour JwtCoder token with nothing to refresh, so they leave
    # this null rather than growing a second response model.
    refresh_token: str | None = None
```

- [ ] **Step 5: Add the routes**

In `agentpit/api/routes/auth.py`:

```python
@router.post("/auth/code", status_code=202)
def send_auth_code(payload: SendCodeRequest, service: AuthKitServiceDep) -> dict:
    """Mail a six-digit code to this address.

    Always 202, whether or not the address has an account here: the reply must
    not tell a stranger who is registered. WorkOS creates the user on this call
    and mails the code; nothing is created on our side until the code comes
    back.
    """
    service.send_code(payload.email)
    return {"status": "sent"}


@router.post("/auth/session", response_model=AuthResponse)
def sign_in_with_code(
    payload: CodeSignInRequest, service: AuthKitServiceDep
) -> AuthResponse:
    session = service.sign_in(payload.email, payload.code)
    return AuthResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        user=UserPublic.model_validate(session.user.model_dump()),
    )


@router.post("/auth/refresh", response_model=AuthResponse)
def refresh_session(
    payload: RefreshRequest, service: AuthKitServiceDep
) -> AuthResponse:
    session = service.refresh(payload.refresh_token)
    return AuthResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        user=UserPublic.model_validate(session.user.model_dump()),
    )
```

In `agentpit/api/deps.py`, add an overridable placeholder beside `get_google_verifier` (the tests above swap it):

```python
def get_workos_client() -> "WorkOsClient | None":
    raise RuntimeError("get_workos_client has not been overridden by the app factory")
```

and an `AuthKitServiceDep` that builds the service from it, following the pattern the other `*ServiceDep` annotations use. In `agentpit/api/app.py`, override `get_workos_client` with `build_workos_client(settings)` where the other placeholders are overridden, and construct `AuthKitService` with `auth_service._onboard_new_account` as its `onboard`.

**A `WorkOsError` must map to 401, not 500.** Check `agentpit/api/exception_handlers.py`: if `WorkOsError` is not a `BusinessRuleError` subclass it falls through to an unhandled 500, and a mistyped code becomes a server error. Either make `WorkOsError` subclass `InvalidCredentialsError`, or add a handler. Whichever you choose, add a test that a wrong code returns 401.

**If WorkOS is not configured** (`build_workos_client` returns `None`), these three routes must answer 503 via `FeatureDisabledError`, exactly as `google_sign_in` does at `auth_service.py:85`. Add a test.

- [ ] **Step 6: Run the tests, the suite, and commit**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
git add agentpit/api agentpit/datastructures tests/api/test_authkit_routes.py
git commit -m "feat(api): sign in with a mailed code, and refresh the session"
```

---

### Task 4: Accept AuthKit tokens in the request path

**Files:**
- Modify: `agentpit/auth/dependencies.py`
- Modify: `agentpit/api/app.py` (pass the verifier into `make_current_user_dep`)
- Create: `tests/auth/test_current_user_authkit.py`

**Interfaces:**
- Consumes: `AuthKitVerifier` (already built), `TableRead.get_user_by_workos_id` (plan 1).

- [ ] **Step 1: Write the failing tests**

Cover exactly these, with real assertions:

- An `X-API-Key` request still resolves its user and **never consults either token path**. (This is the bot path; breaking it stops every trading agent.)
- A legacy `JwtCoder` bearer token still resolves its user. Nothing in this plan may break it.
- A valid AuthKit token whose `sub` matches a `WORKOS_USER_ID` resolves that user.
- A valid AuthKit token whose `sub` matches **no** row is rejected 401 — it must never create an account. Account creation belongs to `POST /auth/session` alone.
- A garbage bearer token is 401.

Mint AuthKit-shaped tokens the way `tests/auth/test_authkit_tokens.py` does, and inject the verifier with a local key resolver so nothing touches the network.

- [ ] **Step 2: Run, watch fail**

- [ ] **Step 3: Extend the dependency**

`make_current_user_dep(coder)` gains an optional `authkit: AuthKitVerifier | None = None`. Order inside `current_user`:

1. `X-API-Key` — unchanged, first, untouched.
2. Bearer token: **try the legacy `coder.decode` first**, and only if it raises try `authkit.verify`. Both are accepted throughout this plan; plan 3 removes the first.

Why that order and not the reverse: the legacy check is a local HMAC verification with no I/O, while `authkit.verify` may fetch a JWKS. Trying the cheap local one first means the common case during the transition costs nothing extra.

An AuthKit token that verifies but whose `sub` matches no row raises `_unauth("unknown session")` — never a create.

- [ ] **Step 4: Tests, suite, commit**

```bash
git commit -m "feat(auth): accept AuthKit sessions alongside the legacy token"
```

---

### Task 5: The dialog asks for an address, then a code

**Files:**
- Modify: `ui/src/api/auth.ts`
- Modify: `ui/src/auth/AuthContext.tsx`, `ui/src/auth/context.ts`
- Modify: `ui/src/components/auth/AuthDialog.tsx`
- Create: `ui/src/components/auth/codeFlow.ts`
- Create: `ui/src/components/auth/codeFlow.test.ts`

**Interfaces:**
- Consumes: `POST /auth/code`, `POST /auth/session`, `POST /auth/refresh` (Task 3).

- [ ] **Step 1: Write the failing helper tests**

`ui/` vitest is node-env with no `@testing-library/react`, so the component cannot be render-tested. Every decision therefore lives in `codeFlow.ts` and is tested there.

Create `ui/src/components/auth/codeFlow.test.ts` covering:

```ts
// normaliseCode: strips spaces and non-digits from a pasted code, because
// people paste "515 627" and mail clients add zero-width characters.
// isCompleteCode: exactly six digits.
// resendSecondsLeft(lastSentAtMs, nowMs): 60 -> 0, never negative.
// canResend(lastSentAtMs, nowMs): false while the countdown runs.
// signInErrorMessage(status): 401 -> "That code is wrong or expired.",
//   429 -> a rate-limited message, otherwise a generic one. The 401 wording
//   must not distinguish "wrong" from "expired": the two are one failure.
```

- [ ] **Step 2: Run and watch fail**

```bash
cd ui && npx vitest run src/components/auth/codeFlow.test.ts
```

- [ ] **Step 3: Write `codeFlow.ts`, then wire the dialog**

The dialog becomes two states — `"email"` then `"code"` — held in local state. `dialogMode` (`"login" | "signup"`) is **not** removed in this plan: `/register` and `/login` still exist and plan 3 removes them. Add the code flow as the primary path and leave the existing form reachable, so a regression in the new path does not lock anybody out mid-transition.

`AuthContext` gains `sendCode(email)` and `signInWithCode(email, code)`, persists `refresh_token` beside the access token, and calls `POST /auth/refresh` when `apiFetch` sees a 401 with a stored refresh token — retrying the original request once. Without that, the 300-second access token logs everybody out every five minutes.

- [ ] **Step 4: The full UI gate**

```bash
cd ui && npx vitest run && npm run typecheck && npm run lint && npm run build
```

All four must pass. Report each.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(ui): sign in with a mailed code"
```

---

## What this plan deliberately does not do

- Google stays exactly as it is today (in-page Google Identity Services). Moving it to the WorkOS redirect is plan 3.
- `/register`, `/login`, `change_password`, `JwtCoder` and `PASSWORD_HASH` all keep working. Plan 3 removes them.
- The `api_key` in the session payload is a permanent credential already sitting in browser storage; the refresh token added here is no worse and no better. Both deserve a look, and that look is neither this plan nor plan 3.
