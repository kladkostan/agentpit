"""The ceiling on `POST /auth/code`.

That endpoint is unauthenticated, is the only door into the product since the
cutover, and every request that reaches WorkOS costs an email. So these tests
care about two things a status code alone cannot show: that a refused request
is refused BEFORE WorkOS is called, and that the two rules key on different
subjects so neither leaves the other's hole open.
"""
import pytest
from fastapi.testclient import TestClient

from agentpit.api import deps
from agentpit.api.main import app
from agentpit.auth.workos_client import FakeWorkOsClient
from agentpit.config import Settings
from agentpit.db.session import DbSession
from agentpit.db.table_write import TableWrite
from agentpit.services.authkit_service import AuthKitService


@pytest.fixture
def workos():
    fake = FakeWorkOsClient()
    app.dependency_overrides[deps.get_workos_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(deps.get_workos_client, None)


def _limit(rule: str) -> int:
    """The configured allowance for one rule, read rather than duplicated."""
    return next(n for r, _w, n in AuthKitService.RATE_LIMITS if r == rule)


def test_a_second_code_for_one_address_inside_a_minute_is_refused(workos):
    with TestClient(app) as client:
        first = client.post("/auth/code", json={"email": "a@example.com"})
        second = client.post("/auth/code", json={"email": "a@example.com"})
    assert first.status_code == 202, first.text
    assert second.status_code == 429, second.text
    # The client is told when to come back, not merely that it failed.
    assert second.headers["Retry-After"] == "60"


def test_a_refused_request_never_reaches_workos(workos):
    # The whole point of the ordering. A status code cannot show this: a local
    # refusal and a refusal from WorkOS both end in 429.
    with TestClient(app) as client:
        client.post("/auth/code", json={"email": "b@example.com"})
        before = len(workos._codes)
        client.post("/auth/code", json={"email": "b@example.com"})
    assert len(workos._codes) == before


def test_the_hourly_address_rule_survives_the_per_minute_one(workos):
    # Walk past the 60s rule by advancing the stored window instead of sleeping,
    # and confirm the hourly ceiling still stops the fifth-and-onwards attempt.
    db = DbSession(Settings().database_url)
    hourly = _limit("email:1h")
    email = "c@example.com"
    with TestClient(app) as client:
        for _ in range(hourly):
            resp = client.post("/auth/code", json={"email": email})
            assert resp.status_code == 202, resp.text
            with db.write() as conn:
                conn.execute(
                    "UPDATE auth_code_attempts SET WINDOW_START = 0 "
                    "WHERE BUCKET = %s",
                    (f"email:60s:{email}",),
                )
        # The per-minute rule is clear again, the hourly one is spent.
        resp = client.post("/auth/code", json={"email": email})
    assert resp.status_code == 429, resp.text
    assert resp.headers["Retry-After"] == "3600"


def test_a_different_address_is_not_blocked_by_another_s_limit(workos):
    with TestClient(app) as client:
        client.post("/auth/code", json={"email": "d@example.com"})
        other = client.post("/auth/code", json={"email": "e@example.com"})
    assert other.status_code == 202, other.text


def test_rotating_the_address_still_runs_into_the_per_ip_rule(workos):
    # The reason the address rule alone is not enough: an attacker who changes
    # the address on every request pays nothing under it, and every request is
    # an email we are billed for.
    per_ip = _limit("ip:1h")
    with TestClient(app) as client:
        codes = [
            client.post("/auth/code", json={"email": f"rot{i}@example.com"}).status_code
            for i in range(per_ip + 1)
        ]
    assert codes[:per_ip] == [202] * per_ip
    assert codes[-1] == 429


def test_the_counter_is_atomic_under_a_lost_race():
    # Two callers reading the same stale count and both passing is the failure
    # this table exists to prevent, and the reason the predicate and the
    # increment are one statement. Driven at the writer, where the race is.
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        first = TableWrite.claim_auth_code_attempt(conn, "race", 1000, 60, 1)
        second = TableWrite.claim_auth_code_attempt(conn, "race", 1000, 60, 1)
    assert first is True
    assert second is False


def test_a_window_that_has_expired_starts_over():
    db = DbSession(Settings().database_url)
    with db.write() as conn:
        assert TableWrite.claim_auth_code_attempt(conn, "roll", 1000, 60, 1) is True
        assert TableWrite.claim_auth_code_attempt(conn, "roll", 1030, 60, 1) is False
        # 61 seconds after the window opened, the allowance is fresh.
        assert TableWrite.claim_auth_code_attempt(conn, "roll", 1061, 60, 1) is True
