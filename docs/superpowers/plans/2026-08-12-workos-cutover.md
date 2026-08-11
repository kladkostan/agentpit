# Finishing the WorkOS migration — implementation plan (plan 3 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WorkOS AuthKit becomes the only way a browser authenticates: Google moves to the WorkOS redirect, private-key export re-authenticates with a mailed code, the five findings parked from plan 2's review are fixed, and our own JWT stops being issued or accepted.

**Architecture:** Everything additive comes first and reverts without consequence; the cutover is last and signs everybody out once. Google goes through `/user_management/authorize` + `/user_management/authenticate` (`grant_type: authorization_code`), which yields the same token shape `AuthKitVerifier` already pins — the `/oauth2/*` endpoints on the AuthKit domain issue a **different** issuer and must not be used. `X-API-Key` is untouched throughout.

**Tech Stack:** Python 3.13, FastAPI, psycopg3/Postgres, PyJWT, `httpx`. UI: Vite/React 18/TS, react-router-dom, vitest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-12-workos-cutover-design.md`, extending `2026-08-11-workos-authkit-design.md`. Read both first.
- Backend tests: `.venv/bin/python -m pytest tests -q --ignore=tests/onchain`. **NEVER source `.env`** — the conftest setdefaults get defeated and the live-sync tests flake. The local anvil must be running.
- **No test may reach the network.** `FakeWorkOsClient` is the double; extend it in step with the protocol.
- **`X-API-Key` must keep working, unchanged, in every task.** It is checked first in `current_user`, before either token path. Every bot trading today depends on it.
- **No backend capability is deleted in this plan.** `JwtCoder`, `PASSWORD_HASH`, `change_password`, `agentpit/auth/passwords.py`, the Google verifier, `GoogleSignInButton.tsx`, `googleAuth.ts` and `loginRequest`/`registerRequest` all stay in the tree, so reverting a single commit restores a working legacy sign-in. Task 8 makes three routes answer 410 and takes the password form out of the dialog — that UI is the one thing this plan does remove, because a form posting to a 410 is worse than no form. Plan 4 deletes the rest.
- UI from `ui/`: `npx vitest run && npm run typecheck && npm run lint && npm run build`. All four must pass. `ui/` vitest runs in node with **no `@testing-library/react`** — components cannot be render-tested, so every real decision lives in a pure helper. `tsconfig` has `exactOptionalPropertyTypes`.
- Commit messages must **NOT** carry a `Co-Authored-By` trailer.
- Comments explain *why*, and cite measured facts. Match the surrounding code, which is heavily commented.
- The AuthKit access token lives **300 seconds** and its refresh token does **not** rotate. Its claims are `iss` (= `https://api.workos.com/user_management/<client_id>`), `sub`, `sid`, `jti`, `auth_time`, `client_id`, `iat`, `exp`. **There is no `aud`.** Do not change `AuthKitVerifier`.

---

### Task 1: The mailed code never reaches a log, and a 429 stays a 429

Findings 1 and 2 from plan 2's review. Both live in the same two files, and neither is worth its own review gate.

**Files:**
- Modify: `agentpit/auth/workos_client.py`
- Modify: `agentpit/api/exception_handlers.py`
- Modify: `tests/auth/test_workos_client.py`
- Modify: `tests/api/test_authkit_routes.py`

**Interfaces:**
- Produces: `WorkOsRateLimitedError(WorkOsError)` in `agentpit/auth/workos_client.py`. No later task depends on it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/auth/test_workos_client.py`. `_real(handler)` and the `json`/`httpx`/`pytest` imports already exist in that file.

```python
def test_the_mailed_code_is_stripped_from_an_error_body():
    # WorkOS answered a bad code with `{"code": "invalid_code"}` when this was
    # measured, echoing nothing -- but a gateway or WAF in front of it is under
    # no such obligation, and this endpoint is reached by an unauthenticated
    # caller who supplies the code. The message becomes a log line.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad code 515627 for a@b.com"})

    with pytest.raises(WorkOsError) as excinfo:
        _real(handler).authenticate_with_code("a@b.com", "515627")
    assert "515627" not in str(excinfo.value)
    assert "[redacted]" in str(excinfo.value)


def test_a_429_is_its_own_error_type():
    # Collapsed into the generic refusal, a rate limit reaches the caller as
    # 401 "request a new code" -- telling them to do the very thing that rate
    # limited them.
    client = _real(lambda _r: httpx.Response(429, json={"code": "rate_limit"}))
    with pytest.raises(WorkOsRateLimitedError):
        client.send_magic_auth_code("a@b.com")


def test_a_rate_limit_is_still_a_workos_error():
    # The migration script catches `WorkOsError` per account and carries on.
    # A subclass keeps that working unchanged, exactly as
    # `WorkOsUnavailableError` does.
    client = _real(lambda _r: httpx.Response(429, json={"code": "rate_limit"}))
    with pytest.raises(WorkOsError):
        client.send_magic_auth_code("a@b.com")
```

Add `WorkOsRateLimitedError` to the `from agentpit.auth.workos_client import ...` line at the top of that file.

Append to `tests/api/test_authkit_routes.py`:

```python
def test_a_workos_rate_limit_reaches_the_caller_as_429():
    # The UI already has copy for 429 (`codeFlow.ts`), and it has been
    # unreachable because the status never arrived. This is what switches it on.
    from agentpit.auth.workos_client import WorkOsRateLimitedError

    class _RateLimited:
        def send_magic_auth_code(self, email: str) -> None:
            raise WorkOsRateLimitedError("WorkOS POST /user_management/magic_auth returned 429")

    app.dependency_overrides[deps.get_workos_client] = lambda: _RateLimited()
    try:
        with TestClient(app) as client:
            resp = client.post("/auth/code", json={"email": "g@example.com"})
        assert resp.status_code == 429, resp.text
        # The diagnostic message names our endpoint; it is logged, not returned.
        assert "user_management" not in resp.text
    finally:
        app.dependency_overrides.pop(deps.get_workos_client, None)
```

- [ ] **Step 2: Run them and watch them fail**

```bash
.venv/bin/python -m pytest tests/auth/test_workos_client.py tests/api/test_authkit_routes.py -q
```

Expected: `ImportError: cannot import name 'WorkOsRateLimitedError'`.

- [ ] **Step 3: Add the error type and raise it**

In `agentpit/auth/workos_client.py`, add beside `WorkOsUnavailableError`:

```python
class WorkOsRateLimitedError(WorkOsError):
    """WorkOS refused because we asked too often.

    A subclass rather than a sibling for the same reason
    `WorkOsUnavailableError` is one: `migrate_users` catches `WorkOsError` per
    account and must keep catching this unchanged. It exists for the API, which
    otherwise answers 401 "request a new code" -- instructing a rate-limited
    caller to perform the action that rate limited them, in a loop the UI's own
    resend cooldown cannot break because the cooldown is per dialog, not per
    address.
    """
```

In `RealWorkOsClient._request`, before the generic `>= 400` branch:

```python
        if response.status_code == 429:
            # Split out ahead of the generic refusal below so the API can answer
            # 429 and the already-written UI copy becomes reachable. Same
            # redaction as every other error body.
            raise WorkOsRateLimitedError(
                f"WorkOS {method} {path} returned 429: "
                f"{_redact(response.text, secrets)[:500]}"
            )
```

In `RealWorkOsClient._authenticate`, add the code to the secrets tuple:

```python
            # Everything secret this body can carry. The refresh token is the
            # one no pattern can find, and this endpoint is the only place it
            # is ever sent. The six-digit code joins it: it is a live sign-in
            # credential for ten minutes, and this method's errors are logged.
            secrets=(self._api_key, body.get("refresh_token"), body.get("code")),
```

- [ ] **Step 4: Add the 429 handler**

In `agentpit/api/exception_handlers.py`, import `WorkOsRateLimitedError` and register it **with the other WorkOS handlers**:

```python
    @app.exception_handler(WorkOsRateLimitedError)
    async def _workos_rate_limited(
        _: Request, exc: WorkOsRateLimitedError
    ) -> JSONResponse:
        """We asked WorkOS too often. Not the caller's typo, not our outage.

        Starlette walks the raised exception's MRO and matches the most
        specific registered type, so this wins over the `WorkOsError` handler
        below regardless of registration order -- the same mechanism
        `InsufficientGasError` relies on.

        WARNING, not ERROR: a rate limit is a working system saying no.
        """
        log.warning("WorkOS rate limited a request: %s", exc)
        return JSONResponse(
            status_code=429,
            content={"detail": "too many attempts — wait a moment and try again"},
        )
```

- [ ] **Step 5: Run the tests, then the suite, then commit**

```bash
.venv/bin/python -m pytest tests/auth/test_workos_client.py tests/api/test_authkit_routes.py -q
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
git add agentpit/auth/workos_client.py agentpit/api/exception_handlers.py tests/auth/test_workos_client.py tests/api/test_authkit_routes.py
git commit -m "fix(auth): a mailed code is not log material, and a rate limit is not a typo"
```

Report the exact pytest summary line.

---

### Task 2: Onboarding belongs to sign-in, and the chain-wipe repair reaches it

Findings 3 and 4. They are one change: `_resolve_account` currently repairs on every path including refresh, and never runs the repair that `AuthService` has for a wiped chain. The two halves are complementary and are decided together.

**Files:**
- Modify: `agentpit/services/authkit_service.py`
- Modify: `agentpit/api/deps.py`
- Modify: `tests/services/test_authkit_service.py`

**Interfaces:**
- Produces: `AuthKitService.__init__(self, *, db, workos, onboard, reonboard)` — a fourth keyword argument. Tasks 5 and 7 construct or stub this service and must pass it.
- Consumes: `AuthService._maybe_reonboard(user: User) -> None` (returns nothing; it mutates the chain and the row).

- [ ] **Step 1: Write the failing tests**

The existing `_Onboarder` spy in `tests/services/test_authkit_service.py` stays as it is. Add a second spy beside it and change `_service` to wire both:

```python
class _Reonboarder:
    """Stands in for AuthService._maybe_reonboard.

    The real one reads a native balance off the chain and re-funds a wallet the
    chain forgot. Here it only records that it was asked, because what these
    tests are about is WHICH sign-in paths ask.
    """

    def __init__(self):
        self.calls = []

    def __call__(self, user):
        self.calls.append(user.user_id)


def _service(workos=None, onboarder=None, reonboarder=None):
    db = DbSession(Settings().database_url)
    return AuthKitService(
        db=db,
        workos=workos or FakeWorkOsClient(),
        onboard=onboarder or _Onboarder(),
        reonboard=reonboarder or _Reonboarder(),
    ), db
```

Then add:

```python
def test_refresh_never_runs_on_chain_onboarding():
    # A background call every 300 seconds with nobody watching. Onboarding is
    # ~a second of chain round-trips and real gas, and the whole page's
    # requests queue behind the shared in-flight refresh while it waits. If it
    # failed once it will most likely fail again, so retrying it on a timer
    # buys nothing and costs every five minutes.
    workos, onboarder = FakeWorkOsClient(), _Onboarder()
    svc, db = _service(workos, onboarder)
    svc.send_code("a@example.com")
    first = svc.sign_in("a@example.com", workos.last_code("a@example.com"))

    with db.write() as conn:
        TableWrite.clear_user_onboarded(conn, first.user.user_id)
    onboarder.calls.clear()

    again = svc.refresh(first.refresh_token)

    assert again.user.user_id == first.user.user_id
    assert onboarder.calls == []


def test_sign_in_finishes_an_onboarding_that_never_completed():
    # The complement of the test above. `_create_account` commits the row
    # before onboarding it, so a chain that was down during somebody's first
    # sign-in leaves a committed row with ONBOARDED_AT null -- a wallet with no
    # gas, no collateral and no approvals, failing every order at trade time.
    workos, onboarder = FakeWorkOsClient(), _Onboarder()
    svc, db = _service(workos, onboarder)
    svc.send_code("b@example.com")
    first = svc.sign_in("b@example.com", workos.last_code("b@example.com"))

    with db.write() as conn:
        TableWrite.clear_user_onboarded(conn, first.user.user_id)
    onboarder.calls.clear()

    svc.send_code("b@example.com")
    svc.sign_in("b@example.com", workos.last_code("b@example.com"))

    assert onboarder.calls == [first.user.user_id]


def test_sign_in_runs_the_chain_wipe_repair_for_an_onboarded_account():
    # `_maybe_reonboard` hangs off `login` and `google_sign_in` and has never
    # been reachable from a mailed-code sign-in. On the local anvil, whose
    # state is wiped on restart while the database persists, whoever signs in
    # by code therefore stays unfunded forever.
    workos, reonboarder = FakeWorkOsClient(), _Reonboarder()
    svc, _db = _service(workos, reonboarder=reonboarder)
    svc.send_code("c@example.com")
    first = svc.sign_in("c@example.com", workos.last_code("c@example.com"))

    svc.send_code("c@example.com")
    second = svc.sign_in("c@example.com", workos.last_code("c@example.com"))

    # Not on the first: that account was onboarded by this very call and its
    # wallet is as funded as it will ever be.
    assert reonboarder.calls == [second.user.user_id]
    assert first.user.user_id == second.user.user_id


def test_refresh_never_runs_the_chain_wipe_repair():
    workos, reonboarder = FakeWorkOsClient(), _Reonboarder()
    svc, _db = _service(workos, reonboarder=reonboarder)
    svc.send_code("d@example.com")
    first = svc.sign_in("d@example.com", workos.last_code("d@example.com"))
    reonboarder.calls.clear()

    svc.refresh(first.refresh_token)

    assert reonboarder.calls == []
```

- [ ] **Step 2: Run them and watch them fail**

```bash
.venv/bin/python -m pytest tests/services/test_authkit_service.py -q
```

Expected: `TypeError: AuthKitService.__init__() got an unexpected keyword argument 'reonboard'`, and — once that is added — a failure showing the onboarder was called on refresh.

- [ ] **Step 3: Add `clear_user_onboarded` if it does not exist**

The tests above need to un-onboard a row. Check `agentpit/db/table_write.py` for it; if it is absent, add it beside `mark_user_onboarded`:

```python
    @staticmethod
    def clear_user_onboarded(db: psycopg.Connection, user_id: str) -> bool:
        """Test-only: put a row back into the never-onboarded state.

        The condition it recreates is real -- `_create_account` commits the row
        before onboarding it, so a chain outage leaves exactly this -- but
        nothing in the product ever writes it, and the repair paths that read
        `ONBOARDED_AT` cannot be tested without a way to produce it.
        """
        with db.cursor() as cur:
            cur.execute(
                "UPDATE users SET ONBOARDED_AT = NULL WHERE USER_ID = %s", (user_id,)
            )
            return cur.rowcount > 0
```

Match the surrounding methods' style — read `mark_user_onboarded` directly above and follow whatever it does with cursors and return values.

- [ ] **Step 4: Split repair off the resolution path**

In `agentpit/services/authkit_service.py`, take the fourth argument:

```python
    def __init__(self, *, db: DbSession, workos: WorkOsClient, onboard, reonboard):
        self._db = db
        self._workos = workos
        # `AuthService._onboard_new_account` and `AuthService._maybe_reonboard`
        # -- injected rather than imported so the chain stays out of these
        # tests, and so the two services do not depend on each other's
        # construction.
        self._onboard = onboard
        self._reonboard = reonboard
```

Give `_resolve_account` a second flag and route the repairs through one place:

```python
    def sign_in(self, email: str, code: str) -> AuthKitSession:
        session = self._workos.authenticate_with_code(email, code)
        return AuthKitSession(
            user=self._resolve_account(session, create=True, repair=True),
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
            #
            # `repair=False` for a related reason and a practical one. A
            # refresh runs about every 300 seconds with nobody watching, and
            # both branches of `_repair` are chain work: onboarding funds gas,
            # drips collateral and sends three approvals, and `_reonboard`
            # reads a balance off the chain first. Every request the page has
            # in flight is queued behind the shared refresh while that runs,
            # and an onboarding that failed once will most likely fail again.
            # The repair is not lost -- the next sign_in performs it, with a
            # person at the screen who is already paying that second.
            user=self._resolve_account(session, create=False, repair=False),
            access_token=session.access_token,
            refresh_token=session.refresh_token,
        )

    def _resolve_account(
        self, session: WorkOsSession, *, create: bool, repair: bool
    ) -> User:
        with self._db.read() as conn:
            user = TableRead.get_user_by_workos_id(conn, session.workos_user_id)
        if user is not None:
            return self._repair(user) if repair else user
        if not create:
            raise InvalidCredentialsError("invalid session")
        return self._create_account(session, repair=repair)

    def _repair(self, user: User) -> User:
        """The two ways an existing row can need chain work, and neither overlaps.

        `ONBOARDED_AT` null means the wallet was never funded at all --
        `_create_account` commits the row before onboarding it, so a chain that
        was down during a first sign-in leaves exactly this, and every later
        sign-in would otherwise hand back a session for a wallet that fails
        every order.

        `ONBOARDED_AT` set means the wallet WAS funded, and
        `AuthService._maybe_reonboard` is the repair for the other failure: the
        local anvil wipes its state on restart while the database persists, so
        a funded wallet can find itself empty. That method returns early
        precisely when `onboarded_at is None`, because it needs the stamp to
        know the wallet was ever funded -- which is why these are two branches
        and not one call.
        """
        if user.onboarded_at is None:
            log.info(
                "user %s has no ONBOARDED_AT — finishing onboarding on sign-in",
                user.user_id,
            )
            return self._onboard(user.user_id, user.eth_key)
        self._reonboard(user)
        return user
```

Delete `_finish_onboarding`; `_repair` replaces it. In `_create_account`, the linked-account branch calls `self._repair(linked)` instead of `self._finish_onboarding(linked)`, and `_create_account` takes `repair: bool` and skips that call when it is False. A freshly created row is returned by `self._onboard(...)` as before and needs no repair.

- [ ] **Step 5: Pass the second callable in**

In `agentpit/api/deps.py`, `get_authkit_service`:

```python
    return AuthKitService(
        db=db,
        workos=workos,
        onboard=auth._onboard_new_account,
        reonboard=auth._maybe_reonboard,
    )
```

Extend the existing comment above it to say that `_maybe_reonboard` is reached the same way and for the same reason.

- [ ] **Step 6: Run the tests, then the suite, then commit**

```bash
.venv/bin/python -m pytest tests/services/test_authkit_service.py -q
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
git add agentpit/services/authkit_service.py agentpit/api/deps.py agentpit/db/table_write.py tests/services/test_authkit_service.py
git commit -m "fix(auth): chain work belongs to a sign-in someone is watching"
```

Report the exact pytest summary line.

---

### Task 3: Two first sign-ins for one address make one account

Finding 5.

**Files:**
- Modify: `agentpit/services/authkit_service.py`
- Modify: `tests/services/test_authkit_service.py`

**Interfaces:**
- Consumes: `AuthKitService._create_account` (Task 2's signature, `(session, *, repair: bool)`).

- [ ] **Step 1: Write the failing test**

`EMAIL TEXT NOT NULL UNIQUE` (`agentpit/db/table_create.py`) is the constraint being raced. The test provokes it deterministically by inserting the row between the service's lookup and its insert, rather than by threading — a real race reproduced by hand.

```python
def test_a_lost_race_on_a_new_address_returns_the_winner_s_account():
    # Two first sign-ins for one address arrive together: both miss the
    # WORKOS_USER_ID lookup, both reach create_user, and one takes a
    # UniqueViolation on EMAIL. Unhandled it is a 500 -- a person told the
    # service is broken while their account was in fact created.
    workos = FakeWorkOsClient()
    svc, db = _service(workos)
    svc.send_code("race@example.com")
    code = workos.last_code("race@example.com")
    created = workos.find_user_by_email("race@example.com")

    # Stand in for the request that won: the row and its identity already
    # exist by the time our insert runs.
    with db.write() as conn:
        user_id, _acct, _key = TableWrite.create_user(
            conn, email="race@example.com", password_hash=None, handle=None
        )
        TableWrite.set_workos_user_id(conn, user_id, created.workos_user_id)

    session = svc.sign_in("race@example.com", code)

    assert session.user.user_id == user_id
```

Note this test passes today by a different route — `_link_existing_account` finds the row by email before the insert. Make it fail first by asserting the harder case, where the row appears **after** that lookup. Add this second test, which is the one that actually drives the change:

```python
def test_a_row_that_appears_after_the_link_lookup_is_adopted_not_500(monkeypatch):
    # The window `_link_existing_account` cannot close: it looks, finds
    # nothing, and the winner commits before our insert runs. Simulated by
    # creating the row from inside the lookup itself.
    workos = FakeWorkOsClient()
    svc, db = _service(workos)
    svc.send_code("late@example.com")
    code = workos.last_code("late@example.com")
    created = workos.find_user_by_email("late@example.com")

    original = svc._link_existing_account
    winner = {}

    def _link_then_race(session):
        result = original(session)
        if not winner:
            with db.write() as conn:
                user_id, _acct, _key = TableWrite.create_user(
                    conn, email=session.email, password_hash=None, handle=None
                )
                TableWrite.set_workos_user_id(
                    conn, user_id, created.workos_user_id
                )
            winner["user_id"] = user_id
        return result

    monkeypatch.setattr(svc, "_link_existing_account", _link_then_race)

    session = svc.sign_in("late@example.com", code)

    assert session.user.user_id == winner["user_id"]
```

- [ ] **Step 2: Run it and watch it fail**

```bash
.venv/bin/python -m pytest tests/services/test_authkit_service.py -q
```

Expected: `psycopg.errors.UniqueViolation: duplicate key value violates unique constraint`.

- [ ] **Step 3: Catch the violation and hand back the winner's row**

In `agentpit/services/authkit_service.py`, add `from psycopg.errors import UniqueViolation` to the imports, and wrap the create:

```python
        try:
            with self._db.write() as conn:
                handle = pick_handle(
                    taken=lambda candidate: TableRead.handle_taken(conn, candidate)
                )
                user_id, acct, _api_key = TableWrite.create_user(
                    conn, email=session.email, password_hash=None, handle=handle
                )
                TableWrite.set_workos_user_id(
                    conn, user_id, session.workos_user_id
                )
        except UniqueViolation:
            # Another first sign-in for this same address committed between
            # `_link_existing_account`'s lookup and this insert. `EMAIL` and
            # `WORKOS_USER_ID` are both unique, so either can be the one that
            # fired; read back by identity first and fall back to the address.
            #
            # The loser gets the winner's account, which is the right answer:
            # one person, one wallet. The row may still have ONBOARDED_AT null
            # because the winner onboards outside its transaction -- that is
            # the condition `_repair` exists for, and the next sign-in closes
            # it.
            log.info("lost a create race for %s — adopting the winner's row", session.email)
            with self._db.read() as conn:
                winner = TableRead.get_user_by_workos_id(
                    conn, session.workos_user_id
                ) or TableRead.get_user_by_email_ci(conn, session.email)
            if winner is None:
                # The violation was something else entirely -- a handle
                # collision, say. Re-raising keeps a real bug visible instead
                # of turning it into a confusing None.
                raise
            return winner
```

- [ ] **Step 4: Run the tests, then the suite, then commit**

```bash
.venv/bin/python -m pytest tests/services/test_authkit_service.py -q
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
git add agentpit/services/authkit_service.py tests/services/test_authkit_service.py
git commit -m "fix(auth): two first sign-ins for one address make one account"
```

Report the exact pytest summary line.

---

### Task 4: Private key export re-authenticates with a mailed code

Backend and UI in one task on purpose: this changes the request body of `POST /me/private-key`, and a half-migrated export is not something a reviewer could sensibly accept.

**Files:**
- Modify: `agentpit/services/auth_service.py`
- Modify: `agentpit/datastructures/private_key_request.py`
- Modify: `agentpit/api/routes/users.py`
- Modify: `agentpit/api/deps.py`
- Modify: `tests/api/test_users.py` (or wherever `POST /me/private-key` is covered — find it with `grep -rn "private-key" tests/`)
- Modify: `ui/src/api/auth.ts`
- Modify: `ui/src/lib/exportKeyError.ts`
- Modify: `ui/src/lib/exportKeyError.test.ts`
- Modify: `ui/src/pages/SettingsPage.tsx`

**Interfaces:**
- Produces: `AuthService.send_key_export_code(*, user_id: str) -> None` and `AuthService.export_private_key(*, user_id: str, code: str) -> str`. `PrivateKeyRequest` becomes `{code: str}`. `POST /me/private-key/code` answers 202.
- Consumes: `WorkOsClient.authenticate_with_code`, `WorkOsClient.send_magic_auth_code`.

- [ ] **Step 1: Write the failing backend tests**

Find the existing export tests first (`grep -rn "private-key" tests/`) and rewrite them against the new factor. They live in the API tests, so they run over `TestClient(app)` with the `workos` fixture from `tests/api/test_authkit_routes.py` — copy that fixture into whichever file the export tests live in, or import it.

A helper both this task and the reader need:

```python
def _sign_in(client, workos, email: str) -> dict:
    """A signed-in account, the only way there is one now: address, code, in."""
    client.post("/auth/code", json={"email": email})
    resp = client.post(
        "/auth/session", json={"email": email, "code": workos.last_code(email)}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _auth(session: dict) -> dict:
    return {"Authorization": f"Bearer {session['access_token']}"}
```

The tests:

```python
def test_export_succeeds_with_a_freshly_mailed_code(workos):
    with TestClient(app) as client:
        session = _sign_in(client, workos, "k@example.com")
        assert client.post(
            "/me/private-key/code", headers=_auth(session)
        ).status_code == 202
        resp = client.post(
            "/me/private-key",
            json={"code": workos.last_code("k@example.com")},
            headers=_auth(session),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["eth_address"] == session["user"]["eth_address"]
    assert body["private_key"].startswith("0x")


def test_a_code_belonging_to_a_different_account_is_refused(workos):
    # THE test in this task. Without the workos_user_id pin this passes and
    # the key goes to whoever authenticated last.
    with TestClient(app) as client:
        mine = _sign_in(client, workos, "mine@example.com")
        _sign_in(client, workos, "theirs@example.com")
        # A code genuinely mailed to the other account, presented by this one.
        client.post("/auth/code", json={"email": "theirs@example.com"})
        resp = client.post(
            "/me/private-key",
            json={"code": workos.last_code("theirs@example.com")},
            headers=_auth(mine),
        )
    assert resp.status_code == 401, resp.text
    assert "private_key" not in resp.text


def test_a_wrong_code_is_401_and_does_not_stamp_the_export(workos):
    # The stamp matters beyond this endpoint: once EXPORTED_AT is set,
    # `_maybe_reonboard` never repairs that account again. A wrong guess must
    # not spend that.
    with TestClient(app) as client:
        session = _sign_in(client, workos, "w@example.com")
        client.post("/me/private-key/code", headers=_auth(session))
        resp = client.post(
            "/me/private-key", json={"code": "000000"}, headers=_auth(session)
        )
    assert resp.status_code == 401, resp.text
    with DbSession(Settings().database_url).read() as conn:
        exported_at, _ = TableRead.get_key_export_state(
            conn, session["user"]["user_id"]
        )
    assert exported_at is None


def test_a_malformed_code_is_422_and_never_reaches_workos(workos):
    # Asserted on the call counter, not the status: a local rejection and a
    # round trip both end in a 4xx and are indistinguishable otherwise.
    with TestClient(app) as client:
        session = _sign_in(client, workos, "m@example.com")
        before = workos.authenticate_calls
        resp = client.post(
            "/me/private-key", json={"code": "12345"}, headers=_auth(session)
        )
    assert resp.status_code == 422
    assert workos.authenticate_calls == before


def test_the_cooldown_still_applies(workos):
    # Two attempts inside KEY_EXPORT_COOLDOWN_S. The second is refused before
    # its code is looked at, right or wrong.
    with TestClient(app) as client:
        session = _sign_in(client, workos, "c@example.com")
        client.post("/me/private-key/code", headers=_auth(session))
        first_code = workos.last_code("c@example.com")
        assert client.post(
            "/me/private-key", json={"code": first_code}, headers=_auth(session)
        ).status_code == 200
        client.post("/me/private-key/code", headers=_auth(session))
        resp = client.post(
            "/me/private-key",
            json={"code": workos.last_code("c@example.com")},
            headers=_auth(session),
        )
    assert resp.status_code == 400, resp.text
    assert "too many attempts" in resp.text


def test_the_export_code_goes_to_the_account_s_own_address(workos):
    # `/auth/code` takes an address from the request body. This one may only
    # ever mail the address on the row the caller is authenticated as, or the
    # endpoint becomes a way to mail a sign-in code to anybody.
    with TestClient(app) as client:
        session = _sign_in(client, workos, "own@example.com")
        resp = client.post(
            "/me/private-key/code",
            json={"email": "someone-else@example.com"},
            headers=_auth(session),
        )
    assert resp.status_code == 202, resp.text
    assert workos.last_code("own@example.com")
    with pytest.raises(KeyError):
        workos.last_code("someone-else@example.com")


def test_an_account_with_no_workos_identity_is_told_to_sign_in_again(workos):
    # A row from `/register` that has never been through WorkOS has a null
    # WORKOS_USER_ID, so there is nothing to pin a code against. Reachable
    # only while the legacy JWT is still accepted — Task 8 closes it.
    with TestClient(app) as client:
        made = client.post(
            "/register",
            json={"email": "legacy@example.com", "password": "hunter22hunter22"},
        ).json()
        resp = client.post(
            "/me/private-key", json={"code": "123456"}, headers=_auth(made)
        )
    assert resp.status_code == 400, resp.text
    assert "sign in again" in resp.text


def test_export_answers_503_when_workos_is_not_configured(workos):
    with TestClient(app) as client:
        session = _sign_in(client, workos, "d@example.com")
        app.dependency_overrides[deps.get_workos_client] = lambda: None
        try:
            resp = client.post("/me/private-key/code", headers=_auth(session))
        finally:
            app.dependency_overrides[deps.get_workos_client] = lambda: workos
    assert resp.status_code == 503, resp.text
```

- [ ] **Step 2: Run them and watch them fail**

```bash
.venv/bin/python -m pytest tests/api -q -k private_key
```

- [ ] **Step 3: Change the request model**

Replace the body of `agentpit/datastructures/private_key_request.py`:

```python
from pydantic import BaseModel, Field


class PrivateKeyRequest(BaseModel):
    """The code just mailed to the account's own address.

    One factor for every account. It replaces the password-or-Google pair,
    which chose by what the row HAD -- a rule that could not survive accounts
    having neither.
    """

    # Six digits, as WorkOS issues them. Validated here so an obviously
    # malformed code costs a 422 rather than a round-trip to WorkOS.
    code: str = Field(pattern=r"^\d{6}$")


class PrivateKeyResponse(BaseModel):
    private_key: str
    eth_address: str
```

- [ ] **Step 4: Give `AuthService` the WorkOS client and rewrite the re-auth**

`AuthService.__init__` gains `workos: WorkOsClient | None = None`, stored as `self._workos`, exactly as `google_verifier` already is. In `agentpit/api/deps.py`, `get_auth_service` gains a `workos: WorkOsClientDep` parameter and passes it through.

Replace `export_private_key`'s credential block. The cooldown claim above it — the separate transaction, `mark_key_export_attempt`'s conditional UPDATE and the comment explaining both — **stays exactly as it is**.

```python
    def send_key_export_code(self, *, user_id: str) -> None:
        """Mail a fresh code to the account's own address.

        Deliberately not `/auth/code`: that endpoint takes an address from the
        request body, and this one may only ever mail the address on the row
        the caller is already authenticated as.
        """
        if self._workos is None:
            raise FeatureDisabledError("key export is not configured")
        with self._db.read() as conn:
            user = TableRead.get_user_by_userid(conn, user_id)
        if user is None:
            raise UserNotFoundError()
        self._workos.send_magic_auth_code(user.email)

    def export_private_key(self, *, user_id: str, code: str) -> str:
        """The account's own private key, after proving it is the account.

        One factor for everybody: a code mailed to the address WorkOS holds.
        It is not a second factor in the strict sense -- sign-in is also a
        mailed code -- and what it buys is freshness. A stolen access token out
        of `localStorage` no longer suffices to export a key that cannot be
        revoked; the holder must be at the mailbox now.
        """
```

Keep the cooldown block unchanged, then:

```python
        if self._workos is None:
            raise FeatureDisabledError("key export is not configured")
        if user.workos_user_id is None:
            # Nothing to pin the code against. Only reachable while the legacy
            # JWT is still accepted -- after the cutover every session came
            # through AuthKit and every row therefore has an identity.
            raise BusinessRuleError("sign in again to export this key")

        session = self._workos.authenticate_with_code(user.email, code)
        # A valid code proves somebody owns an address. It has to be THIS
        # account's identity, or the key goes to whoever authenticated last --
        # the same reasoning as the Google-identity check this replaces. It
        # also covers a stale `users.EMAIL`: if the address has changed hands
        # upstream the code reaches a stranger, and the code that stranger
        # presents comes back with a different `workos_user_id`.
        if session.workos_user_id != user.workos_user_id:
            raise InvalidCredentialsError("that code is not this account's")

        with self._db.write() as conn:
            TableWrite.mark_key_exported(conn, user_id, now)
        return Web3.to_hex(user.eth_key.key)
```

Remove the `password` and `google_credential` parameters from the signature. Leave `self._google` and every other Google path alone — plan 4 removes them.

- [ ] **Step 5: Add the send-code route and update the export route**

In `agentpit/api/routes/users.py`:

```python
@router.post("/me/private-key/code", status_code=202)
def send_private_key_code(user: CurrentUserDep, service: AuthServiceDep) -> dict:
    """Mail a fresh export code to this account's own address.

    The address comes off the authenticated row, never off the request.
    """
    service.send_key_export_code(user_id=user.user_id)
    return {"status": "sent"}
```

and change the existing export route's call to `service.export_private_key(user_id=user.user_id, code=payload.code)`. `Cache-Control: no-store` stays.

- [ ] **Step 6: Run the backend tests and the suite**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
```

- [ ] **Step 7: Rewrite the UI error mapper and its test**

`ui/src/lib/exportKeyError.ts` loses its `hasPassword` parameter — there is one factor now, so the status is no longer ambiguous:

```ts
/**
 * Maps a failed `POST /me/private-key` response to user-facing copy.
 *
 * `hasPassword` is gone with the factor it selected: every account
 * re-authenticates with a mailed code, so a status now means one thing.
 *
 * `body` is the raw `ApiError.body` text — the JSON the backend sent, e.g.
 * `{"detail":"too many attempts — wait a moment"}`. Checked by substring
 * rather than parsed, so a body that fails to parse still degrades to generic
 * copy instead of throwing.
 */
export function exportErrorMessage(status: number, body: string): string {
  // Wrong and expired are one failure, and the backend cannot tell them apart
  // either — WorkOS answers the same for both.
  if (status === 401) return "That code is wrong or expired.";
  if (status === 429) return "Too many attempts. Wait a moment and try again.";
  if (status === 400) {
    return body.includes("too many attempts")
      ? "Too many attempts. Wait a moment and try again."
      : "Sign in again, then retry the export.";
  }
  if (status === 503) {
    return "Key export isn't available right now. Try again later.";
  }
  return "Failed to export private key.";
}
```

Rewrite `ui/src/lib/exportKeyError.test.ts` to cover each branch: 401, 429, 400-with-`too many attempts`, 400-without, 503, and an unmapped status.

- [ ] **Step 8: Update the API client**

In `ui/src/api/auth.ts`, replace `exportPrivateKeyRequest` and add the send:

```ts
export function sendExportCodeRequest(): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/me/private-key/code", {
    method: "POST",
  });
}

export function exportPrivateKeyRequest(
  code: string,
): Promise<{ private_key: string; eth_address: string }> {
  return apiFetch<{ private_key: string; eth_address: string }>(
    "/me/private-key",
    {
      method: "POST",
      body: JSON.stringify({ code }),
      // A 401 means the typed code was wrong, not that the session died.
      skipAuthEvent: true,
    },
  );
}
```

- [ ] **Step 9: Rewrite the export dialog**

In `ui/src/pages/SettingsPage.tsx`, `ExportKeyButton` becomes: a first screen with the warning and an "Email me a code" button, then a code field and Confirm, then the key. Replace `password` state with `code`, normalise input with `normaliseCode` from `@/components/auth/codeFlow` and gate Confirm on `isCompleteCode`, reuse `resendSecondsLeft`/`canResend` for the resend, and drop the `user.has_password` and `GOOGLE_CLIENT_ID` branches along with the `GoogleSignInButton` import **in this file only**. `exportErrorMessage(err.status, err.body)` loses its middle argument. Clear the code from state as soon as the key comes back, for the same reason the password was cleared there.

- [ ] **Step 10: The full UI gate**

```bash
cd ui && npx vitest run && npm run typecheck && npm run lint && npm run build
```

All four must pass. Report each.

- [ ] **Step 11: Commit**

```bash
git add agentpit/services/auth_service.py agentpit/datastructures/private_key_request.py agentpit/api/routes/users.py agentpit/api/deps.py tests ui/src
git commit -m "feat(auth): exporting a key needs the mailbox, not a password"
```

---

### Task 5: The authorization-code exchange, behind the client and the service

Backend only, and entirely additive — nothing calls the new route until Task 6.

**Files:**
- Modify: `agentpit/auth/workos_client.py`
- Modify: `agentpit/services/authkit_service.py`
- Modify: `agentpit/datastructures/authkit_requests.py`
- Modify: `agentpit/api/routes/auth.py`
- Modify: `tests/auth/test_workos_client.py`
- Modify: `tests/services/test_authkit_service.py`
- Modify: `tests/api/test_authkit_routes.py`

**Interfaces:**
- Produces: `WorkOsClient.authenticate_with_authorization_code(code: str) -> WorkOsSession`; `FakeWorkOsClient.issue_authorization_code(email: str) -> str` (test-only); `AuthKitService.sign_in_with_authorization_code(code: str) -> AuthKitSession`; `CallbackRequest`; `POST /auth/callback` returning `AuthResponse`. Task 6 consumes the route.

- [ ] **Step 1: Write the failing tests**

In `tests/auth/test_workos_client.py`:

```python
def test_the_authorization_code_grant_goes_to_user_management():
    # NOT the `/oauth2/token` endpoint on the AuthKit domain. That one issues
    # tokens whose `iss` is the AuthKit domain, and `AuthKitVerifier` pins
    # `api.workos.com/user_management/<client_id>` -- so every Google sign-in
    # would be rejected while these tests, which mint their own tokens, stayed
    # green. This is the same failure the original verifier shipped with.
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.read().decode())
        return httpx.Response(200, json={
            "user": {"id": "user_01", "email": "a@b.com", "email_verified": True},
            "access_token": "at", "refresh_token": "rt",
        })

    session = _real(handler).authenticate_with_authorization_code("code_abc")
    assert seen["url"].endswith("/user_management/authenticate")
    assert seen["body"]["grant_type"] == "authorization_code"
    assert seen["body"]["code"] == "code_abc"
    assert seen["body"]["client_id"] == "client_123"
    assert seen["body"]["client_secret"] == "sk_test_123"
    assert session.workos_user_id == "user_01"


def test_a_rejected_authorization_code_raises():
    client = _real(lambda _r: httpx.Response(400, json={"code": "invalid_grant"}))
    with pytest.raises(WorkOsError):
        client.authenticate_with_authorization_code("nope")


def test_the_fake_round_trips_an_authorization_code():
    fake = FakeWorkOsClient()
    code = fake.issue_authorization_code("a@b.com")
    session = fake.authenticate_with_authorization_code(code)
    assert session.email == "a@b.com"


def test_the_fake_refuses_an_authorization_code_twice():
    # A code is single-use at WorkOS. A double that let it be replayed would
    # hide a callback page that posts on every render.
    fake = FakeWorkOsClient()
    code = fake.issue_authorization_code("a@b.com")
    fake.authenticate_with_authorization_code(code)
    with pytest.raises(WorkOsError):
        fake.authenticate_with_authorization_code(code)
```

In `tests/services/test_authkit_service.py`:

```python
def test_a_first_authorization_code_creates_the_account_and_onboards_it():
    workos, onboarder = FakeWorkOsClient(), _Onboarder()
    svc, _db = _service(workos, onboarder)

    code = workos.issue_authorization_code("g@example.com")
    session = svc.sign_in_with_authorization_code(code)

    assert session.user.email == "g@example.com"
    assert session.user.eth_address.startswith("0x")
    assert onboarder.calls == [session.user.user_id]


def test_a_google_account_that_already_exists_here_is_adopted_not_duplicated():
    # Today's Google users have a row with GOOGLE_SUB and no password. Coming
    # back through the WorkOS redirect they must land on it: a second row is a
    # second wallet and a person whose positions have disappeared.
    workos, onboarder = FakeWorkOsClient(), _Onboarder()
    svc, db = _service(workos, onboarder)
    with db.write() as conn:
        user_id, _acct, _key = TableWrite.create_user(
            conn, email="old@example.com", password_hash=None, handle=None,
            google_sub="google-sub-1",
        )

    code = workos.issue_authorization_code("old@example.com")
    session = svc.sign_in_with_authorization_code(code)

    assert session.user.user_id == user_id
    assert onboarder.calls == []
```

In `tests/api/test_authkit_routes.py`:

```python
def test_post_auth_callback_returns_a_session(workos):
    code = workos.issue_authorization_code("cb@example.com")
    with TestClient(app) as client:
        resp = client.post("/auth/callback", json={"code": code})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["user"]["eth_address"].startswith("0x")


def test_a_bad_authorization_code_is_401(workos):
    with TestClient(app) as client:
        resp = client.post("/auth/callback", json={"code": "not-a-code"})
    assert resp.status_code == 401, resp.text


def test_an_empty_authorization_code_is_422_and_never_reaches_workos(workos):
    with TestClient(app) as client:
        resp = client.post("/auth/callback", json={"code": ""})
    assert resp.status_code == 422
    assert workos.authenticate_calls == 0
```

- [ ] **Step 2: Run them and watch them fail**

```bash
.venv/bin/python -m pytest tests/auth/test_workos_client.py tests/services/test_authkit_service.py tests/api/test_authkit_routes.py -q
```

- [ ] **Step 3: Extend the client**

Add to the `WorkOsClient` protocol:

```python
    def authenticate_with_authorization_code(self, code: str) -> WorkOsSession:
        """Exchange the code a provider redirect came back with.

        The `/user_management` flow, NOT the `/oauth2/*` endpoints on the
        AuthKit domain: those issue tokens whose `iss` is the AuthKit domain,
        and `AuthKitVerifier` pins `api.workos.com/user_management/<client_id>`.
        Both are advertised by WorkOS and only one of them is ours.
        """
        ...
```

On `RealWorkOsClient`:

```python
    def authenticate_with_authorization_code(self, code: str) -> WorkOsSession:
        return self._authenticate({"grant_type": "authorization_code", "code": code})
```

On `FakeWorkOsClient`, add `self._auth_codes: dict[str, str] = {}` to `__init__` and:

```python
    def issue_authorization_code(self, email: str) -> str:
        """Test-only: the code a provider redirect would have come back with."""
        user = self.create_user(email=email, password_hash=None)
        code = f"authcode-{len(self._auth_codes) + 1}-{user.workos_user_id}"
        self._auth_codes[code] = user.workos_user_id
        return code

    def authenticate_with_authorization_code(self, code: str) -> WorkOsSession:
        self.authenticate_calls += 1
        # `pop`, not `get`: WorkOS burns an authorization code on use, and a
        # double that allowed a replay would hide a callback page that posts on
        # every render.
        workos_user_id = self._auth_codes.pop(code, None)
        if workos_user_id is None:
            raise WorkOsError("WorkOS rejected the authorization code")
        for user in self._by_email.values():
            if user.workos_user_id == workos_user_id:
                return WorkOsSession(
                    workos_user_id=user.workos_user_id,
                    email=user.email,
                    access_token=f"at-{workos_user_id}",
                    refresh_token=f"rt-{workos_user_id}",
                )
        raise WorkOsError("WorkOS rejected the authorization code")
```

- [ ] **Step 4: Add the service method**

In `agentpit/services/authkit_service.py`:

```python
    def sign_in_with_authorization_code(self, code: str) -> AuthKitSession:
        """A provider redirect (today: Google) landing back on our callback.

        Deliberately identical to `sign_in` past the exchange: whichever door
        an identity arrives through, the account is resolved and created the
        same way. `repair=True` for the same reason as `sign_in` -- a person is
        at the screen, having just come back from Google.
        """
        session = self._workos.authenticate_with_authorization_code(code)
        return AuthKitSession(
            user=self._resolve_account(session, create=True, repair=True),
            access_token=session.access_token,
            refresh_token=session.refresh_token,
        )
```

- [ ] **Step 5: Add the request model and the route**

In `agentpit/datastructures/authkit_requests.py`:

```python
class CallbackRequest(BaseModel):
    # The opaque code WorkOS put in the redirect's query string. No shape to
    # validate beyond being present, so an empty one costs a 422 rather than a
    # round-trip.
    code: str = Field(min_length=1)
```

In `agentpit/api/routes/auth.py`:

```python
@router.post("/auth/callback", response_model=AuthResponse)
def complete_callback(
    payload: CallbackRequest, service: AuthKitServiceDep
) -> AuthResponse:
    """Exchange the code a WorkOS redirect came back with.

    Provider-agnostic on purpose: `authorization_code` is not a Google grant,
    so this route takes a code from any provider WorkOS is configured with, and
    from the AuthKit Hosted UI, without a line of new code. Hence
    `/auth/callback` and not `/auth/google/callback`.

    The exchange is server-side because `client_secret` is our API key. That is
    why the redirect lands on a page and the code arrives here by POST: the
    browser may carry the code, never the secret.
    """
    session = service.sign_in_with_authorization_code(payload.code)
    return AuthResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        user=UserPublic.model_validate(session.user.model_dump()),
    )
```

- [ ] **Step 6: Run the tests, the suite, and commit**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
git add agentpit/auth/workos_client.py agentpit/services/authkit_service.py agentpit/datastructures/authkit_requests.py agentpit/api/routes/auth.py tests
git commit -m "feat(auth): exchange the code a provider redirect brings back"
```

Report the exact pytest summary line.

---

### Task 6: The callback page, and Google becomes a link

**Files:**
- Create: `ui/src/lib/workosAuth.ts`
- Create: `ui/src/lib/workosAuth.test.ts`
- Create: `ui/src/pages/AuthCallbackPage.tsx`
- Modify: `ui/src/App.tsx`
- Modify: `ui/src/api/auth.ts`
- Modify: `ui/src/auth/context.ts`
- Modify: `ui/src/auth/AuthContext.tsx`
- Modify: `ui/src/components/auth/AuthDialog.tsx`

**Interfaces:**
- Consumes: `POST /auth/callback` (Task 5).
- Produces: `AuthValue.signInWithCallbackCode(code: string) => Promise<void>`.

- [ ] **Step 1: Write the failing helper tests**

Create `ui/src/lib/workosAuth.test.ts`. Everything the callback decides lives in pure functions, because components cannot be render-tested here.

```ts
import { describe, expect, it } from "vitest";
import {
  buildAuthorizeUrl,
  readCallbackParams,
  stateMatches,
} from "./workosAuth";

describe("buildAuthorizeUrl", () => {
  it("targets the user_management authorize endpoint, not oauth2", () => {
    // The `/oauth2/authorize` endpoint on the AuthKit domain issues tokens
    // with a different `iss` than AuthKitVerifier pins, so every sign-in
    // through it would be rejected by the API.
    const url = buildAuthorizeUrl({
      clientId: "client_1",
      redirectUri: "http://localhost:5173/auth/callback",
      provider: "GoogleOAuth",
      state: "st",
    });
    expect(url).toContain("https://api.workos.com/user_management/authorize");
    expect(url).not.toContain("/oauth2/");
  });

  it("carries the client id, redirect, provider, state and response type", () => {
    const url = new URL(
      buildAuthorizeUrl({
        clientId: "client_1",
        redirectUri: "http://localhost:5173/auth/callback",
        provider: "GoogleOAuth",
        state: "st",
      }),
    );
    expect(url.searchParams.get("client_id")).toBe("client_1");
    expect(url.searchParams.get("redirect_uri")).toBe(
      "http://localhost:5173/auth/callback",
    );
    expect(url.searchParams.get("provider")).toBe("GoogleOAuth");
    expect(url.searchParams.get("state")).toBe("st");
    expect(url.searchParams.get("response_type")).toBe("code");
  });
});

describe("readCallbackParams", () => {
  it("reads a code and state", () => {
    expect(readCallbackParams("?code=abc&state=st")).toEqual({
      code: "abc",
      state: "st",
    });
  });

  it("reports the provider's error instead of a code", () => {
    expect(readCallbackParams("?error=access_denied")).toEqual({
      error: "access_denied",
    });
  });

  it("treats a missing code as an error rather than an empty sign-in", () => {
    expect(readCallbackParams("")).toEqual({ error: "missing_code" });
  });
});

describe("stateMatches", () => {
  it("is true only for an exact match", () => {
    expect(stateMatches("st", "st")).toBe(true);
    expect(stateMatches("st", "other")).toBe(false);
  });

  it("is false when either side is missing", () => {
    // A link crafted by somebody else arrives with no stored state. Accepting
    // that completes a sign-in in a victim's browser.
    expect(stateMatches("st", null)).toBe(false);
    expect(stateMatches(null, "st")).toBe(false);
    expect(stateMatches(null, null)).toBe(false);
  });

  it("is false for the empty string on both sides", () => {
    expect(stateMatches("", "")).toBe(false);
  });
});
```

- [ ] **Step 2: Run and watch fail**

```bash
cd ui && npx vitest run src/lib/workosAuth.test.ts
```

- [ ] **Step 3: Write the helper**

Create `ui/src/lib/workosAuth.ts`:

```ts
/**
 * The WorkOS redirect flow, as pure functions.
 *
 * `ui/` vitest is node-env with no `@testing-library/react`, so
 * `AuthCallbackPage` cannot be render-tested. Every decision therefore lives
 * here — keep it that way.
 */

/**
 * NOT `<authkit-domain>/oauth2/authorize`.
 *
 * WorkOS advertises both. The `/oauth2/*` endpoints issue tokens whose `iss`
 * is the AuthKit domain; `AuthKitVerifier` on the API pins
 * `https://api.workos.com/user_management/<client_id>`, which is what this
 * flow returns. Taking the more standard-looking path would have every sign-in
 * rejected by the API while the tests, which mint their own tokens, stayed
 * green.
 */
const AUTHORIZE_URL = "https://api.workos.com/user_management/authorize";

/** Trim to null, so a variable set to whitespace means "off" like an unset one.
 *  Read as a value rather than by dynamic key: `import.meta.env` is a typed
 *  interface, and indexing it with a union widens to `any` under
 *  `noImplicitAny` or fails outright. */
function present(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/** Public by design — both appear in the URL of every sign-in. Absence means
 *  the feature is off and the button must not render, the same rule
 *  `GOOGLE_CLIENT_ID` follows in `googleAuth.ts`. */
export const WORKOS_CLIENT_ID = present(import.meta.env.VITE_WORKOS_CLIENT_ID);
export const WORKOS_REDIRECT_URI = present(
  import.meta.env.VITE_WORKOS_REDIRECT_URI,
);

/** Where the state lives between leaving the tab and coming back to it. */
export const STATE_KEY = "agentpit.oauth_state";

export function buildAuthorizeUrl(params: {
  clientId: string;
  redirectUri: string;
  provider: string;
  state: string;
}): string {
  const url = new URL(AUTHORIZE_URL);
  url.searchParams.set("client_id", params.clientId);
  url.searchParams.set("redirect_uri", params.redirectUri);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("provider", params.provider);
  url.searchParams.set("state", params.state);
  return url.toString();
}

export type CallbackParams = { code: string; state: string } | { error: string };

export function readCallbackParams(search: string): CallbackParams {
  const params = new URLSearchParams(search);
  const error = params.get("error");
  if (error) return { error };
  const code = params.get("code");
  // No code and no error is not an empty sign-in — it is somebody who opened
  // this URL by hand, or a redirect that lost its query string.
  if (!code) return { error: "missing_code" };
  return { code, state: params.get("state") ?? "" };
}

/**
 * Does the state that came back match the one we stored?
 *
 * Empty never matches empty. Without that, a link crafted by somebody else —
 * arriving at a browser that has stored nothing — would compare "" with "" and
 * complete a sign-in in a victim's session.
 */
export function stateMatches(
  returned: string | null,
  stored: string | null,
): boolean {
  if (!returned || !stored) return false;
  return returned === stored;
}

/** A fresh state value. `crypto` is injectable so this is testable. */
export function createState(source: Crypto = crypto): string {
  const bytes = new Uint8Array(16);
  source.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
```

- [ ] **Step 4: Add the client call and the context method**

In `ui/src/api/auth.ts`:

```ts
export function completeCallbackRequest(code: string): Promise<AuthResponse> {
  return apiFetch<AuthResponse>("/auth/callback", {
    method: "POST",
    body: JSON.stringify({ code }),
    // A 401 here is a rejected authorization code, not a dead session — there
    // is no session yet. Same reasoning as signInWithCodeRequest.
    skipAuthEvent: true,
  });
}
```

In `ui/src/auth/context.ts`, add to `AuthValue`:

```ts
  /** Finish a provider redirect: exchange its code for a session. */
  signInWithCallbackCode: (code: string) => Promise<void>;
```

In `ui/src/auth/AuthContext.tsx`, add the callback beside `signInWithCode` — same body, calling `completeCallbackRequest(code)` — and include it in both the `useMemo` value and its dependency array.

- [ ] **Step 5: Write the callback page**

Create `ui/src/pages/AuthCallbackPage.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/useAuth";
import { signInErrorMessage, statusOf } from "@/components/auth/codeFlow";
import {
  readCallbackParams,
  stateMatches,
  STATE_KEY,
} from "@/lib/workosAuth";

/**
 * Where a WorkOS provider redirect lands.
 *
 * This page exists rather than the redirect pointing at an API route because
 * the exchange needs `client_secret`, which is our WorkOS API key. The browser
 * may carry the authorization code; it may never carry the secret. So the code
 * arrives here and goes to the backend by POST.
 */
export function AuthCallbackPage() {
  const navigate = useNavigate();
  const { signInWithCallbackCode } = useAuth();
  const [error, setError] = useState<string | null>(null);
  // WorkOS burns an authorization code on first use, and React 18 StrictMode
  // mounts effects twice in development. Without this guard the second post
  // fails on an already-spent code and paints an error over a sign-in that
  // actually succeeded.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const params = readCallbackParams(window.location.search);
    const stored = sessionStorage.getItem(STATE_KEY);
    // Read once and cleared immediately, whatever happens next: a state left
    // behind is a state that can be replayed.
    sessionStorage.removeItem(STATE_KEY);

    if ("error" in params) {
      setError("Sign-in was cancelled or did not complete.");
      return;
    }
    if (!stateMatches(params.state, stored)) {
      // Either this tab never started a sign-in, or the value came back
      // altered. Both mean somebody else's link opened in this browser.
      setError("That sign-in link didn't come from this browser.");
      return;
    }

    void (async () => {
      try {
        await signInWithCallbackCode(params.code);
        // `replace`, so Back does not return to a URL holding a spent code.
        navigate("/", { replace: true });
      } catch (err) {
        setError(signInErrorMessage(statusOf(err)));
      }
    })();
  }, [navigate, signInWithCallbackCode]);

  return (
    <div className="mx-auto max-w-md py-16 text-center">
      {error ? (
        <div className="space-y-4">
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
          <Link to="/" className="text-sm text-blue-600 underline-offset-4 hover:underline dark:text-blue-400">
            Back to agentpit
          </Link>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Signing you in…</p>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Route it**

In `ui/src/App.tsx`, add above the catch-all:

```tsx
            <Route path="/auth/callback" element={<AuthCallbackPage />} />
```

`Routes` ranks by specificity rather than order, so position is cosmetic — but keep it with the other concrete routes. The static host already serves `index.html` for unknown paths, which is why `/markets` works.

- [ ] **Step 7: Replace the Google button in the dialog**

In `ui/src/components/auth/AuthDialog.tsx`, `googleBlock` stops rendering `GoogleSignInButton` and renders a button that creates a state, writes it to `sessionStorage` under `STATE_KEY`, and assigns `window.location.href` to `buildAuthorizeUrl({...})`. It renders only when both `WORKOS_CLIENT_ID` and `WORKOS_REDIRECT_URI` are present — the same "absence means the feature is off" rule `GOOGLE_CLIENT_ID` already follows. Keep the divider and the placement below the fields. Do **not** delete `GoogleSignInButton.tsx` or `googleAuth.ts`; plan 4 does that.

- [ ] **Step 8: The full UI gate**

```bash
cd ui && npx vitest run && npm run typecheck && npm run lint && npm run build
```

All four must pass. Report each.

- [ ] **Step 9: Commit**

```bash
git add ui/src
git commit -m "feat(ui): sign in with Google by way of WorkOS"
```

---

### Task 7: Verify a real Google round trip against Staging

**Blocked on a person.** WorkOS holds a `GoogleOAuth` credential in state `Invalid` with a null `clientId` in **both** environments — the 2026-08-11 spec's claim that Staging runs on WorkOS demo credentials was measured false on 2026-08-12. Nothing here can run until Google client credentials exist in Staging.

This task writes no product code. It exists because the last thing built from documentation in this area — `AuthKitVerifier` — was wrong in two ways while every test passed, and the tests could not have caught it: they minted their own tokens carrying exactly the claims the code assumed.

**Files:**
- Create: `scripts/print_authkit_claims.py`

- [ ] **Step 1: Confirm the prerequisite is done**

Staging needs the Google provider enabled with a real client id and secret, and the Google OAuth client needs this exact redirect URI registered (copy it; the identifier contains `1`/`l`/`I` and `0`/`O`):

```
https://auth.workos.com/sso/oauth/google/lKuLqgowoUQq1qygbeyfuEJq1/callback
```

Do not proceed until that is true. If it is not, stop and report that this task is blocked.

- [ ] **Step 2: Write the claims printer**

Create `scripts/print_authkit_claims.py`: it takes an access token on argv, decodes it **without verifying** (`jwt.decode(token, options={"verify_signature": False})`), and prints the claims as sorted JSON plus `exp - iat`. Verifying is the point of the comparison, not of the printing.

- [ ] **Step 3: Run the flow end to end**

Start the API against Staging credentials and the UI on `http://localhost:5173` — the Staging redirect URI registered with WorkOS is `http://localhost:5173/auth/callback`, and it is the default there. Open the dialog, use the Google button, complete Google's consent, and land back signed in.

- [ ] **Step 4: Compare the token against what the verifier pins**

Take the `access_token` out of the response and run the printer. Confirm, and **write the results into the report**:

- `iss` is exactly `https://api.workos.com/user_management/client_01KZRZ1QQXA15KX04VQBZPE0DZ`, matching `authkit_issuer(client_id)`.
- there is **no `aud`** claim.
- `client_id` equals the Staging client id.
- `exp - iat` is 300.

If any of these differ, **stop and report**. A mismatch means `AuthKitVerifier` rejects tokens from this flow, and no amount of green tests would have shown it.

- [ ] **Step 5: Check the account, not just the token**

Sign in with Google using an address that already has an agentpit account, and confirm in the database that `USER_ID` and `ETH_ADDRESS` are unchanged and `WORKOS_USER_ID` is now populated — no second row, no second wallet.

- [ ] **Step 6: Commit the script**

```bash
git add scripts/print_authkit_claims.py
git commit -m "chore(auth): print an AuthKit token's claims, for comparing against the verifier"
```

---

### Task 8: The cutover

Backend and UI together: a backend that refuses legacy tokens while the UI still offers a password form is broken between commits, and no reviewer could accept one half.

**Files:**
- Modify: `agentpit/auth/dependencies.py`
- Modify: `agentpit/api/app.py`
- Modify: `agentpit/api/routes/auth.py`
- Modify: `tests/auth/test_current_user_authkit.py`
- Modify: `tests/api/test_auth.py`, `tests/api/test_google_auth.py`
- Modify: `ui/src/components/auth/AuthDialog.tsx`
- Modify: `ui/src/auth/context.ts`
- Modify: `ui/src/auth/AuthContext.tsx`

**Interfaces:**
- Produces: `make_current_user_dep(authkit: AuthKitVerifier | None)` — the `coder` parameter is gone. `AuthValue` loses `login`, `register`, `dialogMode` and `setDialogMode`; `openLogin` and `openSignup` **stay** (both simply open the dialog) because `useRequireAuth`, `AuthButtons` and `LandingPage` call them.

- [ ] **Step 1: Write the failing tests**

In `tests/auth/test_current_user_authkit.py`, keep every existing test that proves `X-API-Key` and AuthKit tokens still work — they are the ones this task must not break — and turn the legacy-token test around. The file's existing helpers (`_authkit_token`, `CLIENT_ID`, `_KEY`, `fresh_test_db`) stay; `make_current_user_dep` now takes one argument.

The file already has what these need: `_CountingVerifier` (the real verifier over a local key, so nothing fetches a JWKS), the `db` fixture returning `fresh_test_db()`, and `_CountingCoder`. Use them; do not build a second verifier.

```python
def test_a_legacy_jwt_is_no_longer_accepted(db, coder):
    # The cutover itself. Every browser holding one of these is signed out
    # exactly once — which is what the product already does to everybody every
    # 24 hours, so the disruption is one it inflicts daily already.
    with db.write() as conn:
        user_id, _acct, _key = TableWrite.create_user(
            conn, email="legacy@example.com", password_hash="$2b$12$x", handle=None
        )
    token = coder.encode(user_id=user_id, email="legacy@example.com")

    dep = make_current_user_dep(_CountingVerifier())
    with pytest.raises(HTTPException) as excinfo:
        dep(
            api_key=None,
            creds=HTTPAuthorizationCredentials(
                scheme="Bearer", credentials=token
            ),
            db=db,
        )
    assert excinfo.value.status_code == 401


def test_an_api_key_still_resolves_its_user_after_the_cutover(db):
    # The single most important assertion in this plan. Every bot trading
    # today authenticates this way and nothing about it moved to WorkOS.
    with db.write() as conn:
        user_id, _acct, api_key = TableWrite.create_user(
            conn, email="bot@example.com", password_hash=None, handle=None
        )
    verifier = _CountingVerifier()

    dep = make_current_user_dep(verifier)
    user = dep(api_key=api_key, creds=None, db=db)

    assert user.user_id == user_id
    # Never consulted: the API-key path returns before either token path.
    assert verifier.verifies == 0
```

`_CountingCoder` and the `coder` fixture survive this task even though `make_current_user_dep` no longer takes a coder — the test above still needs to *mint* a legacy token in order to prove it is refused. Plan 4 removes them with `JwtCoder`.

In `tests/api/test_auth.py` and `tests/api/test_google_auth.py`, replace the success cases with 410s. Delete the tests that asserted a legacy sign-in worked; they are now asserting the opposite of the design.

```python
def test_register_is_gone():
    with TestClient(app) as client:
        resp = client.post(
            "/register",
            json={"email": "x@example.com", "password": "hunter22hunter22"},
        )
    assert resp.status_code == 410, resp.text
    assert "mailed code" in resp.text


def test_login_is_gone():
    with TestClient(app) as client:
        resp = client.post(
            "/login",
            json={"email": "x@example.com", "password": "hunter22hunter22"},
        )
    assert resp.status_code == 410, resp.text


def test_the_in_page_google_endpoint_is_gone():
    with TestClient(app) as client:
        resp = client.post("/auth/google", json={"credential": "anything"})
    assert resp.status_code == 410, resp.text


def test_nothing_reads_a_password_hash_any_more(monkeypatch):
    # The spec's plainest requirement, and the cheapest way to hold it: make
    # reading a hash raise, then drive the two paths that used to. A row's
    # PASSWORD_HASH survives the cutover as a rollback path and must simply go
    # unread until plan 4 drops the column.
    def _boom(*_args, **_kwargs):
        raise AssertionError("PASSWORD_HASH was read after the cutover")

    monkeypatch.setattr(TableRead, "get_password_hash_by_userid", _boom)

    with TestClient(app) as client:
        assert client.post(
            "/login", json={"email": "x@example.com", "password": "hunter22hunter22"}
        ).status_code == 410
        assert client.post(
            "/register",
            json={"email": "y@example.com", "password": "hunter22hunter22"},
        ).status_code == 410
```

Note that `test_nothing_reads_a_password_hash_any_more` does not cover key export, because Task 4 already stopped that path reading a hash and its own tests hold that. If the export tests are in the same file, extend this one to drive `/me/private-key` under the same monkeypatch.

- [ ] **Step 2: Run them and watch them fail**

```bash
.venv/bin/python -m pytest tests/auth tests/api -q
```

- [ ] **Step 3: Take the legacy branch out of the request path**

In `agentpit/auth/dependencies.py`, `make_current_user_dep` loses its `coder` parameter and its `coder.decode` branch, along with the `jwt` import if nothing else uses it. What remains: `X-API-Key` first and unchanged, then the bearer token through `_authkit_user`. Rewrite the docstring — it currently describes three credentials and a transition that has ended.

Keep the gate at the top of `AuthKitVerifier.verify` and `cached_key_resolver` exactly as they are. They are what stops an unauthenticated caller turning one request into one outbound fetch to `api.workos.com`, on the threadpool the bots' order placement shares — and with the legacy branch gone, **every** junk bearer token now reaches the verifier, so that guard matters more than it did.

In `agentpit/api/app.py`, update the `make_current_user_dep(coder, authkit_verifier)` call site. `coder` is still built and still passed to `AuthService`; plan 4 removes it.

- [ ] **Step 4: Retire the three routes**

In `agentpit/api/routes/auth.py`, replace the bodies of `register`, `login` and `google_sign_in`:

```python
@router.post("/register", status_code=410)
def register() -> dict:
    """Gone: accounts are created by signing in.

    410 rather than 404 because this endpoint existed and was removed, and
    rather than deleting the route because that would answer 404 — which reads
    as a typo to whoever calls it. The service code behind it is untouched, so
    reverting this commit restores a working legacy sign-in; plan 4 deletes it.
    """
    raise HTTPException(
        status_code=410, detail="sign in with a mailed code instead"
    )
```

Give `login` and `google_sign_in` the same treatment, with `google_sign_in`'s detail naming the redirect. Drop their `response_model` and their now-unused payload/service parameters, and remove the imports that go unused with them.

- [ ] **Step 5: Take the password form out of the dialog**

In `ui/src/components/auth/AuthDialog.tsx`: delete the `usePassword` state and its whole branch, `onSubmitPassword`, `password`, `MIN_PASSWORD_LENGTH`, the `dialogMode` effect, `passwordTitle`/`switchPrompt`/`switchAction`/`switchTo`, and both "Use a password instead" / "Email me a code instead" links. The dialog is `step === "email"` then `step === "code"`, and the title is `"Sign in"` then `"Check your email"`.

In `ui/src/auth/context.ts`, drop `login`, `register`, `dialogMode` and `setDialogMode` from `AuthValue`. **Keep `openLogin` and `openSignup`** — `useRequireAuth.ts`, `AuthButtons.tsx` and `LandingPage.tsx` (two call sites) use them, and both now just open the one dialog. Give them a one-line comment saying so, so the pair does not read as a leftover.

In `ui/src/auth/AuthContext.tsx`, delete the `login` and `register` callbacks, the `dialogMode` state and its effect, and the `loginRequest`/`registerRequest` imports; update the `useMemo` value and dependency array. Leave `ui/src/api/auth.ts`'s `loginRequest`, `registerRequest` and `changePasswordRequest` where they are — plan 4 removes them.

- [ ] **Step 6: The full UI gate**

```bash
cd ui && npx vitest run && npm run typecheck && npm run lint && npm run build
```

All four must pass. Report each. `typecheck` is the one that will find every remaining reference to the removed `AuthValue` fields.

- [ ] **Step 7: Run the whole backend suite and commit**

```bash
.venv/bin/python -m pytest tests -q --ignore=tests/onchain
git add agentpit ui/src tests
git commit -m "feat(auth): AuthKit is the only way in"
```

Report the exact pytest summary line, and say how many tests were removed or inverted.

---

## What this plan deliberately does not do

- **Deletes nothing.** `JwtCoder`, `JWT_SECRET`, `PASSWORD_HASH`, `change_password`, `agentpit/auth/passwords.py`, the Google verifier, `GoogleSignInButton.tsx`, `googleAuth.ts`, `loginRequest`/`registerRequest`, and the 410 stubs all stay. Plan 4 removes them — and it must first change `liquidity/house_accounts.py`, which hashes a fixed constant for accounts that never log in over HTTP, or deleting `passwords.py` breaks the liquidity engine.
- **Does not run the production migration.** `scripts/migrate_users_to_workos.py` is no longer a prerequisite: `_link_existing_account` adopts an unmigrated row by email on its owner's first sign-in. Running it is still worth doing before the deploy, and it is a deploy step, not a code change.
- **Does not deploy.** Production still needs the Google provider configured, the application renamed from `skalelabs.com's Application`, and the environment variables placed — none of them `WORKOS_ISSUER` or `WORKOS_JWKS_URL`, which are not read and whose obvious values are wrong.
- **Does not touch `X-API-Key`,** the `api_key` sitting in browser storage, or on-chain onboarding's contents.
