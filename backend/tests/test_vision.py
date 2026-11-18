"""Tests for the optional vision-LLM identification path.

No network calls: only JSON parsing, taxonomy id cleaning, provider resolution, and the
conversion from a vision result into a full taxonomy-backed API payload.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import vision  # noqa: E402
from app.classifier import ClassifierService  # noqa: E402
from app.config import Settings  # noqa: E402
from app.taxonomy import get_taxonomy  # noqa: E402


def _off() -> Settings:
    return Settings(gemini_api_key="", groq_api_key="", vision_provider="auto")


def _service(settings: Settings | None = None) -> ClassifierService:
    """A ClassifierService shell: enough for `from_vision`, no ONNX load."""
    svc = object.__new__(ClassifierService)
    svc.settings = settings or Settings()
    svc.taxonomy = get_taxonomy()
    svc.model = None
    svc.ready = False
    svc.reason = "not loaded in tests"
    svc.arch = ""
    return svc


def test_vision_off_without_keys():
    settings = _off()
    assert vision.enabled(settings) is False
    assert vision.status(settings) == {"enabled": False, "provider": None, "model": None}


def test_vision_resolves_gemini_then_groq():
    gem = Settings(gemini_api_key="g-key", groq_api_key="x-key", vision_provider="auto")
    assert vision.status(gem)["provider"] == "gemini"

    groq = Settings(gemini_api_key="", groq_api_key="x-key", vision_provider="auto")
    assert vision.status(groq)["provider"] == "groq"

    off = Settings(gemini_api_key="g-key", groq_api_key="x-key", vision_provider="off")
    assert vision.enabled(off) is False


@pytest.mark.parametrize(
    "text",
    [
        '{"item":"laptop","confidence":0.8}',
        'Here you go:\n```json\n{"item":"laptop","confidence":0.8}\n```',
        'The answer is {"item":"laptop","confidence":0.8} — done.',
    ],
)
def test_extract_json_tolerates_wrapping(text):
    obj = vision._extract_json(text)
    assert obj["item"] == "laptop"


def test_extract_json_rejects_garbage():
    with pytest.raises(vision.VisionError):
        vision._extract_json("")
    with pytest.raises(vision.VisionError):
        vision._extract_json("no json here")


def test_clean_id_accepts_ids_and_names():
    tax = get_taxonomy()
    assert vision._clean_id("laptop", tax) == "laptop"
    assert vision._clean_id("Plastic bottle", tax) == "plastic_bottle"
    assert vision._clean_id("definitely-not-a-class", tax) is None


def test_from_vision_builds_taxonomy_card():
    svc = _service()
    out = svc.from_vision(
        {"item": "laptop", "confidence": 0.82, "alternatives": ["monitor_tv"], "reason": "screen and keyboard"}
    )
    assert out["item"] == "laptop"
    assert out["category"] == "ewaste"
    assert out["source"] == "vision"
    assert out["uncertain"] is False
    assert out["disposal"]["bin"]
    assert out["disposal"]["steps"]
    assert out["top_k"][0]["item"] == "laptop"
    assert any(t["item"] == "monitor_tv" for t in out["top_k"])


def test_from_vision_unknown_item_falls_back_to_mixed_trash():
    svc = _service()
    out = svc.from_vision({"item": "spaceship", "confidence": 0.99})
    assert out["item"] == "mixed_trash"
    assert out["uncertain"] is True


def test_from_vision_text_hint_overrides_low_confidence():
    svc = _service()
    out = svc.from_vision(
        {"item": "mixed_trash", "confidence": 0.2},
        text_hint="an old laptop",
    )
    assert out["item"] == "laptop"
    assert out["source"] == "text_hint"
    assert out["uncertain"] is False
