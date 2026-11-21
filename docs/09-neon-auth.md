# Neon Auth integration

Kachra Mitra keeps its existing HTML/CSS/JavaScript interface and uses Neon Managed
Better Auth for email/password signup, login, session restoration, and logout.

## Neon Console setup

- Enable Better Auth on the same Neon branch used by `DATABASE_URL` (the production branch).
- Add the deployed Vercel origin to Better Auth trusted domains (scheme + hostname only).
- Keep email signup and email signin enabled.
- Configure email delivery before enabling email verification.
- Google sign-in is not activated in the app yet; configure its provider credentials separately.

## Render environment

`render.yaml` contains the public Auth base URL and JWKS URL. If the production branch
changes, update both variables to the URLs shown by Neon for that branch. Do not expose
`DATABASE_URL`, Neon API keys, or other secrets in frontend files.

## Existing accounts and app roles

New Neon Auth accounts are created in `neon_auth.user`. On the first authenticated request,
the API mirrors the identity into the app's `users` table. Existing app accounts are matched
by email so their `is_admin` setting and scan history remain attached to the existing row.
Neon manages passwords; mirrored accounts have an unusable local password marker.

To promote an app user to admin, use the app's `users` table:

```sql
UPDATE users SET is_admin = 1 WHERE email = 'person@example.com';
```

The admin page reuses the signed-in app's Neon JWT. FastAPI verifies the JWT signature
against `NEON_AUTH_JWKS_URL`, checks the issuer, then checks the app's `is_admin` flag.

## Verification before production

1. Add the Vercel domain and any local development origin to Neon trusted domains.
2. Set `NEON_AUTH_URL` and `NEON_AUTH_JWKS_URL` on Render.
3. Deploy the backend and frontend.
4. Test signup, sign-in, `/auth/me`, logout, scan ownership, and admin access.
5. Confirm a signup appears in `neon_auth.user` and its app profile appears in `public.users`.

The previous `/auth/signup` and `/auth/login` endpoints remain temporarily for rollback;
the public frontend no longer calls them.
