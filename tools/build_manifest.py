#!/usr/bin/env python
"""
Build data/manifest.csv from data/raw/, using data/label_map.yaml as the source of truth.

Pipeline: ingest -> map labels -> clean -> dedupe (phash) -> split (grouped, stratified) -> report

Expected layout (folder-per-class, works for TrashNet / garbage12 / RealWaste / your own photos):

    data/raw/trashnet/glass/glass1.jpg
    data/raw/trashnet/paper/paper1.jpg
    data/raw/local_2026_03/plastic_bottle/img_001.jpg

Optional COCO-JSON layout (TACO, Roboflow COCO export):

    data/raw/taco/annotations.json + data/raw/taco/images/*.jpg
    -> pass:  --coco taco=data/raw/taco/annotations.json --coco-images taco=data/raw/taco/images

Usage
-----
    python tools/build_manifest.py                          # build data/manifest.csv
    python tools/build_manifest.py --dry-run                # only check labels, no image decoding
    python tools/build_manifest.py --wild-sources taco:0.3  # 30% of TACO -> untouched "wild" split
    python tools/build_manifest.py --coco taco=data/raw/taco/annotations.json \
                                   --coco-images taco=data/raw/taco/images

Unknown source labels are a hard error (never silently become "general").
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.taxonomy import load_taxonomy  # noqa: E402

Image.MAX_IMAGE_PIXELS = 200_000_000  # silence the decompression-bomb warning

ROOT = Path(__file__).resolve().parents[1]
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
SPLITS = ("train", "val", "test")


# ----------------------------------------------------------------------------- helpers
def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


POPCOUNT = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)


def phash(img: Image.Image, hash_size: int = 8, highfreq: int = 4) -> str:
    """
    64-bit perceptual hash (DCT-based), implemented with numpy only — no imagehash/scipy.
    Identical in spirit to imagehash.phash: resize to 32x32 grey, 2-D DCT-II,
    keep the top-left 8x8 low frequencies, threshold at the median -> 64 bits.
    """
    size = hash_size * highfreq
    small = img.convert("L").resize((size, size), Image.LANCZOS)
    a = np.asarray(small, dtype=np.float64)

    n = np.arange(size)
    k = np.arange(size)[:, None]
    dct_m = np.cos(np.pi * (2 * n[None, :] + 1) * k / (2 * size)) * np.sqrt(2.0 / size)
    dct_m[0, :] /= np.sqrt(2.0)          # orthonormal DCT-II
    coeffs = dct_m @ a @ dct_m.T

    low = coeffs[:hash_size, :hash_size]
    med = np.median(low.flatten())        # median including DC, like imagehash
    bits = (low.flatten() > med).astype(np.uint8)
    value = 0
    for b in bits:
        value = (value << 1) | int(b)
    return format(value, "016x")


def hamming_to_all(kept: np.ndarray, h: np.uint64) -> np.ndarray:
    """Hamming distance between one 64-bit hash and an array of hashes."""
    x = np.bitwise_xor(kept, h)
    return POPCOUNT[x.view(np.uint8).reshape(-1, 8)].sum(axis=1)


# ----------------------------------------------------------------------------- taxonomy
# Item / load_taxonomy now live in tools/taxonomy.py so the API and the trainer agree.


# ----------------------------------------------------------------------------- discovery
def iter_folder_source(src_dir: Path):
    """Yield (image_path, label) using the first directory level under src_dir as label."""
    for sub in sorted(p for p in src_dir.iterdir() if p.is_dir()):
        label = sub.name
        for f in sorted(sub.rglob("*")):
            if f.suffix.lower() in IMG_EXT:
                yield f, label
    for f in sorted(src_dir.glob("*")):
        if f.suffix.lower() in IMG_EXT:
            yield f, "__unlabeled__"


def iter_coco_source(json_path: Path, image_dir: Path):
    """Yield (image_path, label). Label = category of the largest annotation in the image."""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    cats = {c["id"]: c["name"] for c in data.get("categories", [])}
    files = {im["id"]: im["file_name"] for im in data.get("images", [])}
    best: dict[int, tuple[float, str]] = {}
    for a in data.get("annotations", []):
        cat = cats.get(a.get("category_id"), "unknown")
        area = float(a.get("area") or 0.0)
        if area == 0.0 and "bbox" in a:
            w, h = a["bbox"][2], a["bbox"][3]
            area = float(w) * float(h)
        img_id = a["image_id"]
        if img_id not in best or area > best[img_id][0]:
            best[img_id] = (area, cat)
    for img_id, fname in files.items():
        if img_id in best:
            yield image_dir / fname, best[img_id][1]


# ----------------------------------------------------------------------------- dedupe
def dedupe_groups(hashes: list[int], max_dist: int = 5) -> tuple[list[int], int]:
    """
    Returns (group_per_image, n_duplicates_dropped).
    group_per_image[i] is the representative index of i's near-duplicate cluster.
    Images that are duplicates of an earlier image are flagged (group != own index).
    """
    n = len(hashes)
    if n == 0:
        return [], 0
    kept = np.empty(n, dtype=np.uint64)  # preallocated to avoid O(n^2) copies
    kept_idx: list[int] = []
    group = [-1] * n
    dropped = 0
    size = 0
    for i, h in enumerate(hashes):
        if size > 0:
            best_j, best_d = -1, 999
            for start in range(0, size, 4096):
                dists = hamming_to_all(kept[start : start + 4096], np.uint64(h))
                j = int(dists.argmin())
                if int(dists[j]) < best_d:
                    best_d, best_j = int(dists[j]), start + j
                if best_d == 0:
                    break
            if best_d <= max_dist and best_j >= 0:
                group[i] = group[kept_idx[best_j]]  # representative of that cluster
                dropped += 1
                continue
        kept[size] = np.uint64(h)
        kept_idx.append(i)
        size += 1
        group[i] = i
    return group, dropped


# ----------------------------------------------------------------------------- rows
@dataclass
class Row:
    path: str
    source: str
    original_label: str
    item: str
    category: str
    flags: str
    sha256: str
    phash: str
    group: int = 0
    split: str = ""


# ----------------------------------------------------------------------------- split
def assign_splits(rows: list[Row], seed: int, ratios=(0.70, 0.15, 0.15)) -> None:
    """Stratify by item; keep every phash cluster inside one split."""
    rng = random.Random(seed)
    by_item: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_item[r.item].append(r)

    for item, item_rows in by_item.items():
        clusters: dict[int, list[Row]] = defaultdict(list)
        for r in item_rows:
            clusters[r.group].append(r)
        keys = list(clusters)
        rng.shuffle(keys)
        keys.sort(key=lambda k: -len(clusters[k]))  # big clusters first
        total = len(item_rows)
        target = {s: total * rt for s, rt in zip(SPLITS, ratios)}
        filled = {s: 0 for s in SPLITS}
        for k in keys:
            split = max(SPLITS, key=lambda s: (target[s] - filled[s]) / max(target[s], 1e-9))
            for r in clusters[k]:
                r.split = split
            filled[split] += len(clusters[k])

    # Never leave an item with zero val/test rows (when it has enough clusters).
    for item, item_rows in by_item.items():
        for need in ("test", "val"):
            if any(r.split == need for r in item_rows):
                continue
            donors = [r for r in item_rows if r.split == "train"]
            if len(donors) > 1:
                donors[0].split = need


def hold_out_wild(rows: list[Row], wild_spec: dict[str, float], seed: int) -> list[Row]:
    """Mark a fraction (by cluster) of the given sources as the untouched 'wild' split."""
    rng = random.Random(seed + 1)
    pool = [r for r in rows if r.source not in wild_spec]
    for src, frac in wild_spec.items():
        src_rows = [r for r in rows if r.source == src]
        if not src_rows:
            print(f"  ! --wild-sources: no rows for source '{src}'")
            continue
        clusters: dict[int, list[Row]] = defaultdict(list)
        for r in src_rows:
            clusters[r.group].append(r)
        keys = list(clusters)
        rng.shuffle(keys)
        goal, taken = int(len(src_rows) * frac), 0
        for k in keys:
            if taken >= goal:
                pool.extend(clusters[k])
                continue
            for r in clusters[k]:
                r.split = "wild"
            taken += len(clusters[k])
    return pool


# ----------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", default=str(ROOT / "data" / "raw"))
    ap.add_argument("--label-map", default=str(ROOT / "data" / "label_map.yaml"))
    ap.add_argument("--out", default=str(ROOT / "data" / "manifest.csv"))
    ap.add_argument("--min-side", type=int, default=200)
    ap.add_argument("--dup-distance", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true", help="label check only; no decoding/hashing")
    ap.add_argument("--skip-unknown", action="store_true", help="drop unmapped images instead of failing")
    ap.add_argument("--wild-sources", default="", help="e.g. taco:0.3,local_wild:1.0")
    ap.add_argument("--coco", action="append", default=[], help="source=path/to/annotations.json")
    ap.add_argument("--coco-images", action="append", default=[], help="source=path/to/images")
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    tax = load_taxonomy(Path(args.label_map))
    items = tax.items
    if not raw_dir.exists():
        print(f"ERROR: {raw_dir} does not exist. Create it and drop datasets in.")
        return 2

    coco: dict[str, tuple[Path, Path]] = {}
    for spec in args.coco:
        src, _, p = spec.partition("=")
        coco[src] = (Path(p), raw_dir / src)
    for spec in args.coco_images:
        src, _, p = spec.partition("=")
        if src in coco:
            coco[src] = (coco[src][0], Path(p))

    wild_spec = {}
    for spec in args.wild_sources.split(","):
        if spec.strip():
            src, _, frac = spec.partition(":")
            wild_spec[src.strip()] = float(frac or 1.0)

    # ---- 1+2. ingest and map
    rows: list[Row] = []
    unknown: Counter = Counter()

    for source_dir in sorted(p for p in raw_dir.iterdir() if p.is_dir()):
        source = source_dir.name
        if source not in tax.sources:
            print(f"  ! source '{source}' has no entry under 'sources:' in label_map.yaml -> skipped")
            continue
        pairs = (
            list(iter_coco_source(*coco[source]))
            if source in coco
            else list(iter_folder_source(source_dir))
        )
        print(f"  {source}: {len(pairs)} candidate images")
        for path, label in pairs:
            item_id = tax.resolve(source, label)
            if item_id is None:
                unknown[f"{source}/{label}"] += 1
                continue
            it = items[item_id]
            rows.append(
                Row(
                    path=str(path),
                    source=source,
                    original_label=label,
                    item=it.id,
                    category=it.category,
                    flags="|".join(it.flags),
                    sha256="",
                    phash="",
                )
            )

    if unknown:
        print(f"\nERROR: {len(unknown)} source label(s) not in label_map.yaml:")
        for k, v in unknown.most_common(40):
            print(f"   {k}  ({v} images)")
        if not args.skip_unknown:
            print("\nAdd them under sources: in data/label_map.yaml, or re-run with --skip-unknown.")
            return 3
        print("  -> --skip-unknown set: dropping them.")

    if not rows:
        print("No usable images found.")
        return 4

    if args.dry_run:
        print(f"\nDry run OK: {len(rows)} images map cleanly to {len({r.item for r in rows})} items.")
        for item, n in Counter(r.item for r in rows).most_common():
            print(f"   {item:22s} {n:5d}  [{items[item].category}]")
        return 0

    # ---- 3. clean (decode + size) and hash
    print("\nDecoding, hashing, deduping ...")
    kept: list[Row] = []
    bad = 0
    for i, r in enumerate(rows):
        try:
            with Image.open(r.path) as im:
                im = im.convert("RGB")
                if min(im.size) < args.min_side:
                    bad += 1
                    continue
                r.phash = phash(im)
            r.sha256 = sha256_of(Path(r.path))
        except Exception as e:  # noqa: BLE001 - any decode failure means "skip this file"
            print(f"   skip {r.path}: {e}")
            bad += 1
            continue
        kept.append(r)
        if (i + 1) % 1000 == 0:
            print(f"   ... {i + 1}/{len(rows)}")

    # exact duplicates by sha256 first (cheap), then near-duplicates by phash
    seen_sha: dict[str, int] = {}
    unique: list[Row] = []
    for r in kept:
        if r.sha256 in seen_sha:
            bad += 1
            continue
        seen_sha[r.sha256] = 1
        unique.append(r)

    hashes = [int(r.phash, 16) for r in unique]
    groups, near_dupes = dedupe_groups(hashes, max_dist=args.dup_distance)
    # keep one representative per near-duplicate cluster (docs: drop duplicates, keep clusters whole)
    reps = [i for i in range(len(unique)) if groups[i] == i]
    unique = [unique[i] for i in reps]
    for new_idx in range(len(unique)):
        unique[new_idx].group = new_idx

    # ---- 4. split
    pool = hold_out_wild(unique, wild_spec, args.seed)
    assign_splits(pool, args.seed)

    # ---- 5. write + report
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(Row.__dataclass_fields__)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in unique:
            d = {k: getattr(r, k) for k in fieldnames}
            p = Path(d["path"])
            if p.is_absolute():
                try:
                    d["path"] = p.relative_to(ROOT).as_posix()
                except ValueError:
                    d["path"] = p.as_posix()
            w.writerow(d)

    counts: Counter = Counter()
    for r in unique:
        counts[(r.item, r.category, r.split)] += 1

    report = [
        "# Dataset report",
        "",
        f"- images kept: **{len(unique)}**",
        f"- dropped (decode/size/exact-dup): **{bad}**",
        f"- near-duplicates removed (phash distance <= {args.dup_distance}): **{near_dupes}**",
        f"- unknown labels skipped: **{sum(unknown.values())}**",
        f"- distinct items: **{len({r.item for r in unique})}**",
        "",
        "| item | category | train | val | test | wild | total |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    items_sorted = sorted({r.item for r in unique}, key=lambda x: -sum(1 for r in unique if r.item == x))
    for item in items_sorted:
        cat = next(r.category for r in unique if r.item == item)
        vals = [counts[(item, cat, s)] for s in (*SPLITS, "wild")]
        report.append(f"| {item} | {cat} | {vals[0]} | {vals[1]} | {vals[2]} | {vals[3]} | {sum(vals)} |")

    cats = Counter(r.category for r in unique)
    report += ["", "## By category", "", "| category | images |", "|---|---:|"]
    for c, n in cats.most_common():
        report.append(f"| {c} | {n} |")

    thin = [i for i in items_sorted if sum(1 for r in unique if r.item == i) < 80]
    if thin:
        report += ["", "## Warnings", ""]
        report += [f"- `{i}` has < 80 images - merge it upward or collect more." for i in thin]

    (out.parent / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    (out.parent / "counts.csv").write_text(
        "item,category,split,count\n"
        + "\n".join(f"{i},{c},{s},{n}" for (i, c, s), n in sorted(counts.items())),
        encoding="utf-8",
    )

    print(f"\nWrote {out}")
    print(f"  kept {len(unique)}  |  dropped {bad}  |  near-dupes {near_dupes}  |  items {len(items_sorted)}")
    print(f"  train {sum(1 for r in unique if r.split == 'train')}  "
          f"val {sum(1 for r in unique if r.split == 'val')}  "
          f"test {sum(1 for r in unique if r.split == 'test')}  "
          f"wild {sum(1 for r in unique if r.split == 'wild')}")
    print(f"  report -> {out.parent / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
