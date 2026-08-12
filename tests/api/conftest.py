"""Getting a signed-in account over HTTP, now that AuthKit is the only way in.

`/register` was deleted in the cutover, so every test that needs an
authenticated caller goes through the flow the product itself uses: POST
/auth/code, then POST /auth/session with the mailed code. Two doubles make
that work offline, and they are useless apart, so one fixture installs both.

`FakeWorkOsClient` mints an opaque `at-<workos_user_id>` access token rather
than a signed JWT, while the production `AuthKitVerifier` checks a real JWT's
signature, issuer and `client_id` claim against a JWKS fetched from
api.workos.com -- exactly what no test may do. `_FakeAuthKitVerifier` reads the
double's token straight back instead. `AuthKitVerifier.verify`'s contract is
"token in, workos_user_id out"; this satisfies that without pretending to
check a signature the double never produced.

Both overrides RESTORE the previous value rather than pop it. The root
conftest installs a default under each key -- one shared fake client, and a
verifier whose resolver deliberately raises so an accidental live JWKS fetch
fails loudly rather than merely looking slow. Popping would not undo this
override, it would delete theirs, and every later test in the session that
touched an /auth route would 500 on the placeholder's RuntimeError, looking
like a product bug in a file that changed nothing.

Opt-in rather than autouse for the same reason: a file that never signs in
should keep the root conftest's raising verifier underneath it.
"""
from contextlib import contextmanager

import pytest

from agentpit.api import deps
from agentpit.api.main import app
from agentpit.auth.dependencies import make_current_user_dep
from agentpit.auth.workos_client import FakeWorkOsClient
from agentpit.domain.exceptions import InvalidCredentialsError


@contextmanager
def _overriding(key, value):
    previous = app.dependency_overrides.get(key)
    app.dependency_overrides[key] = value
    try:
        yield
    finally:
        if previous is None:
            app.dependency_overrides.pop(key, None)
        else:
            app.dependency_overrides[key] = previous


class _FakeAuthKitVerifier:
    """Maps `FakeWorkOsClient`'s access token back to its `workos_user_id`."""

    def verify(self, token: str) -> str:
        if not token.startswith("at-"):
            raise InvalidCredentialsError("invalid session")
        return token[3:]


@pytest.fixture
def workos():
    """The offline sign-in world: a fake WorkOS, and a bearer path that
    accepts what it hands out."""
    fake = FakeWorkOsClient()
    with _overriding(deps.get_workos_client, lambda: fake), _overriding(
        deps.get_current_user, make_current_user_dep(_FakeAuthKitVerifier())
    ):
        yield fake


@pytest.fixture
def sign_in(workos):
    """`sign_in(client, email)` -> the `/auth/session` body for a live session.

    Creates the account on first use, exactly as the product does: there is no
    separate signup step any more.
    """

    def _sign_in(client, email: str) -> dict:
        client.post("/auth/code", json={"email": email})
        resp = client.post(
            "/auth/session", json={"email": email, "code": workos.last_code(email)}
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    return _sign_in
