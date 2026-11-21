"""Verification helpers for Neon Managed Better Auth JWTs."""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse

import jwt
from jwt import PyJWKClient


@lru_cache(maxsize=8)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_jwk_set=True, lifespan=300, timeout=8)


def verify_neon_token(settings, token: str) -> dict | None:
    """Verify signature, issuer and expiry; never trust decoded claims alone."""
    auth_url = (getattr(settings, "neon_auth_url", "") or "").strip()
    jwks_url = (getattr(settings, "neon_auth_jwks_url", "") or "").strip()
    if not auth_url or not jwks_url or not token:
        return None

    parsed = urlparse(auth_url)
    issuer = f"{parsed.scheme}://{parsed.netloc}"
    if parsed.scheme != "https" or not parsed.netloc:
        return None

    try:
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["EdDSA"],
            issuer=issuer,
            options={"verify_aud": False, "require": ["sub", "exp", "iss"]},
            leeway=30,
        )
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            return None
        return claims
    except Exception:  # noqa: BLE001 - invalid/expired/unverifiable tokens are unauthenticated
        return None
