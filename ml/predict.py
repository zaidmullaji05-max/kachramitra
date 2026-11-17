#!/usr/bin/env python
"""
Single-image inference with the exported ONNX model. Also the reference implementation
for the FastAPI classifier service (step 4 imports `OnnxClassifier` from here).

    python ml/predict.py --image path/to/photo.jpg
    python ml/predict.py --image photo.jpg --json
    python ml/predict.py --image photo.jpg --lang hi
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]

# Windows consoles default to cp1252, which cannot print Devanagari names.
try:
    if (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass


class OnnxClassifier:
    """Loads artifacts/waste_model*.onnx + labels.json and does confidence-gated prediction."""

    def __init__(self, model_path: str | Path, labels_path: str | Path, threads: int = 2,
                 calibration_path: str | Path | None = None):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.sess = ort.InferenceSession(str(model_path), sess_options=opts, providers=["CPUExecutionProvider"])
        self.input_name = self.sess.get_inputs()[0].name
        meta = json.loads(Path(labels_path).read_text(encoding="utf-8"))
        self.classes = meta["classes"]
        self.size = int(meta["img_size"])
        self.mean = np.array(meta["mean"], dtype=np.float32).reshape(1, 3, 1, 1)
        self.std = np.array(meta["std"], dtype=np.float32).reshape(1, 3, 1, 1)

        # optional temperature from ml/calibrate.py (sits next to the model by default)
        self.temperature = 1.0
        cal = Path(calibration_path) if calibration_path else Path(model_path).with_name("calibration.json")
        if cal.exists():
            try:
                self.temperature = float(json.loads(cal.read_text(encoding="utf-8"))["temperature"])
            except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                self.temperature = 1.0

    def preprocess(self, img: Image.Image) -> np.ndarray:
        img = img.convert("RGB")
        # resize shorter side then centre-crop, matching the val transform
        w, h = img.size
        s = int(self.size * 1.14)
        scale = s / min(w, h)
        img = img.resize((max(s, int(round(w * scale))), max(s, int(round(h * scale)))), Image.BICUBIC)
        w, h = img.size
        left, top = (w - self.size) // 2, (h - self.size) // 2
        img = img.crop((left, top, left + self.size, top + self.size))
        x = np.asarray(img, dtype=np.float32) / 255.0
        x = x.transpose(2, 0, 1)[None, ...]
        return ((x - self.mean) / self.std).astype(np.float32)

    def predict(self, img: Image.Image, top_k: int = 3, threshold: float = 0.60, margin: float = 0.15) -> dict:
        logits = self.sess.run(None, {self.input_name: self.preprocess(img)})[0][0]
        logits = logits.astype(np.float64) / max(self.temperature, 1e-3)
        p = np.exp(logits - logits.max())
        p /= p.sum()
        order = np.argsort(-p)[:top_k]
        top = [{"id": self.classes[i]["id"], "name": self.classes[i]["name"],
                "category": self.classes[i]["category"], "p": float(p[i])} for i in order]
        best = self.classes[int(order[0])]
        confidence = float(p[order[0]])
        second = float(p[order[1]]) if len(order) > 1 else 0.0
        uncertain = confidence < threshold or (confidence - second) < margin

        follow_up = None
        if uncertain:
            if len(order) > 1:
                follow_up = f"Is it {top[0]['name']} or {top[1]['name']}?"
            else:
                follow_up = "Could you retake the photo in better light, closer to the item?"

        return {
            "item": best["id"],
            "item_display": best["name"],
            "category": best["category"],
            "category_display": best.get("category_name", best["category"]),
            "confidence": round(confidence, 4),
            "top_k": [{**t, "p": round(t["p"], 4)} for t in top],
            "uncertain": uncertain,
            "flags": best.get("flags", []),
            "disposal": {"bin": best.get("bin", ""), "steps": best.get("steps", []),
                         "do_not": best.get("do_not", []),
                         "rule_refs": [r.get("title") if isinstance(r, dict) else r
                                       for r in best.get("rule_refs", [])]},
            "follow_up": follow_up,
        }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True)
    ap.add_argument("--model", default=str(ROOT / "artifacts" / "waste_model_int8.onnx"))
    ap.add_argument("--labels", default=str(ROOT / "artifacts" / "labels.json"))
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--threshold", type=float, default=0.60)
    ap.add_argument("--lang", default="en", choices=["en", "hi", "mr"])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not Path(args.model).exists():
        print(f"missing {args.model} — run ml/export_onnx.py first")
        return 2
    clf = OnnxClassifier(args.model, args.labels)
    with Image.open(args.image) as im:
        result = clf.predict(im, top_k=args.top_k, threshold=args.threshold)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    names = {"en": "name", "hi": "name_hi", "mr": "name_mr"}
    meta = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    loc = {c["id"]: c for c in meta["classes"]}
    item = loc.get(result["item"], {})
    title = item.get(names[args.lang]) or result["item_display"]

    print(f"\n  {title}  ({result['category_display']})  confidence {result['confidence']:.0%}")
    if result["uncertain"]:
        print(f"  !! low confidence — {result['follow_up']}")
    if result["flags"]:
        print(f"  !! flags: {', '.join(result['flags'])}")
    print(f"\n  bin: {result['disposal']['bin']}")
    for s in result["disposal"]["steps"]:
        print(f"   - {s}")
    if result["disposal"]["do_not"]:
        print("  avoid:")
        for s in result["disposal"]["do_not"]:
            print(f"   x {s}")
    print("\n  top-3:", ", ".join(f"{t['name']} {t['p']:.2%}" for t in result["top_k"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
