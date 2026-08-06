"""The five checks on a Google ID token, each asserted on its own.

No network: the test mints its own RS256 tokens with a locally generated key
and hands the verifier a stub JWKS client that returns the matching public key.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClientConnectionError

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


def test_a_jwks_outage_is_not_an_invalid_credential():
    """Reaching Google is our problem, not the user's. Told "invalid
    credential", somebody with a perfectly good account would retype their
    way nowhere."""

    class _UnreachableJwkClient:
        def get_signing_key_from_jwt(self, token):
            raise PyJWKClientConnectionError("could not reach the JWKS endpoint")

    verifier = GoogleTokenVerifier(CLIENT_ID, jwk_client=_UnreachableJwkClient())
    with pytest.raises(PyJWKClientConnectionError):
        verifier.verify(_token())
