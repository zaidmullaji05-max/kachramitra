"""
API tests — these run with NO API keys and NO trained model.

    cd backend
    python -m pytest tests -q

What they cover:
  * the app boots and /health reports honest capability flags
  * /taxonomy serves all six categories
  * /facilities returns sorted, distance-annotated sample data
  * /classify rejects junk input with 400 (and returns 503, not a crash, without a model)
  * /chat answers from rule cards and injects hazard warnings for batteries
  * /history + /feedback round-trip through SQLite
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

# configure BEFORE importing the app (Settings is cached)
os.environ.update(
    LLM_PROVIDER="fake",
    FACILITY_PROVIDER="fixture",
    DB_PATH=str(ROOT / "backend" / "data" / "test_api.db"),
    RATE_LIMIT_PER_MIN="1000",
    ALLOW_ORIGINS="*",
)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    for p in (ROOT / "backend" / "data" / "test_api.db",):
        if p.exists():
            p.unlink()
    from app.main import app

    with TestClient(app) as c:
        yield c


def jpeg_bytes(colour=(90, 140, 200), size=(320, 320)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="JPEG")
    return buf.getvalue()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "classifier" in body and "ready" in body["classifier"]
    assert body["llm"] in ("rules", "groq", "gemini", "fake")


def test_taxonomy(client):
    r = client.get("/taxonomy")
    assert r.status_code == 200
    cats = {c["id"] for c in r.json()}
    assert {"ewaste", "recyclable", "general", "organic", "hazardous", "biomedical"} <= cats


def test_facilities_fixture(client):
    r = client.get("/facilities", params={"lat": 19.11, "lng": 72.84, "category": "ewaste"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "fixture"
    assert body["results"], "fixture data should never be empty"
    distances = [f["distance_m"] for f in body["results"]]
    assert distances == sorted(distances)
    assert all(f["category"] == "ewaste" for f in body["results"])


def test_facilities_bad_category(client):
    r = client.get("/facilities", params={"lat": 19.11, "lng": 72.84, "category": "nuclear"})
    assert r.status_code == 400


def test_classify_rejects_non_image(client):
    r = client.post("/classify", files={"file": ("x.jpg", b"not an image", "image/jpeg")})
    assert r.status_code == 400


def test_classify_path(client):
    r = client.get("/health")
    ready = r.json()["classifier"]["ready"]
    files = {"file": ("x.jpg", jpeg_bytes(), "image/jpeg")}
    resp = client.post("/classify", files=files, data={"lang": "en"})
    if not ready:
        assert resp.status_code == 503
        assert "classifier unavailable" in resp.json()["detail"]
        return
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scan_id"].startswith("scn_")
    assert body["category"] in {"ewaste", "recyclable", "general", "organic", "hazardous", "biomedical"}
    assert 0.0 <= body["confidence"] <= 1.0
    assert isinstance(body["disposal"]["steps"], list)
    # history now has this scan
    h = client.get("/history", params={"device_id": "anonymous"})
    assert h.status_code == 200
    assert h.json()["total"] >= 1


def test_chat_rule_fallback_with_hazard(client):
    r = client.post(
        "/chat",
        json={
            "message": "मेरी बैटरी फूल गई है, क्या करूँ?",
            "lang": "hi",
            "context": {"item": "battery", "category": "ewaste"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["answer"].strip()
    assert body["warnings"], "battery context must produce a safety warning"
    assert any(w["level"] == "danger" for w in body["warnings"])
    assert "rules" in body["tool_trace"]


def test_chat_hindi_without_context(client):
    """Demo mode (no LLM key) must still answer Hindi questions from the rule cards."""
    r = client.post("/chat", json={"message": "ट्यूबलाइट फूट गई है, क्या करूँ?", "lang": "hi"})
    assert r.status_code == 200
    body = r.json()
    assert "बल्ब" in body["answer"] or "ट्यूबलाइट" in body["answer"]
    assert body["warnings"], "a broken tube light must trigger the mercury warning"


def test_chat_refusal(client):
    r = client.post("/chat", json={"message": "prescribe me antibiotics", "lang": "en"})
    assert r.status_code == 200
    assert r.json()["tool_trace"] == ["refused"]


def test_knowledge_retrieval():
    from app.knowledge import get_knowledge

    kb = get_knowledge()
    assert kb.stats()["docs"] >= 6
    hits = kb.search("swollen battery what should I do")
    assert hits, "battery safety passage must be retrievable"
    assert "Battery" in hits[0][0].title
    hits = kb.search("which bin for vegetable peels")
    assert any("bin" in c.section.lower() or "bin" in c.text.lower() for c, _ in hits)


def test_chat_with_image_fake_mode(client):
    """No LLM key: the agent must still run the classifier tool and answer from the card."""
    import base64

    r = client.get("/health")
    if not r.json()["classifier"]["ready"]:
        pytest.skip("no model exported in this environment")
    payload = base64.b64encode(jpeg_bytes()).decode()
    resp = client.post("/chat", json={"message": "What is this and where do I put it?",
                                      "lang": "en", "image_base64": payload})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"].strip()
    assert any(t.startswith("classify_image") for t in body["tool_trace"])
    assert body["session_id"].startswith("ses_")


def test_feedback(client):
    r = client.post("/feedback", json={"scan_id": "scn_test", "correct_item": "battery",
                                       "correct_category": "ewaste", "comment": "call me on 9876543210"})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_validation(client):
    assert client.post("/chat", json={"message": "", "lang": "en"}).status_code == 422
    # unsupported language is rejected by the schema (Literal) before the handler runs
    assert client.post("/chat", json={"message": "hi", "lang": "fr"}).status_code == 422
