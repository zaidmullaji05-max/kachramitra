"""Admin API tests — no model, no keys, no network.

The admin router is mounted on a tiny standalone app here (rather than reusing
`app.main`) so these tests do not depend on which module imported Settings first.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def _reset_throttle():
    """The failed-login bucket is module level (per process), so isolate each test."""
    from app.admin import _failures

    _failures.clear()
    yield
    _failures.clear()


def _settings(db_path: Path, password: str = PASSWORD):
    from app.config import Settings

    return Settings(
        admin_password=password,
        db_path=str(db_path),
        llm_provider="fake",
        facility_provider="fixture",
        clip_enabled=False,
    )


@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient

    from app import db
    from app.admin import router
    from app.main import app as real_app  # noqa: F401 - ensures package imports cleanly

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    app.state.settings = _settings(tmp_path / "admin.db")
    db.init_db(app.state.settings.db_file)

    with TestClient(app) as c:
        yield c


def _seed(db_path: Path, n: int = 3) -> None:
    from app import db

    for i in range(n):
        db.insert_scan(db_path, {
            "id": f"scn_test{i}",
            "device_id": "dev_test",
            "item": "battery" if i == 0 else "plastic_bottle",
            "category": "ewaste" if i == 0 else "recyclable",
            "confidence": 0.5 + i / 10,
            "uncertain": 0,
            "lang": "en",
            "eco_points": 5,
            "image_url": None,
            "created_at": db.now_iso(),
        })
    db.insert_feedback(db_path, {
        "scan_id": "scn_test0",
        "correct_item": "charger_cable",
        "correct_category": "ewaste",
        "comment": "it was the cable",
        "created_at": db.now_iso(),
    })


# --------------------------------------------------------------------------- tokens
def test_token_roundtrip_and_expiry():
    from app.admin import issue_token, token_valid

    issued = issue_token(PASSWORD, ttl_s=60)
    assert token_valid(issued["token"], PASSWORD)
    assert not token_valid(issued["token"], "different-secret")
    assert not token_valid("", PASSWORD)
    assert not token_valid("not-a-token", PASSWORD)
    assert not token_valid("123.deadbeef", PASSWORD)

    expired = issue_token(PASSWORD, ttl_s=-5)
    assert not token_valid(expired["token"], PASSWORD)


def test_login_wrong_password(client):
    r = client.post("/admin/login", json={"password": "nope"})
    assert r.status_code == 401


def test_login_and_use_token(client):
    r = client.post("/admin/login", json={"password": PASSWORD})
    assert r.status_code == 200
    token = r.json()["token"]

    r = client.get("/admin/session", headers={"X-Admin-Token": token})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_admin_is_off_without_password(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.admin import router

    app = FastAPI()
    app.include_router(router)
    app.state.settings = _settings(tmp_path / "off.db", password="")

    with TestClient(app) as c:
        assert c.post("/admin/login", json={"password": ""}).status_code == 503
        assert c.get("/admin/stats", headers={"X-Admin-Token": "x"}).status_code == 503


def test_endpoints_require_token(client):
    for path in ("/admin/stats", "/admin/scans", "/admin/feedback", "/admin/export.csv", "/admin/model"):
        assert client.get(path).status_code == 401, path


def test_brute_force_is_throttled(client):
    for _ in range(8):
        assert client.post("/admin/login", json={"password": "wrong"}).status_code == 401
    r = client.post("/admin/login", json={"password": PASSWORD})
    assert r.status_code == 429


# --------------------------------------------------------------------------- data
@pytest.fixture()
def authed(client):
    token = client.post("/admin/login", json={"password": PASSWORD}).json()["token"]
    return client, {"X-Admin-Token": token}


def test_stats_shape(authed, tmp_path):
    client, headers = authed
    _seed(tmp_path / "admin.db")

    r = client.get("/admin/stats", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total_scans"] == 3
    assert body["today"] == 3
    assert body["feedback"]["total"] == 1
    assert body["feedback"]["corrections"] == 1
    assert len(body["trend"]) == 14
    cats = {c["category"] for c in body["by_category"]}
    assert {"ewaste", "recyclable"} <= cats
    assert body["top_items"][0]["count"] >= 1


def test_scans_filter_and_paging(authed, tmp_path):
    client, headers = authed
    _seed(tmp_path / "admin.db", n=5)

    body = client.get("/admin/scans?limit=2", headers=headers).json()
    assert body["total"] == 5 and len(body["scans"]) == 2

    only = client.get("/admin/scans?category=ewaste", headers=headers).json()
    assert only["total"] == 1
    assert only["scans"][0]["item"] == "battery"

    found = client.get("/admin/scans?q=bottle", headers=headers).json()
    assert found["total"] == 4


def test_feedback_joins_prediction(authed, tmp_path):
    client, headers = authed
    _seed(tmp_path / "admin.db")

    body = client.get("/admin/feedback", headers=headers).json()
    row = body["feedback"][0]
    assert row["predicted_item"] == "battery"
    assert row["correct_item"] == "charger_cable"
    assert row["agrees"] is False


def test_csv_export(authed, tmp_path):
    client, headers = authed
    _seed(tmp_path / "admin.db")

    r = client.get("/admin/export.csv", headers=headers)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]

    lines = r.text.strip().splitlines()
    assert lines[0].startswith("created_at,scan_id,item")
    assert len(lines) == 4  # header + 3 scans
    assert "charger_cable" in r.text


def test_stats_on_empty_db(authed):
    client, headers = authed
    body = client.get("/admin/stats", headers=headers).json()
    assert body["total_scans"] == 0
    assert body["uncertain_rate"] == 0.0
    assert body["by_category"] == []


def test_model_endpoint_reports_version_and_taxonomy(authed):
    from types import SimpleNamespace

    client, headers = authed
    client.app.state.classifier = SimpleNamespace(
        ready=True,
        reason="",
        arch="mobilenet_v3_large_imagenet",
        model_name="mobilenet.onnx",
        clip_status={"enabled": True, "model": "clip.onnx", "reason": None},
        taxonomy=SimpleNamespace(classes={"ewaste": {}, "general": {}}, items={"a": 1, "b": 2}),
    )
    r = client.get("/admin/model", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["version"]
    assert body["classifier"]["arch"] == "mobilenet_v3_large_imagenet"
    assert body["taxonomy"] == {"categories": 2, "items": 2}
