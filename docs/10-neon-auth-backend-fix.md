# Neon Auth backend JWT verification configuration

The FastAPI settings must declare `neon_auth_url` and `neon_auth_jwks_url`.
Without these Pydantic settings fields, `extra="ignore"` discards Render's
`NEON_AUTH_URL` and `NEON_AUTH_JWKS_URL` environment variables, causing the
JWT verifier to reject every Neon token before signature verification.

Render must have:
- `NEON_AUTH_URL=https://ep-green-scene-bijgdygu.neonauth.c-5.ap-southeast-1.aws.neon.tech/neondb/auth`
- `NEON_AUTH_JWKS_URL=https://ep-green-scene-bijgdygu.neonauth.c-5.ap-southeast-1.aws.neon.tech/neondb/auth/.well-known/jwks.json`

The verifier uses the origin (`https://<auth-host>`) as issuer, matching Neon
Managed Auth's JWT issuer convention. After deploying, test GET /auth/me with a
fresh login. Never log or expose the JWT or session cookie.
