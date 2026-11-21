"""Unit tests for the ImageNet -> waste-taxonomy aggregation.

These never touch ONNX Runtime: `_stub_classifier` builds an `ImageNetClassifier`
shell and replaces the session/preprocess steps, so the tests exercise only our own
aggregation and disambiguation logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ml"))

from ml.imagenet_predict import ImageNetClassifier  # noqa: E402
from tools.imagenet_map import item_for  # noqa: E402


class _StubSession:
    def __init__(self, logits: np.ndarray):
        self._logits = logits

    def run(self, _outputs, _feeds):
        return [self._logits[None, :]]


def _stub(names: list[str], items: list[str | None], logits: list[float]) -> ImageNetClassifier:
    clf = object.__new__(ImageNetClassifier)
    clf.names = names
    clf.items = items
    clf.input_name = "input"
    clf.preprocess = lambda img: np.zeros((1, 3, 4, 4), dtype=np.float32)  # type: ignore[assignment]
    clf.sess = _StubSession(np.asarray(logits, dtype=np.float32))
    return clf


def test_mapping_known_and_unknown():
    assert item_for(620, "laptop") == "laptop"
    assert item_for(440, "beer bottle") == "glass_container"
    assert item_for(0, "tench") is None, "a fish must not become a waste item"
    assert item_for(953, "pineapple") == "food_waste"


def test_aggregation_sums_classes_per_item():
    clf = _stub(
        names=["water bottle", "pop bottle", "golden retriever"],
        items=["plastic_bottle", "plastic_bottle", None],
        logits=[5.0, 4.0, 0.5],
    )
    out = clf.predict(Image.open(_blank()), top_k=3, threshold=0.45, margin=0.15)
    assert out["item"] == "plastic_bottle"
    assert out["confidence"] > 0.8
    assert out["uncertain"] is False


def test_notebook_with_screen_hints_becomes_laptop():
    clf = _stub(
        names=["notebook", "screen"],
        items=["paper", "monitor_tv"],
        logits=[5.0, 1.5],
    )
    out = clf.predict(Image.open(_blank()), top_k=3, threshold=0.45, margin=0.15)
    assert out["item"] == "laptop"
    assert out["top_k"][0]["id"] == "laptop"


def test_unmapped_object_is_uncertain_not_confident():
    clf = _stub(
        names=["golden retriever", "Labrador retriever"],
        items=[None, None],
        logits=[6.0, 5.0],
    )
    out = clf.predict(Image.open(_blank()), top_k=3, threshold=0.45, margin=0.15)
    assert out["item"] == "mixed_trash"
    assert out["uncertain"] is True
    assert out["confidence"] <= 0.35


def _blank() -> Path:
    """A real tiny JPEG so PIL can open it (contents are ignored by the stub)."""
    tmp = Path(__file__).with_name("_blank.jpg")
    if not tmp.exists():
        Image.new("RGB", (8, 8), (120, 120, 120)).save(tmp, format="JPEG")
    return tmp


@pytest.fixture(scope="session", autouse=True)
def _cleanup_blank():
    yield
    p = Path(__file__).with_name("_blank.jpg")
    if p.exists():
        p.unlink()
