"""Admin API: passphrase or an admin user account, short-lived signed tokens.

Two ways in
-----------
* `ADMIN_PASSWORD` alone still signs a passphrase token. That path stays so a lab machine
  with no database of people can open the panel.
* An account with `is_admin` (seeded from `ADMIN_EMAIL` + `ADMIN_PASSWORD`, or promoted
  in the panel) signs in with email and password. The token is the same shape the app
  uses for ordinary users; every request re-loads the row and checks `is_admin`.

The panel can list, edit and remove users. Scans of a removed user stay, with the
account link cleared, so totals do not quietly shrink.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request

from . import db, security
from .schemas import AdminUserUpdate

router = APIRouter(prefix="/admin", tags=["admin"])

MAX_LOGIN_FAILURES = 8
FAILURE_WINDOW_S = 600
_failures: dict[str, deque[float]] = defaultdict(deque)


# --------------------------------------------------------------------------- tokens
def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_token(secret: str, ttl_s: int) -> dict:
    expires = int(time.time()) + ttl_s
    payload = str(expires)
    return {"token": f"{payload}.{_sign(payload, secret)}", "expires_at": expires}


def token_valid(token: str, secret: str) -> bool:
    if not token or "." not in token:
        return False
    payload, signature = token.split(".", 1)
    if not payload.isdigit():
        return False
    if not hmac.compare_digest(signature, _sign(payload, secret)):
        return False
    return int(payload) > time.time()


def _password(request: Request) -> str:
    return (request.app.state.settings.admin_password or "").strip()


def _admin_from_user_token(request: Request, token: str) -> dict | None:
    """An app login token is accepted here only when that account is an active admin."""
    if not token or token.count(".") != 2:
        return None
    settings = request.app.state.settings
    claims = security.read_user_token(token, settings.auth_secret_value)
    if not claims:
        return None
    user = db.get_user(settings, claims["user_id"])
    if not user or not user["is_active"] or not user["is_admin"]:
        return None
    return user


async def require_admin(request: Request) -> None:
    """FastAPI dependency: passphrase token or an active admin user's token."""
    token = request.headers.get("x-admin-token", "")
    secret = _password(request)
    if secret and token_valid(token, secret):
        return
    if _admin_from_user_token(request, token):
        return
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="admin panel is off: set ADMIN_PASSWORD on the server to enable it",
        )
    raise HTTPException(status_code=401, detail="invalid or expired admin token")


# --------------------------------------------------------------------------- auth
@router.post("/login")
async def login(request: Request):
    secret = _password(request)
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    q = _failures[ip]
    while q and now - q[0] > FAILURE_WINDOW_S:
        q.popleft()
    if len(q) >= MAX_LOGIN_FAILURES:
        raise HTTPException(status_code=429, detail="too many failed logins, wait 10 minutes")

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - a junk body is just a bad password
        body = {}
    body = body or {}
    supplied = str(body.get("password") or "")
    email = str(body.get("email") or "").strip().lower()

    # Email present → this is a user-account login, not the shared passphrase.
    if email:
        from .users import normalise_email

        user = db.get_user_by_email(request.app.state.settings, normalise_email(email))
        if not user or not security.verify_password(supplied, user["password_hash"]):
            q.append(now)
            raise HTTPException(status_code=401, detail="wrong email or password")
        if not user["is_active"]:
            raise HTTPException(status_code=403, detail="this account has been disabled")
        if not user["is_admin"]:
            raise HTTPException(status_code=403, detail="this account is not an admin")
        q.clear()
        db.touch_login(request.app.state.settings, user["id"], db.now_iso())
        ttl = int(request.app.state.settings.admin_token_ttl_hours) * 3600
        out = security.issue_user_token(request.app.state.settings.auth_secret_value, user["id"], ttl)
        out["ttl_s"] = ttl
        out["user"] = db.public_user(user)
        return out

    if not secret:
        raise HTTPException(
            status_code=503,
            detail="admin panel is off: set ADMIN_PASSWORD on the server to enable it",
        )
    if not hmac.compare_digest(supplied, secret):
        q.append(now)
        raise HTTPException(status_code=401, detail="wrong password")

    q.clear()
    ttl = int(request.app.state.settings.admin_token_ttl_hours) * 3600
    out = issue_token(secret, ttl)
    out["ttl_s"] = ttl
    return out


@router.get("/session", dependencies=[Depends(require_admin)])
async def session(request: Request):
    """Cheap check the panel calls on load to see whether a stored token still works."""
    return {"ok": True, "ttl_hours": request.app.state.settings.admin_token_ttl_hours}


# --------------------------------------------------------------------------- data
@router.get("/stats", dependencies=[Depends(require_admin)])
async def stats(request: Request, days: int = 14):
    days = max(1, min(days, 90))
    return db.admin_stats(request.app.state.settings, days=days)


@router.get("/scans", dependencies=[Depends(require_admin)])
async def scans(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    category: str | None = None,
    q: str | None = None,
):
    limit = max(1, min(limit, 200))
    return db.admin_scans(
        request.app.state.settings,
        limit=limit,
        offset=max(0, offset),
        category=category or None,
        query=q or None,
    )


@router.get("/feedback", dependencies=[Depends(require_admin)])
async def feedback(request: Request, limit: int = 100, offset: int = 0):
    limit = max(1, min(limit, 200))
    return db.admin_feedback(
        request.app.state.settings, limit=limit, offset=max(0, offset)
    )


@router.get("/users", dependencies=[Depends(require_admin)])
async def users(request: Request, limit: int = 50, offset: int = 0, q: str | None = None):
    limit = max(1, min(limit, 200))
    return db.admin_users(
        request.app.state.settings, limit=limit, offset=max(0, offset), query=q or None
    )


@router.patch("/users/{user_id}", dependencies=[Depends(require_admin)])
async def update_user(user_id: str, body: AdminUserUpdate, request: Request):
    settings = request.app.state.settings
    existing = db.get_user(settings, user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="user not found")
    fields: dict = {}
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name cannot be empty")
        fields["name"] = name[:80]
    if body.is_active is not None:
        fields["is_active"] = int(body.is_active)
    if body.is_admin is not None:
        fields["is_admin"] = int(body.is_admin)
    updated = db.update_user(settings, user_id, fields) if fields else existing
    return {"user": db.public_user(updated)}


@router.delete("/users/{user_id}", dependencies=[Depends(require_admin)])
async def remove_user(user_id: str, request: Request):
    settings = request.app.state.settings
    if not db.get_user(settings, user_id):
        raise HTTPException(status_code=404, detail="user not found")
    db.delete_user(settings, user_id)
    return {"ok": True}


@router.get("/export.csv", dependencies=[Depends(require_admin)])
async def export_csv(request: Request):
    """Download every scan with its correction, ready for a spreadsheet or a re-train set."""
    from fastapi.responses import Response

    rows = db.admin_csv_rows(request.app.state.settings)
    buf = io.StringIO()
    fields = [
        "created_at", "scan_id", "item", "category", "confidence", "uncertain",
        "device_id", "user_id", "user_email", "correct_item", "correct_category", "comment",
    ]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fields})

    stamp = time.strftime("%Y%m%d-%H%M")
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="kachra-mitra-scans-{stamp}.csv"'},
    )


@router.get("/model", dependencies=[Depends(require_admin)])
async def model_info(request: Request):
    """What the server is actually running — the first thing to check when scans look off."""
    st = request.app.state
    from . import VERSION, vision
    from .llm import get_provider

    return {
        "version": VERSION,
        "classifier": {
            "ready": st.classifier.ready,
            "reason": st.classifier.reason or None,
            "arch": st.classifier.arch or None,
            "model": st.classifier.model_name or None,
        },
        "clip": st.classifier.clip_status,
        "vision": vision.status(st.settings),
        "llm": getattr(get_provider(st.settings), "name", "rules"),
        "confidence_threshold": st.settings.confidence_threshold,
        "facilities_provider": st.settings.facility_provider,
        "image_storage": st.settings.image_storage_ready,
        "database": db.database_info(st.settings),
        "taxonomy": {
            "categories": len(st.classifier.taxonomy.classes),
            "items": len(st.classifier.taxonomy.items),
        },
    }
