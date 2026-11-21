"""Storage: SQLite by default, Neon PostgreSQL when `DATABASE_URL` is set.

Why both
--------
A student should be able to clone the repo, run it, and have history work with zero
accounts. That is SQLite. But a hosted demo needs accounts that survive a redeploy, and
Render's free disk is wiped on every restart — which is exactly what Neon's free Postgres
solves. So the same functions talk to either engine:

    db.list_scans(Path("backend/data/app.db"), "dev_123")        # SQLite
    db.list_scans(settings, "dev_123")                            # Settings -> DATABASE_URL

Anything that receives a `Path` is SQLite; anything that receives a `Settings` with a
non-empty `database_url` is Postgres. There is no global "current database", so tests can
use a temp SQLite file while the real app uses Neon in the same process.

The price of one API over two engines is three small adapters, all in this file:

* `?` placeholders are rewritten to `%s` for psycopg.
* `INSERT … ON CONFLICT` is used instead of the SQLite-only `INSERT OR REPLACE`.
* aggregate columns are always aliased (`COUNT(*) AS n`) because Postgres returns dicts.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator
from urllib.parse import urlparse

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a config import cycle
    from .config import Settings

Target = Path | str | "Settings"

# --------------------------------------------------------------------------- schemas
# Two schemas instead of one translated schema: the differences are 4 lines, and reading
# the real DDL is far clearer than debugging a generator.
SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS scans (
    id TEXT PRIMARY KEY,
    device_id TEXT,
    user_id TEXT,
    item TEXT NOT NULL,
    category TEXT NOT NULL,
    confidence REAL NOT NULL,
    uncertain INTEGER NOT NULL DEFAULT 0,
    lang TEXT DEFAULT 'en',
    eco_points INTEGER NOT NULL DEFAULT 0,
    image_url TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scans_device ON scans(device_id, created_at DESC);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id TEXT,
    correct_item TEXT,
    correct_category TEXT,
    comment TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facilities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    address TEXT,
    phone TEXT,
    hours TEXT,
    website TEXT,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facilities_cat ON facilities(category);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS scans (
    id TEXT PRIMARY KEY,
    device_id TEXT,
    user_id TEXT,
    item TEXT NOT NULL,
    category TEXT NOT NULL,
    confidence REAL NOT NULL,
    uncertain INTEGER NOT NULL DEFAULT 0,
    lang TEXT DEFAULT 'en',
    eco_points INTEGER NOT NULL DEFAULT 0,
    image_url TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scans_device ON scans(device_id, created_at DESC);

CREATE TABLE IF NOT EXISTS feedback (
    id BIGSERIAL PRIMARY KEY,
    scan_id TEXT,
    correct_item TEXT,
    correct_category TEXT,
    comment TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facilities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    address TEXT,
    phone TEXT,
    hours TEXT,
    website TEXT,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facilities_cat ON facilities(category);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- adapters
def _kind(target: Target) -> tuple[str, Any]:
    """Resolve a Path to SQLite and a Settings object to SQLite *or* Postgres."""
    if isinstance(target, (str, Path)):
        return "sqlite", Path(target)
    url = (getattr(target, "database_url", "") or "").strip()
    if url:
        # Neon and older Heroku both hand out postgres://, which psycopg also accepts,
        # but normalising it keeps error messages and tooling predictable.
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        return "postgres", url
    return "sqlite", target.db_file


class Conn:
    """The two-line compatibility layer: placeholders and scripts."""

    def __init__(self, con: Any, postgres: bool):
        self._con = con
        self.postgres = postgres

    def execute(self, sql: str, params: Any = ()):
        if self.postgres:
            sql = sql.replace("?", "%s")
        return self._con.execute(sql, params)

    def executemany(self, sql: str, seq: Any):
        if self.postgres:
            sql = sql.replace("?", "%s")
        return self._con.executemany(sql, seq)

    def executescript(self, script: str) -> None:
        if not self.postgres:
            self._con.executescript(script)
            return
        for statement in script.split(";"):
            if statement.strip():
                self._con.execute(statement)


_pools: dict[str, Any] = {}
_pool_lock = threading.Lock()


def _pool(url: str):
    """One thread-safe pool per connection string. Neon free wakes in well under a second."""
    with _pool_lock:
        pool = _pools.get(url)
        if pool is not None:
            return pool

        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(
            url,
            min_size=0,
            max_size=5,
            timeout=15,
            # Neon's pooled endpoint is PgBouncer in transaction mode; server-side
            # prepared statements do not survive that, so let psycopg send plain queries.
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
            open=False,
            name="kachra-mitra",
        )
        pool.open(wait=True, timeout=25)
        _pools[url] = pool
        return pool


def close_pools() -> None:
    """Called on shutdown so Render can recycle the process cleanly."""
    with _pool_lock:
        for pool in _pools.values():
            try:
                pool.close()
            except Exception:  # noqa: BLE001 - best effort during shutdown
                pass
        _pools.clear()


@contextmanager
def connect(target: Target) -> Iterator[Conn]:
    kind, value = _kind(target)
    if kind == "postgres":
        pool = _pool(value)
        with pool.connection() as con:  # commits on success, rolls back on error
            yield Conn(con, True)
        return

    value.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(value, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        yield Conn(con, False)
        con.commit()
    finally:
        con.close()


def init_db(target: Target) -> None:
    kind, value = _kind(target)
    with connect(target) as con:
        con.executescript(POSTGRES_SCHEMA if kind == "postgres" else SQLITE_SCHEMA)
        if kind == "postgres":
            # Idempotent migrations for databases created by an older version.
            con.execute("ALTER TABLE scans ADD COLUMN IF NOT EXISTS user_id TEXT")
            con.execute("ALTER TABLE scans ADD COLUMN IF NOT EXISTS image_url TEXT")
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_scans_user "
                "ON scans(user_id, created_at DESC)"
            )
        else:
            columns = {r["name"] for r in con.execute("PRAGMA table_info(scans)")}
            if "image_url" not in columns:
                con.execute("ALTER TABLE scans ADD COLUMN image_url TEXT")
            if "user_id" not in columns:
                con.execute("ALTER TABLE scans ADD COLUMN user_id TEXT")
            # Re-read: the ALTER above may have just added user_id.
            columns = {r["name"] for r in con.execute("PRAGMA table_info(scans)")}
            if "user_id" in columns:
                con.execute(
                    "CREATE INDEX IF NOT EXISTS idx_scans_user "
                    "ON scans(user_id, created_at DESC)"
                )


def database_info(target: Target) -> dict[str, Any]:
    """Safe description for /health and the admin panel — never the password."""
    kind, value = _kind(target)
    if kind == "sqlite":
        return {"backend": "sqlite", "location": str(value)}
    parsed = urlparse(value)
    return {
        "backend": "postgres",
        "host": parsed.hostname or "unknown",
        "database": (parsed.path or "/").lstrip("/") or "unknown",
        "pooled": "pooler" in (parsed.hostname or ""),
    }


# --------------------------------------------------------------------------- scans
def insert_scan(target: Target, row: dict[str, Any]) -> None:
    row = {"image_url": None, "user_id": None, **row}
    with connect(target) as con:
        con.execute(
            """INSERT INTO scans
               (id, device_id, user_id, item, category, confidence, uncertain, lang,
                eco_points, image_url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 device_id = excluded.device_id, user_id = excluded.user_id,
                 item = excluded.item, category = excluded.category,
                 confidence = excluded.confidence, uncertain = excluded.uncertain,
                 lang = excluded.lang, eco_points = excluded.eco_points,
                 image_url = excluded.image_url, created_at = excluded.created_at""",
            (row["id"], row.get("device_id"), row.get("user_id"), row["item"], row["category"],
             row["confidence"], int(row["uncertain"]), row.get("lang") or "en",
             int(row.get("eco_points") or 0), row.get("image_url"), row["created_at"]),
        )


def _owner_clause(device_id: str | None, user_id: str | None) -> tuple[str, tuple[Any, ...]]:
    if user_id:
        return "user_id = ?", (user_id,)
    return "device_id = ?", (device_id or "anonymous",)


def list_scans(target: Target, device_id: str | None, limit: int = 50,
               user_id: str | None = None) -> list[dict[str, Any]]:
    clause, params = _owner_clause(device_id, user_id)
    with connect(target) as con:
        rows = con.execute(
            f"""SELECT id, item, category, confidence, uncertain, eco_points, image_url, created_at
                FROM scans WHERE {clause} ORDER BY created_at DESC LIMIT ?""",
            (*params, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def scan_summary(target: Target, device_id: str | None,
                 user_id: str | None = None) -> dict[str, Any]:
    clause, params = _owner_clause(device_id, user_id)
    with connect(target) as con:
        total = con.execute(f"SELECT COUNT(*) AS n FROM scans WHERE {clause}", params).fetchone()["n"]
        points = con.execute(
            f"SELECT COALESCE(SUM(eco_points), 0) AS n FROM scans WHERE {clause}", params
        ).fetchone()["n"]
        by_cat = con.execute(
            f"""SELECT category, COUNT(*) AS n FROM scans WHERE {clause}
                GROUP BY category ORDER BY n DESC""",
            params,
        ).fetchall()
    return {"total": int(total), "eco_points": int(points or 0),
            "by_category": {r["category"]: int(r["n"]) for r in by_cat}}


def delete_scan(target: Target, scan_id: str) -> bool:
    """Remove one scan and any corrections attached to it."""
    with connect(target) as con:
        con.execute("DELETE FROM feedback WHERE scan_id = ?", (scan_id,))
        cur = con.execute("DELETE FROM scans WHERE id = ?", (scan_id,))
        return bool(cur.rowcount)


def claim_scans(target: Target, device_id: str, user_id: str) -> None:
    """Attach this browser's guest scans to the account that just signed in."""
    if not device_id or device_id == "anonymous" or not user_id:
        return
    with connect(target) as con:
        con.execute(
            """UPDATE scans SET user_id = ?
               WHERE device_id = ? AND (user_id IS NULL OR user_id = '')""",
            (user_id, device_id),
        )


def insert_feedback(target: Target, row: dict[str, Any]) -> None:
    with connect(target) as con:
        con.execute(
            """INSERT INTO feedback (scan_id, correct_item, correct_category, comment, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (row.get("scan_id"), row.get("correct_item"), row.get("correct_category"),
             row.get("comment"), row["created_at"]),
        )


# --------------------------------------------------------------------------- users
USER_FIELDS = ("email", "name", "password_hash", "is_active", "is_admin", "last_login_at")


def public_user(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip the password hash. Every API response goes through this."""
    if not row:
        return None
    user = dict(row)
    user.pop("password_hash", None)
    user["is_active"] = bool(user.get("is_active"))
    user["is_admin"] = bool(user.get("is_admin"))
    return user


def create_user(target: Target, row: dict[str, Any]) -> None:
    with connect(target) as con:
        con.execute(
            """INSERT INTO users
               (id, email, name, password_hash, is_active, is_admin, created_at, last_login_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (row["id"], row["email"], row.get("name"), row["password_hash"],
             int(row.get("is_active", 1)), int(row.get("is_admin", 0)),
             row["created_at"], row.get("last_login_at")),
        )


def get_user_by_email(target: Target, email: str) -> dict[str, Any] | None:
    with connect(target) as con:
        row = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def get_user(target: Target, user_id: str) -> dict[str, Any] | None:
    with connect(target) as con:
        row = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def touch_login(target: Target, user_id: str, when: str) -> None:
    with connect(target) as con:
        con.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (when, user_id))


def update_user(target: Target, user_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    keys = [k for k in fields if k in USER_FIELDS]
    if not keys:
        return get_user(target, user_id)
    clause = ", ".join(f"{k} = ?" for k in keys)
    with connect(target) as con:
        con.execute(f"UPDATE users SET {clause} WHERE id = ?",
                    (*(fields[k] for k in keys), user_id))
    return get_user(target, user_id)


def delete_user(target: Target, user_id: str) -> bool:
    """Remove the account. Scans stay, anonymised, so totals and CSV exports stay honest."""
    with connect(target) as con:
        con.execute("UPDATE scans SET user_id = NULL WHERE user_id = ?", (user_id,))
        cur = con.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return bool(cur.rowcount)


def user_summary(target: Target, user_id: str) -> dict[str, Any]:
    with connect(target) as con:
        total = con.execute("SELECT COUNT(*) AS n FROM scans WHERE user_id = ?", (user_id,)).fetchone()["n"]
        points = con.execute(
            "SELECT COALESCE(SUM(eco_points), 0) AS n FROM scans WHERE user_id = ?", (user_id,)
        ).fetchone()["n"]
        by_cat = con.execute(
            """SELECT category, COUNT(*) AS n FROM scans WHERE user_id = ?
               GROUP BY category ORDER BY n DESC""",
            (user_id,),
        ).fetchall()
    return {"total": int(total), "eco_points": int(points or 0),
            "by_category": {r["category"]: int(r["n"]) for r in by_cat}}


def admin_users(target: Target, limit: int = 50, offset: int = 0,
                query: str | None = None) -> dict[str, Any]:
    where, params = "", []
    if query:
        where = "WHERE (u.email LIKE ? OR u.name LIKE ?)"
        params = [f"%{query}%", f"%{query}%"]
    with connect(target) as con:
        total = con.execute(
            f"SELECT COUNT(*) AS n FROM users u {where}", params
        ).fetchone()["n"]
        rows = con.execute(
            f"""SELECT u.id, u.email, u.name, u.is_active, u.is_admin, u.created_at,
                       u.last_login_at,
                       (SELECT COUNT(*) FROM scans s WHERE s.user_id = u.id) AS scans,
                       (SELECT COALESCE(SUM(s.eco_points), 0) FROM scans s WHERE s.user_id = u.id) AS points
                FROM users u {where}
                ORDER BY u.created_at DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
    out = []
    for r in rows:
        row = public_user(dict(r))
        row["scans"] = int(r["scans"] or 0)
        row["points"] = int(r["points"] or 0)
        out.append(row)
    return {"total": int(total), "limit": limit, "offset": offset, "users": out}


# --------------------------------------------------------------------------- admin
# Read-only reporting for the admin panel, plus the user-management writes above.

def admin_stats(target: Target, days: int = 14) -> dict[str, Any]:
    """Dashboard numbers: totals, today's activity, category mix, daily trend, top items."""
    with connect(target) as con:
        total = con.execute("SELECT COUNT(*) AS n FROM scans").fetchone()["n"]
        today = con.execute(
            "SELECT COUNT(*) AS n FROM scans WHERE created_at >= ?", (_day_start(0),)
        ).fetchone()["n"]
        yesterday = con.execute(
            "SELECT COUNT(*) AS n FROM scans WHERE created_at >= ? AND created_at < ?",
            (_day_start(1), _day_start(0)),
        ).fetchone()["n"]
        uncertain = con.execute("SELECT COUNT(*) AS n FROM scans WHERE uncertain = 1").fetchone()["n"]
        devices = con.execute("SELECT COUNT(DISTINCT device_id) AS n FROM scans").fetchone()["n"]
        signed_in = con.execute("SELECT COUNT(*) AS n FROM scans WHERE user_id IS NOT NULL").fetchone()["n"]
        with_images = con.execute("SELECT COUNT(*) AS n FROM scans WHERE image_url IS NOT NULL").fetchone()["n"]
        avg_conf = con.execute("SELECT COALESCE(AVG(confidence), 0) AS n FROM scans").fetchone()["n"]

        users_total = con.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        users_today = con.execute(
            "SELECT COUNT(*) AS n FROM users WHERE created_at >= ?", (_day_start(0),)
        ).fetchone()["n"]
        users_active = con.execute("SELECT COUNT(*) AS n FROM users WHERE is_active = 1").fetchone()["n"]
        admins = con.execute("SELECT COUNT(*) AS n FROM users WHERE is_admin = 1").fetchone()["n"]
        users_7d = con.execute(
            """SELECT COUNT(DISTINCT user_id) AS n FROM scans
               WHERE user_id IS NOT NULL AND created_at >= ?""",
            (_day_start(7),),
        ).fetchone()["n"]

        by_cat = con.execute(
            "SELECT category, COUNT(*) AS n FROM scans GROUP BY category ORDER BY n DESC"
        ).fetchall()
        top_items = con.execute(
            """SELECT item, category, COUNT(*) AS n, AVG(confidence) AS avg_conf,
                      SUM(uncertain) AS uncertain
               FROM scans GROUP BY item ORDER BY n DESC LIMIT 8"""
        ).fetchall()

        # Daily trend, oldest first, with zero-filled gaps so the chart never lies.
        rows = con.execute(
            """SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n
               FROM scans WHERE created_at >= ? GROUP BY day""",
            (_day_start(days - 1),),
        ).fetchall()
        counts = {r["day"]: r["n"] for r in rows}
        trend = []
        for i in range(days - 1, -1, -1):
            day = _day_start(i)[:10]
            trend.append({"day": day, "n": int(counts.get(day, 0))})

        fb_total = con.execute("SELECT COUNT(*) AS n FROM feedback").fetchone()["n"]
        fb_fixes = con.execute(
            "SELECT COUNT(*) AS n FROM feedback f JOIN scans s ON s.id = f.scan_id "
            "WHERE f.correct_item IS NOT NULL AND f.correct_item <> s.item"
        ).fetchone()["n"]
        fb_recent = con.execute(
            """SELECT f.created_at, f.correct_item, f.correct_category, f.comment,
                      s.item AS predicted_item, s.category AS predicted_category
               FROM feedback f LEFT JOIN scans s ON s.id = f.scan_id
               ORDER BY f.created_at DESC LIMIT 5"""
        ).fetchall()

    return {
        "total_scans": int(total),
        "today": int(today),
        "yesterday": int(yesterday),
        "uncertain": int(uncertain),
        "uncertain_rate": round(uncertain / total, 4) if total else 0.0,
        "avg_confidence": round(float(avg_conf), 4),
        "devices": int(devices),
        "with_images": int(with_images),
        "signed_in_scans": int(signed_in),
        "guest_scans": int(total) - int(signed_in),
        "users": {
            "total": int(users_total),
            "today": int(users_today),
            "active": int(users_active),
            "admins": int(admins),
            "active_7d": int(users_7d),
        },
        "by_category": [{"category": r["category"], "count": int(r["n"])} for r in by_cat],
        "top_items": [
            {
                "item": r["item"],
                "category": r["category"],
                "count": int(r["n"]),
                "avg_confidence": round(float(r["avg_conf"] or 0), 4),
                "uncertain": int(r["uncertain"] or 0),
            }
            for r in top_items
        ],
        "trend": trend,
        "feedback": {
            "total": int(fb_total),
            "corrections": int(fb_fixes),
            "recent": [dict(r) for r in fb_recent],
        },
    }


def admin_scans(target: Target, limit: int = 50, offset: int = 0,
                category: str | None = None, query: str | None = None) -> dict[str, Any]:
    where: list[str] = []
    params: list[Any] = []
    if category:
        where.append("s.category = ?")
        params.append(category)
    if query:
        where.append("(s.item LIKE ? OR s.device_id LIKE ? OR u.email LIKE ?)")
        params += [f"%{query}%", f"%{query}%", f"%{query}%"]
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    with connect(target) as con:
        total = con.execute(
            f"SELECT COUNT(*) AS n FROM scans s LEFT JOIN users u ON u.id = s.user_id {clause}",
            params,
        ).fetchone()["n"]
        rows = con.execute(
            f"""SELECT s.id, s.device_id, s.user_id, s.item, s.category, s.confidence,
                       s.uncertain, s.lang, s.eco_points, s.image_url, s.created_at,
                       u.email AS user_email, u.name AS user_name
                FROM scans s LEFT JOIN users u ON u.id = s.user_id
                {clause} ORDER BY s.created_at DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
    return {"total": int(total), "limit": limit, "offset": offset,
            "scans": [dict(r) for r in rows]}


def admin_feedback(target: Target, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    with connect(target) as con:
        total = con.execute("SELECT COUNT(*) AS n FROM feedback").fetchone()["n"]
        rows = con.execute(
            """SELECT f.id, f.created_at, f.scan_id, f.correct_item, f.correct_category,
                      f.comment, s.item AS predicted_item, s.category AS predicted_category,
                      s.confidence, s.uncertain
               FROM feedback f LEFT JOIN scans s ON s.id = f.scan_id
               ORDER BY f.created_at DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
    out = []
    for r in rows:
        row = dict(r)
        row["agrees"] = bool(
            row["predicted_item"] and row["correct_item"] == row["predicted_item"]
        )
        out.append(row)
    return {"total": int(total), "limit": limit, "offset": offset, "feedback": out}


def admin_csv_rows(target: Target, limit: int = 5000) -> list[dict[str, Any]]:
    """Flat rows for the CSV export: prediction plus the correction, when there is one."""
    with connect(target) as con:
        rows = con.execute(
            """SELECT s.created_at, s.id AS scan_id, s.item, s.category, s.confidence,
                      s.uncertain, s.device_id, s.user_id, u.email AS user_email,
                      f.correct_item, f.correct_category, f.comment
               FROM scans s
               LEFT JOIN users u ON u.id = s.user_id
               LEFT JOIN feedback f ON f.scan_id = s.id
               ORDER BY s.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def _day_start(days_ago: int = 0) -> str:
    """UTC midnight `days_ago` days back, as an ISO string comparable to created_at."""
    d = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return d.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- facilities
def cache_facilities(target: Target, facilities: list[dict[str, Any]], fetched_at: str) -> None:
    with connect(target) as con:
        con.executemany(
            """INSERT INTO facilities
               (id, name, category, lat, lng, address, phone, hours, website, source, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 name = excluded.name, category = excluded.category,
                 lat = excluded.lat, lng = excluded.lng, address = excluded.address,
                 phone = excluded.phone, hours = excluded.hours, website = excluded.website,
                 source = excluded.source, fetched_at = excluded.fetched_at""",
            [(f["id"], f["name"], f["category"], float(f["lat"]), float(f["lng"]),
              f.get("address"), f.get("phone"), f.get("hours"), f.get("website"),
              f.get("source") or "osm", fetched_at) for f in facilities],
        )


def cached_facilities(target: Target, category: str, lat: float, lng: float,
                      dlat: float, dlng: float, max_age_days: int) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat(timespec="seconds")
    with connect(target) as con:
        rows = con.execute(
            """SELECT * FROM facilities
               WHERE category = ? AND lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?
                 AND fetched_at >= ?""",
            (category, lat - dlat, lat + dlat, lng - dlng, lng + dlng, cutoff),
        ).fetchall()
    return [dict(r) for r in rows]
