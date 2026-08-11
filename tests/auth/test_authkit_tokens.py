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
