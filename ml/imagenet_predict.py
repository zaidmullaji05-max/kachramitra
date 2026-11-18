"""ImageNet-pretrained classifier with taxonomy aggregation.

A normal ImageNet model returns one of 1,000 object classes. Several of those classes
belong to the same disposal item (`water bottle` + `pop bottle` -> plastic_bottle), so we
sum their probabilities per item before choosing. Classes that are not waste objects
(dogs, cars, buildings) stay unmapped and never become a confident disposal answer.

The returned shape matches `ml/predict.py::OnnxClassifier.predict` closely enough for
`ClassifierService` to enrich it with the taxonomy card.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

# Confusion guard: ImageNet calls an open laptop "notebook". If the same image also
# scores screen/monitor/computer/keyboard, treat it as e-waste instead of paper.
SCREEN_HINTS = {
    "screen", "monitor", "desktop computer", "computer keyboard", "laptop", "modem",
    "home theater", "television", "space bar",
}

MIN_KNOWN = 0.12  # below this, say "not sure" rather than force an item


class ImageNetClassifier:
    def __init__(self, model_path: str | Path, labels_path: str | Path, threads: int = 2):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.sess = ort.InferenceSession(str(model_path), sess_options=opts,
                                         providers=["CPUExecutionProvider"])
        self.input_name = self.sess.get_inputs()[0].name
        meta = json.loads(Path(labels_path).read_text(encoding="utf-8"))
        self.classes = meta["classes"]
        self.names = [c["name"] for c in self.classes]
        self.items = [c.get("item") for c in self.classes]
        self.size = int(meta.get("img_size", 224))
        self.resize = int(meta.get("resize_size", 256))
        self.mean = np.array(meta["mean"], dtype=np.float32).reshape(1, 3, 1, 1)
        self.std = np.array(meta["std"], dtype=np.float32).reshape(1, 3, 1, 1)
        self.arch = meta.get("arch", "imagenet")

    def preprocess(self, img: Image.Image) -> np.ndarray:
        img = img.convert("RGB")
        w, h = img.size
        scale = self.resize / min(w, h)
        img = img.resize((max(self.resize, round(w * scale)), max(self.resize, round(h * scale))),
                         Image.BICUBIC)
        w, h = img.size
        left, top = (w - self.size) // 2, (h - self.size) // 2
        img = img.crop((left, top, left + self.size, top + self.size))
        x = np.asarray(img, dtype=np.float32) / 255.0
        x = x.transpose(2, 0, 1)[None, ...]
        return ((x - self.mean) / self.std).astype(np.float32)

    def predict(self, img: Image.Image, top_k: int = 3, threshold: float = 0.60,
                margin: float = 0.15) -> dict:
        logits = self.sess.run(None, {self.input_name: self.preprocess(img)})[0][0]
        p = logits.astype(np.float64)
        p = np.exp(p - p.max())
        p /= p.sum()

        top_idx = np.argsort(-p)[:20]
        items = list(self.items)

        # laptop/notebook disambiguation
        if self.names[top_idx[0]] == "notebook":
            if any(self.names[j] in SCREEN_HINTS and p[j] >= 0.005 for j in top_idx):
                items[top_idx[0]] = "laptop"

        agg: dict[str, float] = {}
        for i, item in enumerate(items):
            if item:
                agg[item] = agg.get(item, 0.0) + float(p[i])

        order = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        best_p = order[0][1] if order else 0.0

        if not order or best_p < MIN_KNOWN:
            conf = round(min(0.35, max(best_p, 0.05)), 4)
            top = [{"id": "mixed_trash", "p": conf}]
            top += [{"id": item, "p": round(score, 4)} for item, score in order[:2]
                    if item != "mixed_trash"]
            return {"item": "mixed_trash", "confidence": conf, "top_k": top, "uncertain": True}

        item = order[0][0]
        confidence = float(order[0][1])
        second = float(order[1][1]) if len(order) > 1 else 0.0
        uncertain = confidence < threshold or (confidence - second) < margin

        top = [{"id": it, "p": round(score, 4)} for it, score in order]
        return {
            "item": item,
            "confidence": round(confidence, 4),
            "top_k": top,
            "uncertain": bool(uncertain),
        }
