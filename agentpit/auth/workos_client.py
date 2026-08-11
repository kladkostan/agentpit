"""The WorkOS surface agentpit uses, and nothing more.

A Protocol rather than the SDK client itself, for one reason: every test in
this repo runs offline, and a service that reaches out to api.workos.com from
a unit test is a test that fails on a train. `FakeWorkOsClient` is the double
every test uses; `RealWorkOsClient` is the only place the SDK is touched.

The surface is deliberately narrow. Plan 2 widens it; this plan needs exactly
what the migration script needs.
"""
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

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


class WorkOsError(RuntimeError):
    """Anything the WorkOS API refused or failed to answer.

    One type for every failure, deliberately: the migration script catches per
    account and carries on, and it can only do that if it knows what to catch.
    The message never carries the request — the bearer token lives in the
    headers and a traceback from here can reach a log.
    """


API_BASE = "https://api.workos.com"

#: bcrypt output: $2a/$2b/$2y, a cost, and the salt+digest. Matched wherever it
#: appears, not anchored, because it is being hunted inside a JSON body.
_BCRYPT_RE = re.compile(r"\$2[aby]?\$\d{2}\$[./A-Za-z0-9]{0,53}")


def _redact(text: str) -> str:
    """Strip anything password-shaped out of an error body before it is stored.

    The body is kept because it names the field WorkOS objected to, which is
    what makes a failed import diagnosable. But a 422 is entitled to quote the
    value it rejected, and the value we send is a bcrypt hash lifted from
    `users.PASSWORD_HASH`. `migrate_users` catches per account and calls
    `log.exception`, so without this a rejected import writes a live password
    hash to stdout next to the address it belongs to, during a hand-run
    production migration.
    """
    return _BCRYPT_RE.sub("[redacted]", text)


class RealWorkOsClient:
    """The WorkOS REST API over the httpx we already have.

    Not the `workos` SDK, and the reason is a pin: every published version of
    it requires `httpx~=0.28` while this repo runs `httpx[http2]==0.27.0`, the
    client underneath the order-book mirror and the Polymarket sync. The
    current release also wants `cryptography~=50.0` against our `<47`, which
    sits under eth-account's signing. Six REST calls are not worth moving
    either. If the SDK ever becomes worth it, it replaces this class and
    nothing else — that is what the Protocol is for.
    """

    def __init__(self, api_key: str, client_id: str, *, transport=None):
        self._client_id = client_id
        self._http = httpx.Client(
            base_url=API_BASE,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15.0,
            transport=transport,
        )

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            # Bare `exc` would be fine, but chaining keeps the cause visible in
            # a traceback while the message stays ours.
            raise WorkOsError(f"WorkOS request failed: {method} {path}") from exc
        if response.status_code >= 400:
            # The body may name the field WorkOS objected to, which is what
            # makes a failed migration diagnosable. The request is not
            # included: it carries the hash, and the headers carry the key.
            raise WorkOsError(
                f"WorkOS {method} {path} returned {response.status_code}: "
                f"{_redact(response.text)[:500]}"
            )
        return response.json()

    @staticmethod
    def _to_user(payload: dict) -> WorkOsUser:
        return WorkOsUser(
            workos_user_id=payload["id"],
            email=payload["email"],
            email_verified=bool(payload.get("email_verified")),
        )

    def create_user(self, *, email: str, password_hash: str | None) -> WorkOsUser:
        existing = self.find_user_by_email(email)
        if existing is not None:
            # Idempotent by construction: the migration script is re-runnable
            # and a second call for the same address must not mint a second
            # identity for one person.
            return existing
        body: dict[str, object] = {"email": email, "email_verified": True}
        if password_hash:
            # Omitted entirely rather than sent as null when absent: a
            # Google-sourced account never had a password, and `null` is a
            # different request from silence.
            body["password_hash"] = password_hash
            body["password_hash_type"] = "bcrypt"
        return self._to_user(
            self._request("POST", "/user_management/users", json=body)
        )

    def find_user_by_email(self, email: str) -> WorkOsUser | None:
        page = self._request(
            "GET", "/user_management/users", params={"email": email, "limit": 1}
        )
        for user in page.get("data") or []:
            return self._to_user(user)
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


def build_workos_client(
    settings: Settings, *, transport=None
) -> WorkOsClient | None:
    """The configured client, or None when WorkOS is not set up.

    None is a first-class answer, not a failure: an environment without
    WORKOS_API_KEY is every developer machine until the account exists, and
    startup must not depend on it.

    `transport` exists so tests can drive the REAL client over
    `httpx.MockTransport`. Without it the only code ever exercised offline is
    the double, and the double cannot be wrong about a URL, a header or a
    request body — the three things that are actually easy to get wrong here.
    """
    if not settings.workos_api_key or not settings.workos_client_id:
        return None
    return RealWorkOsClient(
        settings.workos_api_key, settings.workos_client_id, transport=transport
    )
