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
