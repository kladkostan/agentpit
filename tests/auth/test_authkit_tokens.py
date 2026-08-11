"""The token shape here is copied from a REAL staging token, not invented.

The previous version of this file minted tokens carrying whatever claims the
implementation expected, so it passed against an implementation that would have
rejected every genuine sign-in. Every token below therefore uses the claim set
observed on 2026-08-11: `iss` = api.workos.com/user_management/<client_id>, a
`client_id` claim, and NO `aud`.
"""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from agentpit.auth.authkit_tokens import (
    AuthKitVerifier,
    authkit_issuer,
    authkit_jwks_url,
)
from agentpit.domain.exceptions import InvalidCredentialsError

CLIENT_ID = "client_01KZRZ1QQXA15KX04VQBZPE0DZ"
ISSUER = authkit_issuer(CLIENT_ID)

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key=_KEY, *, sub="user_01", iss=ISSUER, client_id=CLIENT_ID,
           exp_delta=300, extra=None, drop=()):
    now = int(time.time())
    claims = {
        "iss": iss,
        "sub": sub,
        "sid": "session_01",
        "jti": "01",
        "auth_time": now,
        "client_id": client_id,
        "iat": now,
        "exp": now + exp_delta,
    }
    claims.update(extra or {})
    for name in drop:
        claims.pop(name, None)
    return jwt.encode(claims, key, algorithm="RS256")


def _verifier() -> AuthKitVerifier:
    # The resolver stands in for the remote JWKS: same contract, no network.
    return AuthKitVerifier(
        client_id=CLIENT_ID, key_resolver=lambda _token: _KEY.public_key()
    )


def test_issuer_is_derived_from_the_client_id_not_the_authkit_domain():
    # The mistake this whole module was rewritten for: the AuthKit domain
    # serves the sign-in surface and a JWKS, but it is NOT what `iss` says.
    assert ISSUER == (
        "https://api.workos.com/user_management/client_01KZRZ1QQXA15KX04VQBZPE0DZ"
    )
    assert "authkit.app" not in ISSUER
    assert authkit_jwks_url(CLIENT_ID) == (
        "https://api.workos.com/sso/jwks/client_01KZRZ1QQXA15KX04VQBZPE0DZ"
    )


def test_a_real_shaped_token_verifies_and_returns_the_workos_user_id():
    assert _verifier().verify(_token(sub="user_abc")) == "user_abc"


def test_a_token_with_no_aud_claim_is_accepted():
    # Explicit, because requiring `aud` is exactly what broke this before and
    # a future edit adding `audience=` back would pass every other test here.
    decoded = jwt.decode(_token(), options={"verify_signature": False})
    assert "aud" not in decoded
    assert _verifier().verify(_token()) == "user_01"


def test_a_token_for_another_workos_application_is_rejected():
    # Same provider, same signature, different customer. This is the check
    # that `aud` would normally do.
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(_token(client_id="client_someone_else"))


def test_a_token_with_no_client_id_claim_is_rejected():
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(_token(drop=("client_id",)))


def test_token_signed_by_an_unknown_key_is_rejected():
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(_token(key=_OTHER_KEY))


def test_wrong_issuer_is_rejected():
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(_token(iss="https://evil.example"))


def test_the_authkit_domain_as_issuer_is_rejected():
    # Guards the exact regression: someone "fixes" the issuer back to the
    # AuthKit domain because that is what the setting is named.
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(
            _token(iss="https://accurate-spoon-64-staging.authkit.app")
        )


def test_expired_token_is_rejected():
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(_token(exp_delta=-1))


def test_a_token_without_exp_is_rejected():
    # Without `require`, PyJWT happily accepts a token that never expires.
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(_token(drop=("exp",)))


def test_garbage_is_rejected_rather_than_raising_something_else():
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify("not-a-jwt")


def test_token_without_sub_is_rejected():
    with pytest.raises(InvalidCredentialsError):
        _verifier().verify(_token(drop=("sub",)))
