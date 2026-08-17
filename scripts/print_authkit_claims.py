#!/usr/bin/env python
"""Print an AuthKit access token's claims, WITHOUT verifying it.

Not verifying is the point. This exists to answer "what does a real token
actually contain", which is the question `AuthKitVerifier` answers by assuming.
Verifying here would use the same assumptions and prove nothing.

The project has already paid once for skipping this: the first verifier was
written from documentation, pinned `iss` to the AuthKit domain and required an
`aud` claim, and would have rejected every sign-in in production -- while every
test passed, because the tests minted their own tokens carrying exactly the
claims the code assumed. Run this against a token from each NEW flow before
trusting it.

Usage:
    .venv/bin/python scripts/print_authkit_claims.py <access_token>
    .venv/bin/python scripts/print_authkit_claims.py --expect-client-id client_… <token>

Compare the output against `agentpit.auth.authkit_tokens.authkit_issuer(client_id)`.
"""
import argparse
import json
import sys

import jwt

from agentpit.auth.authkit_tokens import authkit_issuer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("token", help="the access_token, as issued")
    parser.add_argument(
        "--expect-client-id",
        default=None,
        help="check iss and client_id against this application id",
    )
    args = parser.parse_args()

    try:
        claims = jwt.decode(args.token, options={"verify_signature": False})
    except Exception as exc:
        print(f"not a JWT: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(claims, indent=2, sort_keys=True))

    iat, exp = claims.get("iat"), claims.get("exp")
    if isinstance(iat, int) and isinstance(exp, int):
        # Measured 2026-08-11 and confirmed as configured (accessTokenExpiry) on
        # 2026-08-12: 300 seconds.
        print(f"\nlifetime: {exp - iat}s")

    print(f"aud present: {'aud' in claims}  <- expected False")

    if args.expect_client_id is None:
        return 0

    expected_iss = authkit_issuer(args.expect_client_id)
    iss_ok = claims.get("iss") == expected_iss
    cid_ok = claims.get("client_id") == args.expect_client_id
    print(f"\niss     : {claims.get('iss')}")
    print(f"expected: {expected_iss}")
    print(f"iss matches what AuthKitVerifier pins : {iss_ok}")
    print(f"client_id matches                     : {cid_ok}")
    # A mismatch means the token came from a different flow -- most likely the
    # `/oauth2/*` endpoints on the AuthKit domain, which issue a different
    # issuer. The verifier would reject it.
    return 0 if (iss_ok and cid_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
