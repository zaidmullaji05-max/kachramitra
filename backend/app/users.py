"""User accounts: sign up, sign in, profile.

Optional by design. The scanner, chat, map and history keep working without an account;
signing in simply attaches scans to a durable identity instead of a browser device id.

Storage is Neon Postgres when `DATABASE_URL` is set (accounts then survive redeploys),
otherwise the same local SQLite file as the rest of the app.

Security choices, stated plainly:
* scrypt password hashing, never plaintext, never reversible;
* one generic "wrong email or password" message;
* failed logins throttled per IP + email;
* signed tokens with an expiry, no server-side session table;
* every request re-loads the user, so deactivating an account takes effect immediately.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request

from . import db, security
from .schemas import LoginRequest, ProfileUpdate, SignupRequest

router = APIRouter(prefix="/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_FAILURES = 10
FAILURE_WINDOW_S = 600
SIGNUP_PER_HOUR = 6

_login_failures: dict[str, deque[float]] = defaultdict(deque)
_signups: dict[str, deque[float]] = defaultdict(deque)


def _throttled(store: dict[str, deque[float]], key: str, limit: int, window: int) -> bool:
    now = time.monotonic()
    q = store[key]
    while q and now - q[0] > window:
        q.popleft()
    return len(q) >= limit


def _record(store: dict[str, deque[float]], key: str) -> None:
    store[key].append(time.monotonic())


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _settings(request: Request):
    return request.app.state.settings


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


def user_from_token(settings, token: str) -> dict | None:
    """Resolve either a legacy app token or a verified Neon Auth JWT to an app user."""
    if not token:
        return None

    # Keep existing sessions valid during migration.
    claims = security.read_user_token(token, settings.auth_secret_value)
    if claims:
        user = db.get_user(settings, claims["user_id"])
        return user if user and user["is_active"] else None

    # New sessions are issued by Neon Managed Better Auth.
    from .neon_auth import verify_neon_token
    neon_claims = verify_neon_token(settings, token)
    if not neon_claims:
        return None

    user_id = neon_claims["sub"]
    email = (neon_claims.get("email") or "").strip().lower()
    name = (neon_claims.get("name") or (email.split("@")[0] if email else "User")).strip()[:80]
    user = db.get_user(settings, user_id)
    if not user and email:
        # Preserve existing app roles and scan history for users who already had an account.
        user = db.get_user_by_email(settings, email)
    if not user:
        user = {
            "id": user_id,
            "email": email,
            "name": name,
            # Neon owns the password. This unusable marker prevents legacy password login.
            "password_hash": "managed-by-neon-auth",
            "is_active": 1,
            "is_admin": 0,
            "created_at": db.now_iso(),
            "last_login_at": db.now_iso(),
        }
        try:
            db.create_user(settings, user)
        except Exception:
            # Concurrent first requests may race on the unique email constraint.
            user = db.get_user_by_email(settings, email) if email else None
            if not user:
                raise
    if not user or not user["is_active"]:
        return None
    return user


def current_user(request: Request, required: bool = False) -> dict | None:
    """Resolve the Authorization header. Used directly by /classify and /history."""
    user = user_from_token(_settings(request), _bearer(request))
    if not user and required:
        raise HTTPException(status_code=401, detail="sign in required or session expired")
    return user


def _issue(settings, user: dict) -> dict:
    ttl = int(settings.auth_token_ttl_hours) * 3600
    token = security.issue_user_token(settings.auth_secret_value, user["id"], ttl)
    return {
        **token,
        "ttl_s": ttl,
        "user": db.public_user(user),
    }


def ensure_admin(settings) -> None:
    """Create or promote the operator account when ADMIN_EMAIL and ADMIN_PASSWORD are set.

    The passphrase-only admin login still works without this. Seeding a row is what lets
    the same person sign in from the app's Log in button and land in the admin dashboard.
    """
    email = normalise_email(getattr(settings, "admin_email", ""))
    password = (getattr(settings, "admin_password", "") or "").strip()
    if not email or len(password) < 8:
        return
    existing = db.get_user_by_email(settings, email)
    if existing:
        db.update_user(settings, existing["id"], {
            "password_hash": security.hash_password(password),
            "is_admin": 1,
            "is_active": 1,
        })
        return
    db.create_user(settings, {
        "id": security.new_user_id(),
        "email": email,
        "name": "Admin",
        "password_hash": security.hash_password(password),
        "is_active": 1,
        "is_admin": 1,
        "created_at": db.now_iso(),
        "last_login_at": None,
    })


def _check_password_shape(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")
    if len(password) > 128:
        raise HTTPException(status_code=400, detail="password is too long (128 max)")


# --------------------------------------------------------------------------- endpoints
@router.post("/signup")
async def signup(req: SignupRequest, request: Request):
    settings = _settings(request)
    ip = _ip(request)
    if _throttled(_signups, ip, SIGNUP_PER_HOUR, 3600):
        raise HTTPException(status_code=429, detail="too many accounts from this network, try later")

    email = normalise_email(req.email)
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(status_code=400, detail="enter a valid email address")
    _check_password_shape(req.password)

    if db.get_user_by_email(settings, email):
        raise HTTPException(status_code=409, detail="an account with this email already exists")

    name = (req.name or "").strip()[:80] or email.split("@")[0][:80]
    user = {
        "id": security.new_user_id(),
        "email": email,
        "name": name,
        "password_hash": security.hash_password(req.password),
        "is_active": 1,
        "is_admin": 0,
        "created_at": db.now_iso(),
        "last_login_at": db.now_iso(),
    }
    try:
        db.create_user(settings, user)
    except Exception as exc:  # noqa: BLE001 - unique email race between two requests
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise HTTPException(status_code=409, detail="an account with this email already exists") from exc
        raise

    _record(_signups, ip)
    db.claim_scans(settings, request.headers.get("x-device-id", ""), user["id"])
    return _issue(settings, user)


@router.post("/login")
async def login(req: LoginRequest, request: Request):
    settings = _settings(request)
    email = normalise_email(req.email)
    key = f"{_ip(request)}:{email}"
    if _throttled(_login_failures, key, MAX_FAILURES, FAILURE_WINDOW_S):
        raise HTTPException(status_code=429, detail="too many failed sign-ins, wait 10 minutes")

    user = db.get_user_by_email(settings, email) if email else None
    if not user or not security.verify_password(req.password, user["password_hash"]):
        _record(_login_failures, key)
        raise HTTPException(status_code=401, detail="wrong email or password")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="this account has been disabled")

    _login_failures.pop(key, None)
    db.touch_login(settings, user["id"], db.now_iso())
    user["last_login_at"] = db.now_iso()
    db.claim_scans(settings, request.headers.get("x-device-id", ""), user["id"])
    return _issue(settings, user)


@router.get("/me")
async def me(request: Request):
    user = current_user(request, required=True)
    return {"user": db.public_user(user), "stats": db.user_summary(_settings(request), user["id"])}


@router.patch("/me")
async def update_me(req: ProfileUpdate, request: Request):
    user = current_user(request, required=True)
    settings = _settings(request)
    fields: dict = {}

    if req.name is not None:
        name = req.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name cannot be empty")
        fields["name"] = name[:80]

    if req.new_password:
        if not req.current_password or not security.verify_password(
            req.current_password, user["password_hash"]
        ):
            raise HTTPException(status_code=403, detail="current password is incorrect")
        _check_password_shape(req.new_password)
        fields["password_hash"] = security.hash_password(req.new_password)

    updated = db.update_user(_settings(request), user["id"], fields) if fields else user
    return {"user": db.public_user(updated), "stats": db.user_summary(settings, user["id"])}
