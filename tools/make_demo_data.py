#!/usr/bin/env python
"""
Generate a tiny synthetic dataset so you can test the whole pipeline BEFORE the real
datasets finish downloading (and so CI has something to run against).

    python tools/make_demo_data.py                       # -> data/raw_demo/trashnet/<label>/*.jpg
    python tools/build_manifest.py --raw-dir data/raw_demo --out data/demo/manifest.csv
    python ml/train.py --manifest data/demo/manifest.csv --epochs 6 --out artifacts_demo

This is NOT training data for the real model. It exists to prove that the code runs.
"""
from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]

# source -> label -> (shape, base colour)
SPEC = {
    "trashnet": {
        "plastic": ("bottle", (40, 110, 220)),
        "glass": ("circle", (30, 160, 90)),
        "paper": ("page", (245, 243, 235)),
        "cardboard": ("box", (170, 120, 60)),
        "metal": ("can", (150, 155, 165)),
        "trash": ("blob", (90, 70, 80)),
    }
}


def draw_item(shape: str, colour, size: int, rng: random.Random) -> Image.Image:
    bg = rng.randint(90, 200)
    img = Image.new("RGB", (size, size), (bg, bg, bg))
    d = ImageDraw.Draw(img)
    cx, cy = size // 2 + rng.randint(-12, 12), size // 2 + rng.randint(-12, 12)
    w, h = rng.randint(size // 3, size // 2), rng.randint(size // 3, size // 2)
    shade = tuple(min(255, max(0, c + rng.randint(-35, 35))) for c in colour)

    if shape == "bottle":
        d.rounded_rectangle([cx - w // 3, cy - h // 2, cx + w // 3, cy + h // 2], radius=14, fill=shade)
        d.rectangle([cx - 8, cy - h // 2 - 16, cx + 8, cy - h // 2], fill=(60, 60, 70))
    elif shape == "circle":
        d.ellipse([cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2], fill=shade, outline=(255, 255, 255))
    elif shape == "page":
        d.rectangle([cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2], fill=shade)
        for k in range(4):
            y = cy - h // 2 + 18 + k * 16
            d.line([cx - w // 2 + 12, y, cx + w // 2 - 12, y], fill=(140, 140, 145), width=2)
    elif shape == "box":
        d.polygon([(cx, cy - h // 2), (cx + w // 2, cy - h // 4), (cx, cy), (cx - w // 2, cy - h // 4)], fill=shade)
        d.rectangle([cx - w // 2, cy - h // 4, cx + w // 2, cy + h // 2], fill=tuple(int(c * 0.85) for c in shade))
    elif shape == "can":
        d.rounded_rectangle([cx - w // 3, cy - h // 2, cx + w // 3, cy + h // 2], radius=8, fill=shade)
        d.ellipse([cx - w // 3, cy - h // 2 - 6, cx + w // 3, cy - h // 2 + 6], fill=(200, 200, 210))
    else:  # blob
        pts = [(cx + int(w * 0.6 * math.cos(a)), cy + int(h * 0.45 * math.sin(a * 1.7)))
               for a in np.linspace(0, 2 * math.pi, 12)]
        d.polygon(pts, fill=shade)

    # lighting + blur + JPEG-ish noise, so the task is not trivially separable
    arr = np.asarray(img).astype(np.int16)
    arr = arr + rng.randint(-18, 18)
    arr = np.clip(arr + np.random.normal(0, 6, arr.shape), 0, 255).astype(np.uint8)
    img = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(rng.uniform(0.0, 1.2)))
    return img.resize((rng.randint(200, 320), rng.randint(200, 320)), Image.BICUBIC)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "data" / "raw_demo"))
    ap.add_argument("--per-class", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    np.random.seed(args.seed)
    total = 0
    for source, labels in SPEC.items():
        for label, (shape, colour) in labels.items():
            d = Path(args.out) / source / label
            d.mkdir(parents=True, exist_ok=True)
            for i in range(args.per_class):
                img = draw_item(shape, colour, 256, rng)
                img.save(d / f"{label}_{i:03d}.jpg", quality=88)
                total += 1
    print(f"wrote {total} synthetic images to {args.out}")
    print("next: python tools/build_manifest.py --raw-dir data/raw_demo --out data/demo/manifest.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
