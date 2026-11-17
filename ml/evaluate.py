#!/usr/bin/env python
"""
Evaluate a trained checkpoint on a manifest split and write a full report.

    python ml/evaluate.py --ckpt artifacts/model_best.pt --split test
    python ml/evaluate.py --ckpt artifacts/model_best.pt --split wild   # the honest number

Outputs (artifacts/eval/<split>/):
    report.md              headline metrics, per-class table, calibration, risk-coverage
    confusion_matrix.png
    confusion_matrix.csv
    errors.csv             every wrong prediction (for error analysis)
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
import yaml
from PIL import Image
from sklearn.metrics import confusion_matrix, f1_score
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml"))
from train import build_model  # noqa: E402  (reuse the exact same architecture code)


class EvalDataset(Dataset):
    def __init__(self, rows, label_to_idx, tf):
        self.rows, self.label_to_idx, self.tf = rows, label_to_idx, tf

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        with Image.open(ROOT / r["path"]) as im:
            x = self.tf(im.convert("RGB"))
        return x, self.label_to_idx[r["_label"]], i


def read_rows(manifest: Path, level: str, split: str) -> list[dict]:
    key = "item" if level == "item" else "category"
    rows = []
    with manifest.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["split"] == split:
                r["_label"] = r[key]
                rows.append(r)
    return rows


def expected_calibration_error(conf: np.ndarray, correct: np.ndarray, n_bins: int = 15):
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    table = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if not m.any():
            continue
        acc_bin, conf_bin = correct[m].mean(), conf[m].mean()
        ece += (m.sum() / len(conf)) * abs(acc_bin - conf_bin)
        table.append((lo, hi, int(m.sum()), conf_bin, acc_bin))
    return float(ece), table


def risk_coverage(conf: np.ndarray, correct: np.ndarray):
    order = np.argsort(-conf)
    sorted_correct = correct[order]
    rows = []
    for cov in np.arange(0.1, 1.01, 0.1):
        k = max(1, int(len(conf) * cov))
        rows.append((cov, float(sorted_correct[:k].mean())))
    return rows


def category_of(label: str, level: str, tax: dict) -> str:
    if level == "category":
        return label
    for cat, block in tax["classes"].items():
        if any(it["id"] == label for it in block["items"]):
            return cat
    return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ckpt", default=str(ROOT / "artifacts" / "model_best.pt"))
    ap.add_argument("--manifest", default=str(ROOT / "data" / "manifest.csv"))
    ap.add_argument("--label-map", default=str(ROOT / "data" / "label_map.yaml"))
    ap.add_argument("--split", default="test", choices=["train", "val", "test", "wild"])
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--threshold", type=float, default=0.60, help="abstain below this confidence")
    ap.add_argument("--out", default=str(ROOT / "artifacts" / "eval"))
    args = ap.parse_args()

    ck = torch.load(args.ckpt, map_location="cpu", weights_only=False)
    class_names: list[str] = ck["class_names"]
    level: str = ck.get("level", "item")
    img_size = ck.get("img_size", 224)
    mean, std = ck.get("mean", (0.485, 0.456, 0.406)), ck.get("std", (0.229, 0.224, 0.225))

    rows = read_rows(Path(args.manifest), level, args.split)
    if not rows:
        print(f"no rows with split='{args.split}' in {args.manifest}")
        return 2
    print(f"split '{args.split}': {len(rows)} images, {len(class_names)} classes, level={level}")

    tf = transforms.Compose([
        transforms.Resize(int(img_size * 1.14)),
        transforms.CenterCrop(img_size),
        transforms.ToTensor(),
        transforms.Normalize(mean, std),
    ])
    label_to_idx = {c: i for i, c in enumerate(class_names)}
    unknown = [r["_label"] for r in rows if r["_label"] not in label_to_idx]
    if unknown:
        print(f"ERROR: labels not in checkpoint: {sorted(set(unknown))[:10]} (retrain or fix the manifest)")
        return 3
    rows = [r for r in rows if r["_label"] in label_to_idx]  # keep index alignment simple

    ds = EvalDataset(rows, label_to_idx, tf)
    dl = DataLoader(ds, batch_size=args.batch, shuffle=False, num_workers=args.workers)

    model, _, _, _ = build_model(ck["arch"], len(class_names), pretrained=False)
    model.load_state_dict(ck["model_state"])
    model.eval()

    logits_all, y_all, idx_all = [], [], []
    with torch.no_grad():
        for x, y, idx in dl:
            logits_all.append(model(x))
            y_all.append(y)
            idx_all.extend(idx.tolist())
    logits = torch.cat(logits_all)
    y = torch.cat(y_all).numpy()
    probs = torch.softmax(logits, dim=1).numpy()
    pred = probs.argmax(1)
    conf = probs.max(1)
    correct = (pred == y)

    acc = float(correct.mean())
    macro_f1 = f1_score(y, pred, average="macro", zero_division=0)
    weighted_f1 = f1_score(y, pred, average="weighted", zero_division=0)
    top2 = float(np.mean([y[i] in np.argsort(-probs[i])[:2] for i in range(len(y))]))
    ece, ece_table = expected_calibration_error(conf, correct)

    # ---- per-class table
    cm = confusion_matrix(y, pred, labels=list(range(len(class_names))))
    per_class = []
    for i, name in enumerate(class_names):
        tp = cm[i, i]
        support = cm[i].sum()
        fp = cm[:, i].sum() - tp
        fn = support - tp
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / support if support else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        per_class.append((name, int(support), prec, rec, f1))

    # ---- safety: category-level recall for ewaste + hazardous
    tax = yaml.safe_load(Path(args.label_map).read_text(encoding="utf-8"))
    cat_true = np.array([category_of(class_names[i], level, tax) for i in y])
    cat_pred = np.array([category_of(class_names[i], level, tax) for i in pred])
    safety = {}
    for cat in ("ewaste", "hazardous", "biomedical"):
        mask = cat_true == cat
        if mask.sum():
            safety[cat] = (float((cat_pred[mask] == cat).mean()), int(mask.sum()))

    # ---- abstain behaviour at the operating threshold
    abstain_mask = conf < args.threshold
    answered = ~abstain_mask
    answered_acc = float(correct[answered].mean()) if answered.any() else 0.0
    coverage = float(answered.mean())

    # ---- write outputs
    out_dir = Path(args.out) / args.split
    out_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(max(6, len(class_names) * 0.45), max(5, len(class_names) * 0.42)))
    im = ax.imshow(cm, cmap="Blues")
    fig.colorbar(im, ax=ax, fraction=0.046)
    ax.set_xticks(range(len(class_names)), class_names, rotation=90, fontsize=7)
    ax.set_yticks(range(len(class_names)), class_names, fontsize=7)
    ax.set_xlabel("predicted")
    ax.set_ylabel("true")
    ax.set_title(f"Confusion matrix — {args.split} (acc {acc:.3f})")
    for i in range(len(class_names)):
        for j in range(len(class_names)):
            if cm[i, j]:
                ax.text(j, i, str(cm[i, j]), ha="center", va="center",
                        fontsize=6, color="white" if cm[i, j] > cm.max() / 2 else "black")
    fig.tight_layout()
    fig.savefig(out_dir / "confusion_matrix.png", dpi=160)
    plt.close(fig)

    with (out_dir / "confusion_matrix.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["true\\pred", *class_names])
        for i, name in enumerate(class_names):
            w.writerow([name, *cm[i].tolist()])

    with (out_dir / "errors.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["path", "true", "pred", "confidence"])
        for k, i in enumerate(idx_all):
            if not correct[k]:
                w.writerow([rows[i]["path"], class_names[y[k]], class_names[pred[k]], f"{conf[k]:.3f}"])

    lines = [
        f"# Evaluation — `{args.split}`",
        "",
        f"- arch: `{ck['arch']}` · level: `{level}` · images: **{len(y)}**",
        f"- **accuracy**: {acc:.4f}",
        f"- **macro-F1**: {macro_f1:.4f}",
        f"- weighted-F1: {weighted_f1:.4f}",
        f"- top-2 accuracy: {top2:.4f}",
        f"- ECE (15 bins): {ece:.4f}",
        f"- abstain < {args.threshold:.2f}: coverage {coverage:.3f} → accuracy on answered {answered_acc:.4f}",
        "",
        "## Per-class",
        "",
        "| class | support | precision | recall | F1 |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, sup, p, r, f1 in sorted(per_class, key=lambda t: t[4]):
        lines.append(f"| {name} | {sup} | {p:.3f} | {r:.3f} | {f1:.3f} |")

    if safety:
        lines += ["", "## Safety-critical category recall", "", "| category | recall | support |", "|---|---:|---:|"]
        for cat, (rec, sup) in safety.items():
            lines.append(f"| {cat} | {rec:.3f} | {sup} |")

    lines += ["", "## Calibration", "", "| bin | n | mean conf | accuracy |", "|---|---:|---:|---:|"]
    for lo, hi, n, c, a in ece_table:
        lines.append(f"| {lo:.2f}–{hi:.2f} | {n} | {c:.3f} | {a:.3f} |")

    lines += ["", "## Risk–coverage", "", "| coverage | accuracy |", "|---:|---:|"]
    for cov, a in risk_coverage(conf, correct):
        lines.append(f"| {cov:.1f} | {a:.3f} |")

    worst = sorted(per_class, key=lambda t: t[4])[:3]
    lines += ["", "## Read this before you present", ""]
    for name, sup, _, rec, f1 in worst:
        lines.append(f"- `{name}` F1 {f1:.3f} (recall {rec:.3f}, n={sup}) — check `errors.csv` for what it is confused with.")
    if args.split == "test":
        lines.append("- Compare with `--split wild`: the gap is your real-world performance loss.")

    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\naccuracy {acc:.4f} | macro-F1 {macro_f1:.4f} | top-2 {top2:.4f} | ECE {ece:.4f}")
    print(f"coverage@thr={args.threshold:.2f} {coverage:.3f} (accuracy {answered_acc:.4f})")
    for cat, (rec, sup) in safety.items():
        print(f"safety recall[{cat}] {rec:.3f} (n={sup})")
    print(f"report -> {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
