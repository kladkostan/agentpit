"""What is left of in-page Google sign-in: the 410 where it used to be.

`POST /auth/google` took a Google credential minted in our own page by Google
Identity Services. Google now arrives the other way round -- the browser is
sent to AuthKit's authorize URL and comes back to `/auth/callback` with an
authorization code -- so no credential is ever posted here again. The linking
rules this file used to hold (sub-first lookup, case-insensitive email match,
retiring the password on the account) all lived in `AuthService.google_sign_in`
behind that endpoint and are unreachable from HTTP now.

Nothing was deleted from `agentpit/` to make that true, so this file shrinking
is not a loss of the code's coverage: `GoogleTokenVerifier` is still exercised
by `tests/test_google_verifier.py` and `tests/test_config_google.py`, and the
redirect that replaced this endpoint by
`tests/api/test_authkit_routes.py`'s /auth/callback tests. Reverting the
cutover commit brings the endpoint and its rules back working; plan 4 deletes
them for good.
"""

from fastapi.testclient import TestClient

from agentpit.api.main import app


def test_the_in_page_google_endpoint_is_gone():
    with TestClient(app) as client:
        resp = client.post("/auth/google", json={"credential": "anything"})
    assert resp.status_code == 410, resp.text


def test_the_410_does_not_depend_on_a_google_client_id_being_configured():
    """It answers before anything is looked at, verifier or credential.

    The old endpoint 503'd on a deployment with no GOOGLE_CLIENT_ID and 401'd
    on a bad credential, so a caller could still tell those two apart. Now
    every request gets the same answer -- which is what "removed" means, and
    what stops the route reading as merely misconfigured.
    """
    with TestClient(app) as client:
        assert client.post("/auth/google", json={"credential": "x"}).status_code == 410
        # No body at all: the route takes no payload any more, so not even a
        # 422 comes back ahead of the 410.
        assert client.post("/auth/google").status_code == 410
