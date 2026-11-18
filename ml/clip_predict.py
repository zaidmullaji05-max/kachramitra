"""Open-vocabulary waste screening with a MobileCLIP image encoder.

Why this exists
---------------
The shipped ImageNet model can only name the 1,000 classes it was trained on. A battery,
a phone charger, a CFL bulb, a chips packet or a syringe are not among them, so those
photos come back "not sure" exactly where the wrong bin is most dangerous.

MobileCLIP2-S0 was trained to put an image and a *sentence* in the same vector space.
`tools/build_clip_model.py` converts our 32 waste descriptions (plus "not waste"
descriptions such as `a photo of a dog`) into text embeddings once. At runtime this
module only needs ONNX Runtime + NumPy: the image is embedded, compared with those
sentences, and the best-matching waste item wins.

Runtime dependencies: numpy, onnxruntime, Pillow. No torch, no downloads.

What it returns
---------------
`predict()` returns the usual `{item, confidence, top_k, uncertain, source}` shape *plus*
`is_waste` and `negative_p`. `item` is still a taxonomy id, so the taxonomy card keeps
owning bin/steps/do_not — a vision model never invents disposal advice.

`fuse()` is the final decision step: it merges the ImageNet result and the CLIP result
into one answer, and refuses to answer when neither model found waste.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

# Fused score = w_imagenet * p_imagenet + w_clip * p_clip.
# CLIP gets the larger weight because it is scored against all 32 items (including the
# e-waste items ImageNet cannot express), while ImageNet only covers mapped classes.
W_IMAGENET = 0.4
W_CLIP = 0.6

# CLIP softmax temperature comes from the model (logit_scale ~= 64). A photo is only
# treated as "waste" when it beats the negative prompts by a real margin.
MIN_NEGATIVE_MARGIN = 0.10
MIN_WASTE_CONFIDENCE = 0.30

DEFAULT_FUSED_THRESHOLD = 0.45
DEFAULT_FUSED_MARGIN = 0.08

NOT_WASTE = "mixed_trash"


class CLIPClassifier:
    """Zero-shot waste screening on top of a pre-exported MobileCLIP visual encoder."""

    def __init__(self, model_path: str | Path, embeds_path: str | Path, threads: int = 2):
        import onnxruntime as ort

        self.model_path = str(model_path)
        self.embeds_path = str(embeds_path)

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.sess = ort.InferenceSession(
            self.model_path, sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self.input_name = self.sess.get_inputs()[0].name

        data = np.load(self.embeds_path, allow_pickle=False)
        embeds = np.asarray(data["embeds"], dtype=np.float32)
        self.embeds = embeds / np.linalg.norm(embeds, axis=1, keepdims=True)
        self.owners = [str(o) for o in data["owners"]]
        neg = np.asarray(data["neg_embeds"], dtype=np.float32)
        self.neg_embeds = neg / np.linalg.norm(neg, axis=1, keepdims=True)
        self.logit_scale = float(data["logit_scale"]) if "logit_scale" in data else 64.0

        meta_path = Path(self.embeds_path).with_name("clip_meta.json")
        meta = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.meta = meta
        self.size = int(meta.get("image_size", 256))
        self.resize = int(meta.get("resize_size", self.size))
        self.mean = np.array(meta.get("mean", [0.0, 0.0, 0.0]), dtype=np.float32).reshape(1, 3, 1, 1)
        self.std = np.array(meta.get("std", [1.0, 1.0, 1.0]), dtype=np.float32).reshape(1, 3, 1, 1)
        self.arch = meta.get("arch", "MobileCLIP2-S0")

        # Each item's best-matching prompt, so a single item can be described many ways.
        self.item_index: dict[str, list[int]] = {}
        for i, owner in enumerate(self.owners):
            self.item_index.setdefault(owner, []).append(i)

    # ------------------------------------------------------------------ image side
    def preprocess(self, img: Image.Image) -> np.ndarray:
        """Match the torchvision pipeline used when the model was exported exactly."""
        img = img.convert("RGB")
        w, h = img.size
        scale = self.resize / min(w, h)
        img = img.resize(
            (max(self.resize, round(w * scale)), max(self.resize, round(h * scale))),
            Image.BILINEAR,
        )
        w, h = img.size
        left, top = (w - self.size) // 2, (h - self.size) // 2
        img = img.crop((left, top, left + self.size, top + self.size))
        x = np.asarray(img, dtype=np.float32) / 255.0
        x = x.transpose(2, 0, 1)[None, ...]
        return ((x - self.mean) / self.std).astype(np.float32)

    def embed(self, img: Image.Image) -> np.ndarray:
        out = self.sess.run(None, {self.input_name: self.preprocess(img)})[0]
        v = np.asarray(out, dtype=np.float32).reshape(-1)
        n = float(np.linalg.norm(v))
        return v / n if n else v

    # ------------------------------------------------------------------ text side
    def item_scores(self, img_embed: np.ndarray) -> dict[str, float]:
        """Best cosine similarity per taxonomy item (max over that item's prompts)."""
        sims = self.embeds @ img_embed
        scores: dict[str, float] = {}
        for item, idxs in self.item_index.items():
            scores[item] = float(np.max(sims[idxs]))
        return scores

    def predict(self, img: Image.Image, top_k: int = 3) -> dict:
        feat = self.embed(img)
        scores = self.item_scores(feat)
        neg_p_raw = float(np.max(self.neg_embeds @ feat)) if len(self.neg_embeds) else -1.0

        items = list(scores)
        raw = np.array([scores[i] for i in items], dtype=np.float64)
        # Softmax over the per-item maxima, with the negative prompts as one more class.
        all_raw = np.concatenate([raw, [neg_p_raw]])
        z = self.logit_scale * all_raw
        z -= z.max()
        p = np.exp(z)
        p /= p.sum()

        probs = dict(zip(items, p[:-1].tolist()))
        negative_p = float(p[-1])
        ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
        best_item, best_p = ranked[0]
        second_p = ranked[1][1] if len(ranked) > 1 else 0.0

        is_waste = (
            best_p >= MIN_WASTE_CONFIDENCE
            and best_p - negative_p >= MIN_NEGATIVE_MARGIN
        )

        top = [{"id": item, "p": round(score, 4)} for item, score in ranked[:top_k]]
        if is_waste:
            item, confidence, uncertain = best_item, best_p, best_p < 0.5
        else:
            # Keep the guess in top_k so the UI can still show "it looked like X".
            item, confidence = NOT_WASTE, min(0.30, max(0.05, best_p))
            uncertain = True

        return {
            "item": item,
            "confidence": round(float(confidence), 4),
            "top_k": top,
            "uncertain": bool(uncertain),
            "is_waste": bool(is_waste),
            "negative_p": round(negative_p, 4),
            "second_p": round(float(second_p), 4),
            "arch": self.arch,
        }


# ---------------------------------------------------------------------- fusion
def _dist(top_k: list[dict]) -> dict[str, float]:
    """Normalise a model's top_k list into a probability-like distribution."""
    d: dict[str, float] = {}
    for entry in top_k or []:
        tid = entry.get("id") or entry.get("item")
        if not tid:
            continue
        d[str(tid)] = d.get(str(tid), 0.0) + max(float(entry.get("p") or 0.0), 0.0)
    total = sum(d.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in d.items()}


def fuse(
    imagenet: dict | None,
    clip: dict | None,
    *,
    threshold: float = DEFAULT_FUSED_THRESHOLD,
    margin: float = DEFAULT_FUSED_MARGIN,
) -> dict:
    """Merge the ImageNet and CLIP opinions into one `{item, confidence, top_k, uncertain, source}`.

    Three cases:

    1. CLIP says "not waste" (a dog, a room, a car) and ImageNet has no confident item
       -> answer `mixed_trash` with low confidence, so the app asks a follow-up question.
    2. ImageNet found nothing usable -> trust CLIP alone.
    3. Both have an opinion -> weighted average of the two distributions.

    Fusion is preferred over "if A then B" rules because it degrades gracefully: a very
    confident CLIP result can correct a wrong ImageNet label (ImageNet calls a soda can
    "pop bottle"; CLIP knows it is a metal can), while a very confident ImageNet result
    keeps its item when CLIP is unsure.
    """
    image_top = (imagenet or {}).get("top_k") or []
    image_item = (imagenet or {}).get("item") or NOT_WASTE
    image_ok = bool(imagenet) and image_item != NOT_WASTE and image_top
    clip_ok = bool(clip) and bool(clip.get("is_waste"))

    if not clip_ok and not image_ok:
        # Nothing recognised the photo. Say so instead of guessing a bin.
        guess = (clip or {}).get("top_k") or image_top
        conf = min(0.30, max(0.05, float((clip or {}).get("confidence") or 0.05)))
        top = [{"id": NOT_WASTE, "p": round(conf, 4)}]
        top += [g for g in guess[:2] if (g.get("id") or g.get("item")) != NOT_WASTE]
        return {
            "item": NOT_WASTE,
            "confidence": round(conf, 4),
            "top_k": top,
            "uncertain": True,
            "source": "none",
        }

    if not clip_ok:
        return {
            "item": image_item,
            "confidence": float(imagenet.get("confidence") or 0.0),
            "top_k": image_top,
            "uncertain": bool(imagenet.get("uncertain")),
            "source": "model",
        }

    if not image_ok:
        return {
            "item": clip["item"],
            "confidence": float(clip["confidence"]),
            "top_k": clip.get("top_k") or [],
            "uncertain": bool(clip.get("uncertain")),
            "source": "clip",
        }

    img_p = _dist(image_top)
    clip_p = _dist(clip.get("top_k") or [])
    fused: dict[str, float] = {}
    for tid in set(img_p) | set(clip_p):
        fused[tid] = W_IMAGENET * img_p.get(tid, 0.0) + W_CLIP * clip_p.get(tid, 0.0)

    ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
    best_item, best_p = ranked[0]
    second_p = ranked[1][1] if len(ranked) > 1 else 0.0
    uncertain = best_p < threshold or (best_p - second_p) < margin

    return {
        "item": best_item,
        "confidence": round(float(best_p), 4),
        "top_k": [{"id": tid, "p": round(p, 4)} for tid, p in ranked[:3]],
        "uncertain": bool(uncertain),
        "source": "model+clip",
    }
