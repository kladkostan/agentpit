"""Verification of AuthKit access tokens.

AuthKit signs its access tokens asymmetrically and publishes the public keys
at `<authkit-domain>/oauth2/jwks`. That is the whole difference from
`JwtCoder`, which signs symmetrically with a secret we hold: here we can only
verify, never mint, which is the point.

Two claims are checked beyond the signature, and neither is optional.
`issuer` pins the tokens to our AuthKit domain. `audience` pins them to our
client id -- without it, a token minted for a DIFFERENT WorkOS application
would carry a valid signature from the same provider and authenticate here.
"""
from collections.abc import Callable
from typing import Any

import jwt

from agentpit.domain.exceptions import InvalidCredentialsError

KeyResolver = Callable[[str], Any]


def remote_jwks_resolver(authkit_domain: str) -> KeyResolver:
    """Resolve signing keys from the live JWKS, with PyJWT's own caching.

    `PyJWKClient` caches keys and refetches on an unknown `kid`, so a key
    rotation upstream costs one extra request rather than an outage.
    """
    client = jwt.PyJWKClient(f"{authkit_domain.rstrip('/')}/oauth2/jwks")
    return lambda token: client.get_signing_key_from_jwt(token).key


class AuthKitVerifier:
    def __init__(
        self, *, issuer: str, audience: str, key_resolver: KeyResolver
    ):
        self._issuer = issuer
        self._audience = audience
        self._resolve = key_resolver

    def verify(self, token: str) -> str:
        """The WorkOS user id this token belongs to.

        Every failure is one failure: a bad signature, a wrong audience, an
        expired token and outright garbage all raise `InvalidCredentialsError`,
        because a caller that could tell them apart could use the difference to
        probe.
        """
        try:
            key = self._resolve(token)
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
            )
        except Exception as exc:
            raise InvalidCredentialsError("invalid session") from exc
        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise InvalidCredentialsError("invalid session")
        return sub
