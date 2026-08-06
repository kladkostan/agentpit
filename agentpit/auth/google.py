"""Verification of Google Identity Services ID tokens.

The credential the browser hands us is a JWT signed by Google. It is verified
locally against Google's published JWKS rather than by calling the `tokeninfo`
endpoint: that keeps a network round trip — and its failure mode — out of the
moment somebody is signing up, and local verification is what Google
recommends for production.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from jwt import PyJWKClient, PyJWKClientConnectionError, PyJWTError

from agentpit.domain.exceptions import InvalidCredentialsError

GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"

# Google mints both spellings; a token carrying either is genuine.
GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})


@dataclass(frozen=True)
class GoogleIdentity:
    """The two claims we act on, once every check has passed."""

    sub: str
    email: str


class GoogleTokenVerifier:
    """Checks a Google ID token and returns who it says signed in.

    `jwk_client` exists so tests can supply a key without reaching the network;
    production leaves it unset and gets the caching JWKS client.
    """

    def __init__(self, client_id: str, jwk_client=None):
        self._client_id = client_id
        # Keys are cached: Google rotates them slowly, and fetching per
        # sign-in would put their availability in front of ours.
        self._jwk_client = (
            jwk_client
            if jwk_client is not None
            else PyJWKClient(GOOGLE_JWKS_URI, cache_keys=True)
        )

    def verify(self, credential: str) -> GoogleIdentity:
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(credential)
            claims = jwt.decode(
                credential,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._client_id,
                issuer=GOOGLE_ISSUERS,
                options={"require": ["exp", "iss", "aud", "sub", "email"]},
            )
        except PyJWKClientConnectionError:
            # We could not reach Google to fetch its signing keys. That is our
            # outage, not a bad credential, and it must not be reported to the
            # person signing in as "your credential is invalid" -- let it
            # surface as the server error it is.
            raise
        except PyJWTError as exc:
            # Bad signature, wrong audience, expired, malformed, or a `kid`
            # Google no longer publishes -- to the caller they are one thing:
            # this credential proves nothing. The reason stays in the
            # traceback, not in the response.
            raise InvalidCredentialsError("invalid Google credential") from exc

        # Checked after the signature rather than alongside it: `email_verified`
        # is what makes linking by address safe, so it has to be a claim Google
        # actually signed, not one we read off an unverified token.
        if claims.get("email_verified") is not True:
            raise InvalidCredentialsError("Google account email is not verified")

        return GoogleIdentity(sub=str(claims["sub"]), email=str(claims["email"]))
