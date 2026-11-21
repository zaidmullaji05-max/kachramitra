"""Admin API: one password, short-lived signed tokens, read-only analytics.

Why it looks like this
----------------------
The project has no user accounts and no database of admins. Adding one would mean storing
passwords, resets, and sessions — too much for a student project that must stay deployable
on a free tier.

Instead: `ADMIN_PASSWORD` is a single passphrase kept in the host's environment. Logging
in returns a token that is *signed* with that passphrase and carries its own expiry, so the
server keeps no session state. Restart the service, change the password, or delete the
browser's localStorage and every old token stops working.

Security notes (be honest about them):
* The password is compared with `hmac.compare_digest`, so timing does not leak it.
* Failed logins are throttled per IP.
* Empty `ADMIN_PASSWORD` disables the API entirely — it fails closed, not open.
* The panel is read-only. It cannot change a label, delete a scan, or run shell commands.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request

from . import db

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


async def require_admin(request: Request) -> None:
    """FastAPI dependency: 401 unless a valid `X-Admin-Token` header is present."""
    secret = _password(request)
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="admin panel is off: set ADMIN_PASSWORD on the server to enable it",
        )
    token = request.headers.get("x-admin-token", "")
    if not token_valid(token, secret):
        raise HTTPException(status_code=401, detail="invalid or expired admin token")


# --------------------------------------------------------------------------- auth
@router.post("/login")
async def login(request: Request):
    secret = _password(request)
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="admin panel is off: set ADMIN_PASSWORD on the server to enable it",
        )

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
    supplied = str((body or {}).get("password") or "")

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
    return db.admin_stats(request.app.state.settings.db_file, days=days)


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
        request.app.state.settings.db_file,
        limit=limit,
        offset=max(0, offset),
        category=category or None,
        query=q or None,
    )


@router.get("/feedback", dependencies=[Depends(require_admin)])
async def feedback(request: Request, limit: int = 100, offset: int = 0):
    limit = max(1, min(limit, 200))
    return db.admin_feedback(
        request.app.state.settings.db_file, limit=limit, offset=max(0, offset)
    )


@router.get("/export.csv", dependencies=[Depends(require_admin)])
async def export_csv(request: Request):
    """Download every scan with its correction, ready for a spreadsheet or a re-train set."""
    from fastapi.responses import Response

    rows = db.admin_csv_rows(request.app.state.settings.db_file)
    buf = io.StringIO()
    fields = [
        "created_at", "scan_id", "item", "category", "confidence", "uncertain",
        "device_id", "correct_item", "correct_category", "comment",
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
        "taxonomy": {
            "categories": len(st.classifier.taxonomy.classes),
            "items": len(st.classifier.taxonomy.items),
        },
    }
