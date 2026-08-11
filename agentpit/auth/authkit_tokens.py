"""Verification of AuthKit access tokens.

AuthKit signs its access tokens asymmetrically and publishes the public keys as
a JWKS. That is the whole difference from `JwtCoder`, which signs symmetrically
with a secret we hold: here we can only verify, never mint, which is the point.

Everything below about the token's shape was read off a REAL token minted
against the staging environment on 2026-08-11, not inferred from documentation.
The first version of this module was inferred, and it was wrong in two ways
that would each have rejected every sign-in in production while every test
passed -- because the tests minted their own tokens carrying exactly the
claims the code assumed. The real claim set is:

    iss        https://api.workos.com/user_management/<client_id>
    sub        user_...          the WorkOS user id
    client_id  client_...        the application the token was minted for
    sid, jti, auth_time, iat, exp     (exp - iat was 300s)

Two consequences, both counter-intuitive:

**The issuer is not the AuthKit domain.** `WORKOS_AUTHKIT_DOMAIN`
(`something.authkit.app`) hosts the sign-in surface and serves a JWKS, but the
token says it was issued by `api.workos.com/user_management/<client_id>`.
Comparing against the domain rejects everything.

**There is no `aud` claim at all.** Passing `audience=` to `jwt.decode` makes
PyJWT raise `MissingRequiredClaimError` on a token that has none, so the check
meant to pin tokens to our application instead rejected all of them. The
pinning still has to happen -- without it a token minted for a DIFFERENT WorkOS
application carries a valid signature from the same provider and would
authenticate here -- so it is done explicitly against the `client_id` claim.

Both the issuer and the JWKS URL are derived from `client_id` rather than
configured. There is then exactly one WorkOS value an operator can get wrong,
and getting it wrong fails loudly at the first request instead of half-working.
"""
from collections.abc import Callable
from typing import Any

import jwt

from agentpit.domain.exceptions import InvalidCredentialsError

KeyResolver = Callable[[str], Any]

_API_BASE = "https://api.workos.com"


def authkit_issuer(client_id: str) -> str:
    """The `iss` an AuthKit access token for this application carries."""
    return f"{_API_BASE}/user_management/{client_id}"


def authkit_jwks_url(client_id: str) -> str:
    """Where this application's signing keys live.

    `<authkit-domain>/oauth2/jwks` serves the same key -- verified against
    staging, both endpoints returned `sso_oidc_key_pair_01KZRZ1Q...`. This form
    is preferred because it derives from `client_id`, the value the issuer is
    already derived from, so the two cannot disagree.
    """
    return f"{_API_BASE}/sso/jwks/{client_id}"


def remote_jwks_resolver(client_id: str) -> KeyResolver:
    """Resolve signing keys from the live JWKS, with PyJWT's own caching.

    `PyJWKClient` caches keys and refetches on an unknown `kid`, so a key
    rotation upstream costs one extra request rather than an outage.
    """
    client = jwt.PyJWKClient(authkit_jwks_url(client_id))
    return lambda token: client.get_signing_key_from_jwt(token).key


class AuthKitVerifier:
    def __init__(self, *, client_id: str, key_resolver: KeyResolver):
        self._client_id = client_id
        self._issuer = authkit_issuer(client_id)
        self._resolve = key_resolver

    def verify(self, token: str) -> str:
        """The WorkOS user id this token belongs to.

        Every failure is one failure: a bad signature, a foreign application,
        an expired token and outright garbage all raise
        `InvalidCredentialsError`, because a caller that could tell them apart
        could use the difference to probe.
        """
        try:
            key = self._resolve(token)
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self._issuer,
                # No `audience=`: these tokens carry no `aud`, and asking for
                # one rejects every valid token. See the module docstring.
                options={"require": ["exp", "iat", "iss", "sub"]},
            )
        except Exception as exc:
            raise InvalidCredentialsError("invalid session") from exc

        # The `aud` check that cannot be done as an `aud` check. A token minted
        # for another WorkOS application is signed by the same provider and
        # would otherwise verify perfectly here.
        if claims.get("client_id") != self._client_id:
            raise InvalidCredentialsError("invalid session")

        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise InvalidCredentialsError("invalid session")
        return sub
