"""Unit tests for the CLIP zero-shot head and the ImageNet+CLIP fusion.

No ONNX Runtime and no torch: the classifier is built with `object.__new__` and given
synthetic embeddings, so these tests only cover our own maths.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ml"))

from ml.clip_predict import CLIPClassifier, fuse  # noqa: E402
from tools.clip_prompts import build_prompts, negative_prompts, names_for_item  # noqa: E402
from tools.taxonomy import load_taxonomy  # noqa: E402

TAX = load_taxonomy(ROOT / "data" / "label_map.yaml")


def _vec(seed: int, dim: int = 512) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _clip(item_vectors: dict[str, list[np.ndarray]], neg_vectors: list[np.ndarray],
          scale: float = 64.0) -> CLIPClassifier:
    clf = object.__new__(CLIPClassifier)
    embeds, owners = [], []
    for item, vecs in item_vectors.items():
        for v in vecs:
            embeds.append(v)
            owners.append(item)
    clf.embeds = np.stack(embeds)
    clf.owners = owners
    clf.neg_embeds = np.stack(neg_vectors) if neg_vectors else np.zeros((0, 512), dtype=np.float32)
    clf.logit_scale = scale
    clf.arch = "test"
    clf.item_index = {}
    for i, owner in enumerate(owners):
        clf.item_index.setdefault(owner, []).append(i)
    return clf


# ------------------------------------------------------------------ prompt builder
def test_every_taxonomy_item_has_prompts():
    prompts, owners = build_prompts(TAX)
    assert len(prompts) == len(owners)
    assert set(owners) == set(TAX.items), "every item needs at least one description"
    assert len(prompts) > 500


def test_prompts_are_english_ascii():
    prompts, _ = build_prompts(TAX)
    assert all(p.isascii() for p in prompts), "MobileCLIP text encoder is English-only"


def test_names_are_deduplicated():
    item = TAX.items["plastic_bottle"]
    names = names_for_item(item)
    assert len({n.lower() for n in names}) == len(names)
    assert any("bottle" in n.lower() for n in names)


def test_negative_prompts_exist_for_animals_and_scenes():
    negs = " ".join(negative_prompts())
    assert "dog" in negs and "person" in negs and "car" in negs


# ------------------------------------------------------------------ zero-shot predict
def test_predict_matches_best_item():
    battery = _vec(1)
    clf = _clip(
        {"battery": [battery, _vec(2)], "textile": [_vec(3)]},
        [_vec(9)],
    )
    clf.embed = lambda img: battery  # type: ignore[assignment]
    out = clf.predict(None)
    assert out["item"] == "battery"
    assert out["is_waste"] is True
    assert out["confidence"] > 0.5
    assert out["top_k"][0]["id"] == "battery"


def test_predict_rejects_non_waste_photo():
    dog = _vec(9)
    clf = _clip({"plastic_bottle": [_vec(1)], "textile": [_vec(3)]}, [dog])
    clf.embed = lambda img: dog  # type: ignore[assignment]
    out = clf.predict(None)
    assert out["is_waste"] is False
    assert out["item"] == "mixed_trash"
    assert out["uncertain"] is True
    assert out["negative_p"] > 0.5


def test_embedding_is_normalised():
    clf = _clip({"battery": [_vec(1)]}, [_vec(9)])
    clf.embed = lambda img: _vec(4)  # type: ignore[assignment]
    assert abs(float(np.linalg.norm(clf.embed(None))) - 1.0) < 1e-5


# ------------------------------------------------------------------ fusion
def _imagenet(item: str, p: float, alts: list[tuple[str, float]], uncertain: bool = False) -> dict:
    return {
        "item": item,
        "confidence": p,
        "top_k": [{"id": item, "p": p}] + [{"id": i, "p": a} for i, a in alts],
        "uncertain": uncertain,
    }


def _clipout(item: str, p: float, negative_p: float = 0.01, is_waste: bool = True,
             alts: list[tuple[str, float]] | None = None) -> dict:
    return {
        "item": item if is_waste else "mixed_trash",
        "confidence": p,
        "top_k": [{"id": item, "p": p}] + [{"id": i, "p": a} for i, a in (alts or [])],
        "uncertain": not is_waste,
        "is_waste": is_waste,
        "negative_p": negative_p,
    }


def test_confident_clip_corrects_wrong_imagenet():
    # ImageNet calls a soda can "pop bottle"; CLIP knows it is a metal can.
    img = _imagenet("plastic_bottle", 0.67,
                    [("paint_chemical", 0.12), ("medicine", 0.08)])
    clp = _clipout("metal_can", 0.90, alts=[("plastic_bottle", 0.08)])
    out = fuse(img, clp)
    assert out["item"] == "metal_can"
    assert out["source"] == "model+clip"
    assert out["uncertain"] is False


def test_agreement_keeps_imagenet_item_and_raises_confidence():
    img = _imagenet("food_waste", 0.95, [("mixed_trash", 0.02)])
    clp = _clipout("food_waste", 0.99)
    out = fuse(img, clp)
    assert out["item"] == "food_waste"
    assert out["confidence"] > 0.9


def test_clip_not_waste_and_image_unsure_means_no_answer():
    img = _imagenet("mixed_trash", 0.05, [], uncertain=True)
    clp = _clipout("plastic_bottle", 0.2, negative_p=0.93, is_waste=False)
    out = fuse(img, clp)
    assert out["item"] == "mixed_trash"
    assert out["uncertain"] is True
    assert out["confidence"] <= 0.30


def test_confident_imagenet_survives_when_clip_says_not_waste():
    img = _imagenet("laptop", 0.71, [("monitor_tv", 0.1)])
    clp = _clipout("mixed_trash", 0.1, negative_p=0.6, is_waste=False)
    out = fuse(img, clp)
    assert out["item"] == "laptop"
    assert out["source"] == "model"


def test_clip_alone_used_when_imagenet_has_no_item():
    img = _imagenet("mixed_trash", 0.05, [], uncertain=True)
    clp = _clipout("battery", 0.82)
    out = fuse(img, clp)
    assert out["item"] == "battery"
    assert out["source"] == "clip"


def test_fusion_without_clip_is_passthrough():
    img = _imagenet("paper", 0.8, [("cardboard", 0.1)])
    out = fuse(img, None)
    assert out["item"] == "paper"
    assert out["source"] == "model"


def test_low_margin_is_marked_uncertain():
    # Both models split evenly between the same two items: no bin can be recommended.
    img = _imagenet("paper", 0.40, [("cardboard", 0.40)])
    clp = _clipout("cardboard", 0.42, alts=[("paper", 0.42)])
    out = fuse(img, clp)
    assert out["item"] in {"paper", "cardboard"}
    assert out["uncertain"] is True


def test_one_supporter_does_not_cap_confidence_at_the_weights():
    # CLIP is certain, ImageNet names something else. Averaging the two distributions
    # used to report ~0.55 for a correct answer; that looked like "we are guessing".
    img = _imagenet("plastic_bottle", 0.67, [("paint_chemical", 0.12), ("medicine", 0.08)])
    clp = _clipout("metal_can", 0.90, alts=[("plastic_bottle", 0.08)])
    out = fuse(img, clp)
    assert out["item"] == "metal_can"
    assert out["confidence"] > 0.75
    assert out["uncertain"] is False


def test_agreement_uses_the_more_certain_model():
    img = _imagenet("laptop", 0.62, [("monitor_tv", 0.10)])
    clp = _clipout("laptop", 0.88, alts=[("monitor_tv", 0.04)])
    out = fuse(img, clp)
    assert out["item"] == "laptop"
    assert out["confidence"] >= 0.88


def test_full_distribution_is_used_instead_of_top_three():
    # The item that wins is outside the truncated top_k lists, but present in `probs`.
    img = _imagenet("battery", 0.34, [("charger_cable", 0.31)])
    img["probs"] = {"battery": 0.34, "charger_cable": 0.31, "metal_scrap": 0.35}
    clp = _clipout("battery", 0.55, alts=[("plastic_bottle", 0.05)])
    clp["probs"] = {"battery": 0.55, "plastic_bottle": 0.05, "charger_cable": 0.4}
    out = fuse(img, clp)
    assert out["item"] == "battery"
    assert out["top_k"][0]["id"] == "battery"
