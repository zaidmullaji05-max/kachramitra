"""SQLite storage: scan history, feedback, and the facility cache.

No images and no chat transcripts are stored by default — only the label the model
produced. That is a deliberate privacy decision (see docs/10) and it also keeps the DB
tiny. If the operator opts into Cloudinary (`IMAGE_STORAGE=true`), `scans.image_url`
holds the public URL of the sanitized photo; the bytes still never touch local disk.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id TEXT PRIMARY KEY,
    device_id TEXT,
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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        yield con
        con.commit()
    finally:
        con.close()


def init_db(db_path: Path) -> None:
    with connect(db_path) as con:
        con.executescript(SCHEMA)
        # idempotent migration for databases created before optional image storage
        columns = {r["name"] for r in con.execute("PRAGMA table_info(scans)")}
        if "image_url" not in columns:
            con.execute("ALTER TABLE scans ADD COLUMN image_url TEXT")


def insert_scan(db_path: Path, row: dict[str, Any]) -> None:
    row = {"image_url": None, **row}
    with connect(db_path) as con:
        con.execute(
            """INSERT OR REPLACE INTO scans
               (id, device_id, item, category, confidence, uncertain, lang, eco_points, image_url, created_at)
               VALUES (:id, :device_id, :item, :category, :confidence, :uncertain, :lang, :eco_points,
                       :image_url, :created_at)""",
            row,
        )


def list_scans(db_path: Path, device_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with connect(db_path) as con:
        rows = con.execute(
            """SELECT id, item, category, confidence, uncertain, eco_points, image_url, created_at
               FROM scans WHERE device_id = ? ORDER BY created_at DESC LIMIT ?""",
            (device_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def scan_summary(db_path: Path, device_id: str) -> dict[str, Any]:
    with connect(db_path) as con:
        total = con.execute("SELECT COUNT(*) FROM scans WHERE device_id = ?", (device_id,)).fetchone()[0]
        points = con.execute(
            "SELECT COALESCE(SUM(eco_points), 0) FROM scans WHERE device_id = ?", (device_id,)
        ).fetchone()[0]
        by_cat = con.execute(
            """SELECT category, COUNT(*) AS n FROM scans WHERE device_id = ?
               GROUP BY category ORDER BY n DESC""",
            (device_id,),
        ).fetchall()
    return {"total": total, "eco_points": points, "by_category": {r["category"]: r["n"] for r in by_cat}}


def insert_feedback(db_path: Path, row: dict[str, Any]) -> None:
    with connect(db_path) as con:
        con.execute(
            """INSERT INTO feedback (scan_id, correct_item, correct_category, comment, created_at)
               VALUES (:scan_id, :correct_item, :correct_category, :comment, :created_at)""",
            row,
        )


# --------------------------------------------------------------------------- admin
# Everything below is read-only reporting for the admin panel. No new tables: the panel
# is a lens over the scan log, not a second source of truth.


def admin_stats(db_path: Path, days: int = 14) -> dict[str, Any]:
    """Dashboard numbers: totals, today's activity, category mix, daily trend, top items."""
    with connect(db_path) as con:
        total = con.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
        today = con.execute(
            "SELECT COUNT(*) FROM scans WHERE created_at >= ?", (_day_start(0),)
        ).fetchone()[0]
        yesterday = con.execute(
            "SELECT COUNT(*) FROM scans WHERE created_at >= ? AND created_at < ?",
            (_day_start(1), _day_start(0)),
        ).fetchone()[0]
        uncertain = con.execute("SELECT COUNT(*) FROM scans WHERE uncertain = 1").fetchone()[0]
        devices = con.execute("SELECT COUNT(DISTINCT device_id) FROM scans").fetchone()[0]
        with_images = con.execute("SELECT COUNT(*) FROM scans WHERE image_url IS NOT NULL").fetchone()[0]
        avg_conf = con.execute("SELECT COALESCE(AVG(confidence), 0) FROM scans").fetchone()[0]

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
            trend.append({"day": day, "n": counts.get(day, 0)})

        fb_total = con.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        fb_fixes = con.execute(
            "SELECT COUNT(*) FROM feedback f JOIN scans s ON s.id = f.scan_id "
            "WHERE f.correct_item IS NOT NULL AND f.correct_item <> s.item"
        ).fetchone()[0]
        fb_recent = con.execute(
            """SELECT f.created_at, f.correct_item, f.correct_category, f.comment,
                      s.item AS predicted_item, s.category AS predicted_category
               FROM feedback f LEFT JOIN scans s ON s.id = f.scan_id
               ORDER BY f.created_at DESC LIMIT 5"""
        ).fetchall()

    return {
        "total_scans": total,
        "today": today,
        "yesterday": yesterday,
        "uncertain": uncertain,
        "uncertain_rate": round(uncertain / total, 4) if total else 0.0,
        "avg_confidence": round(float(avg_conf), 4),
        "devices": devices,
        "with_images": with_images,
        "by_category": [{"category": r["category"], "count": r["n"]} for r in by_cat],
        "top_items": [
            {
                "item": r["item"],
                "category": r["category"],
                "count": r["n"],
                "avg_confidence": round(float(r["avg_conf"] or 0), 4),
                "uncertain": r["uncertain"],
            }
            for r in top_items
        ],
        "trend": trend,
        "feedback": {
            "total": fb_total,
            "corrections": fb_fixes,
            "recent": [dict(r) for r in fb_recent],
        },
    }


def admin_scans(db_path: Path, limit: int = 50, offset: int = 0,
                category: str | None = None, query: str | None = None) -> dict[str, Any]:
    where: list[str] = []
    params: list[Any] = []
    if category:
        where.append("category = ?")
        params.append(category)
    if query:
        where.append("(item LIKE ? OR device_id LIKE ?)")
        params += [f"%{query}%", f"%{query}%"]
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    with connect(db_path) as con:
        total = con.execute(f"SELECT COUNT(*) FROM scans {clause}", params).fetchone()[0]
        rows = con.execute(
            f"""SELECT id, device_id, item, category, confidence, uncertain, eco_points,
                       image_url, created_at
                FROM scans {clause} ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
    return {"total": total, "limit": limit, "offset": offset, "scans": [dict(r) for r in rows]}


def admin_feedback(db_path: Path, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    with connect(db_path) as con:
        total = con.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
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
    return {"total": total, "limit": limit, "offset": offset, "feedback": out}


def admin_csv_rows(db_path: Path, limit: int = 5000) -> list[dict[str, Any]]:
    """Flat rows for the CSV export: prediction plus the correction, when there is one."""
    with connect(db_path) as con:
        rows = con.execute(
            """SELECT s.created_at, s.id AS scan_id, s.item, s.category, s.confidence,
                      s.uncertain, s.device_id,
                      f.correct_item, f.correct_category, f.comment
               FROM scans s LEFT JOIN feedback f ON f.scan_id = s.id
               ORDER BY s.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def _day_start(days_ago: int = 0) -> str:
    """UTC midnight `days_ago` days back, as an ISO string comparable to created_at."""
    from datetime import timedelta

    d = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return d.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


def cache_facilities(db_path: Path, facilities: list[dict[str, Any]], fetched_at: str) -> None:
    with connect(db_path) as con:
        con.executemany(
            """INSERT OR REPLACE INTO facilities
               (id, name, category, lat, lng, address, phone, hours, website, source, fetched_at)
               VALUES (:id, :name, :category, :lat, :lng, :address, :phone, :hours, :website, :source, :fetched_at)""",
            [{**f, "fetched_at": fetched_at} for f in facilities],
        )


def cached_facilities(db_path: Path, category: str, lat: float, lng: float, dlat: float, dlng: float,
                      max_age_days: int) -> list[dict[str, Any]]:
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat(timespec="seconds")
    with connect(db_path) as con:
        rows = con.execute(
            """SELECT * FROM facilities
               WHERE category = ? AND lat BETWEEN ? AND ? AND lng BETWEEN ? AND ? AND fetched_at >= ?""",
            (category, lat - dlat, lat + dlat, lng - dlng, lng + dlng, cutoff),
        ).fetchall()
    return [dict(r) for r in rows]
