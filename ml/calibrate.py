#!/usr/bin/env python
"""
Temperature scaling: make the confidence numbers honest.

Why this exists
---------------
Two things broke in practice: label smoothing + class weights make the model UNDER-confident
(a 26% top-1 on a correct prediction), and heavy models are often OVER-confident. Either way
the 0.60 gate in the API misbehaves: it abstains on everything, or on nothing.

Temperature scaling fits ONE number T on the validation split so that softmax(logits / T)
matches reality. It cannot change which class wins — only the confidence — so accuracy is
untouched while ECE and the risk-coverage curve improve a lot.

    python ml/calibrate.py --ckpt artifacts/model_best.pt --split val

Writes artifacts/calibration.json, which ml/predict.py picks up automatically.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train import build_model  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class Split(Dataset):
    def __init__(self, rows, label_to_idx, tf):
        self.rows, self.label_to_idx, self.tf = rows, label_to_idx, tf

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        with Image.open(ROOT / r["path"]) as im:
            x = self.tf(im.convert("RGB"))
        return x, self.label_to_idx[r["_label"]]


def ece(probs: np.ndarray, labels: np.ndarray, n_bins: int = 15) -> float:
    conf, pred = probs.max(1), probs.argmax(1)
    correct = (pred == labels).astype(np.float64)
    edges = np.linspace(0, 1, n_bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            total += m.mean() * abs(correct[m].mean() - conf[m].mean())
    return float(total)


def softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(1, keepdims=True)


def nll(logits: np.ndarray, labels: np.ndarray, t: float) -> float:
    p = softmax(logits / t)
    return float(-np.log(np.clip(p[np.arange(len(labels)), labels], 1e-12, None)).mean())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ckpt", default=str(ROOT / "artifacts" / "model_best.pt"))
    ap.add_argument("--manifest", default=str(ROOT / "data" / "manifest.csv"))
    ap.add_argument("--split", default="val", choices=["train", "val", "test", "wild"])
    ap.add_argument("--threshold", type=float, default=0.60)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--out", default=str(ROOT / "artifacts"))
    args = ap.parse_args()

    ck = torch.load(args.ckpt, map_location="cpu", weights_only=False)
    classes, level = ck["class_names"], ck.get("level", "item")
    key = "item" if level == "item" else "category"
    label_to_idx = {c: i for i, c in enumerate(classes)}
    size = ck.get("img_size", 224)
    mean, std = ck.get("mean", (0.485, 0.456, 0.406)), ck.get("std", (0.229, 0.224, 0.225))

    rows = []
    with Path(args.manifest).open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["split"] == args.split and r[key] in label_to_idx:
                r["_label"] = r[key]
                rows.append(r)
    if len(rows) < 20:
        print(f"only {len(rows)} rows in split '{args.split}' — need at least 20 to fit a temperature")
        return 2

    tf = transforms.Compose([transforms.Resize(int(size * 1.14)), transforms.CenterCrop(size),
                             transforms.ToTensor(), transforms.Normalize(mean, std)])
    dl = DataLoader(Split(rows, label_to_idx, tf), batch_size=args.batch, num_workers=0)

    model, _, _, _ = build_model(ck["arch"], len(classes), pretrained=False)
    model.load_state_dict(ck["model_state"])
    model.eval()

    logits, labels = [], []
    with torch.no_grad():
        for x, y in dl:
            logits.append(model(x).numpy())
            labels.append(y.numpy())
    logits, labels = np.concatenate(logits), np.concatenate(labels)

    # grid search is enough for one parameter and has no scipy dependency
    grid = np.arange(0.05, 6.01, 0.01)
    losses = [nll(logits, labels, t) for t in grid]
    best_t = float(grid[int(np.argmin(losses))])
    if best_t <= grid[1] or best_t >= grid[-1]:
        print(f"NOTE: temperature {best_t:.2f} is at the edge of the search grid — "
              "the model may be badly calibrated or the val split too small.")

    p0, p1 = softmax(logits), softmax(logits / best_t)
    acc0, acc1 = float((p0.argmax(1) == labels).mean()), float((p1.argmax(1) == labels).mean())

    def coverage(p):
        conf = p.max(1)
        return float((conf >= args.threshold).mean())

    print(f"split '{args.split}': {len(rows)} images")
    print(f"temperature  : {best_t:.2f}")
    print(f"accuracy     : {acc0:.4f} -> {acc1:.4f}   (must be identical; only confidence changes)")
    print(f"ECE          : {ece(p0, labels):.4f} -> {ece(p1, labels):.4f}")
    print(f"coverage@{args.threshold:.2f}: {coverage(p0):.3f} -> {coverage(p1):.3f}")

    if abs(acc0 - acc1) > 1e-9:
        print("WARNING: accuracy changed — temperature scaling should be accuracy-preserving. Not writing.")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "temperature": round(best_t, 3),
        "fitted_on": args.split,
        "n": len(rows),
        "ece_before": round(ece(p0, labels), 4),
        "ece_after": round(ece(p1, labels), 4),
        "coverage_before": round(coverage(p0), 4),
        "coverage_after": round(coverage(p1), 4),
    }
    (out / "calibration.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {out / 'calibration.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
