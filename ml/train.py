#!/usr/bin/env python
"""
Train a waste classifier with transfer learning (PyTorch + torchvision).

Reads data/manifest.csv (built by tools/build_manifest.py) and writes:
    artifacts/model_best.pt     checkpoint: weights + class names + preprocessing config
    artifacts/train_log.csv     per-epoch metrics

Examples
--------
    # the recommended first run (item-level, MobileNetV3-Small)
    python ml/train.py --level item --arch mobilenet_v3_small --epochs 25

    # safe fallback if you have little data (6 categories instead of 32 items)
    python ml/train.py --level category --arch mobilenet_v3_small --epochs 20

    # stronger model once you have > 10k images
    python ml/train.py --level item --arch efficientnet_b0 --batch 48 --epochs 30

Notes
-----
* Freeze the backbone for the first couple of epochs: small datasets + a randomly
  initialised head otherwise destroy the pretrained features with huge gradients.
* `--balanced` adds a WeightedRandomSampler on top of class-weighted loss. Use it
  when the imbalance ratio is worse than ~5:1.
* Everything is seeded; `--workers 0` is the safest on Windows.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from sklearn.metrics import f1_score, accuracy_score
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
from torchvision import transforms

ROOT = Path(__file__).resolve().parents[1]
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


# --------------------------------------------------------------------------- model
def build_model(arch: str, num_classes: int, pretrained: bool = True):
    """Return (model, head_prefix, mean, std)."""
    if arch == "mobilenet_v3_small":
        from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

        w = MobileNet_V3_Small_Weights.DEFAULT if pretrained else None
        model = mobilenet_v3_small(weights=w)
        model.classifier[3] = nn.Linear(model.classifier[3].in_features, num_classes)
        head = "classifier"
    elif arch == "mobilenet_v3_large":
        from torchvision.models import MobileNet_V3_Large_Weights, mobilenet_v3_large

        w = MobileNet_V3_Large_Weights.DEFAULT if pretrained else None
        model = mobilenet_v3_large(weights=w)
        model.classifier[3] = nn.Linear(model.classifier[3].in_features, num_classes)
        head = "classifier"
    elif arch == "efficientnet_b0":
        from torchvision.models import EfficientNet_B0_Weights, efficientnet_b0

        w = EfficientNet_B0_Weights.DEFAULT if pretrained else None
        model = efficientnet_b0(weights=w)
        model.classifier[1] = nn.Linear(model.classifier[1].in_features, num_classes)
        head = "classifier"
    elif arch == "resnet18":
        from torchvision.models import ResNet18_Weights, resnet18

        w = ResNet18_Weights.DEFAULT if pretrained else None
        model = resnet18(weights=w)
        model.fc = nn.Linear(model.fc.in_features, num_classes)
        head = "fc"
    else:
        raise ValueError(f"unknown arch {arch}")

    meta = getattr(w, "meta", {}) if w is not None else {}
    mean = meta.get("mean") or IMAGENET_MEAN
    std = meta.get("std") or IMAGENET_STD
    return model, head, tuple(mean), tuple(std)


# --------------------------------------------------------------------------- data
class ManifestDataset(Dataset):
    def __init__(self, rows, label_to_idx: dict[str, int], tf):
        self.rows = rows
        self.label_to_idx = label_to_idx
        self.tf = tf

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        with Image.open(ROOT / r["path"]) as im:
            img = self.tf(im.convert("RGB"))
        return img, self.label_to_idx[r["_label"]]


def read_manifest(path: Path, level: str, splits: set[str]) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run tools/build_manifest.py first")
    label_key = "item" if level == "item" else "category"
    rows = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["split"] in splits:
                r["_label"] = r[label_key]
                rows.append(r)
    return rows


def make_transforms(img_size: int, mean, std, train: bool):
    if train:
        return transforms.Compose(
            [
                transforms.RandomResizedCrop(img_size, scale=(0.55, 1.0), ratio=(0.75, 1.333)),
                transforms.RandomHorizontalFlip(),
                transforms.RandomRotation(12),
                transforms.ColorJitter(brightness=0.25, contrast=0.25, saturation=0.25, hue=0.04),
                transforms.RandomAffine(degrees=0, translate=(0.06, 0.06)),
                transforms.ToTensor(),
                transforms.Normalize(mean, std),
                transforms.RandomErasing(p=0.25, scale=(0.02, 0.15)),  # occlusion robustness
            ]
        )
    return transforms.Compose(
        [
            transforms.Resize(int(img_size * 1.14)),
            transforms.CenterCrop(img_size),
            transforms.ToTensor(),
            transforms.Normalize(mean, std),
        ]
    )


# --------------------------------------------------------------------------- loops
def run_epoch(model, loader, criterion, device, optimizer=None, scaler=None, frozen_backbone=False):
    training = optimizer is not None
    model.train(training)
    if training and frozen_backbone and hasattr(model, "features"):
        model.features.eval()  # keep BatchNorm stats of the frozen backbone intact

    total_loss, n = 0.0, 0
    preds, labels = [], []
    use_amp = device.type == "cuda"

    for x, y in loader:
        x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
        if training:
            optimizer.zero_grad(set_to_none=True)

        with torch.set_grad_enabled(training):
            with torch.amp.autocast("cuda", enabled=use_amp):
                logits = model(x)
                loss = criterion(logits, y)
            if training:
                scaler.scale(loss).backward()
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
                scaler.step(optimizer)
                scaler.update()

        total_loss += float(loss.detach()) * y.size(0)
        n += y.size(0)
        preds.append(logits.detach().argmax(1).cpu())
        labels.append(y.cpu())

    preds = torch.cat(preds).numpy()
    labels = torch.cat(labels).numpy()
    return (
        total_loss / max(n, 1),
        accuracy_score(labels, preds),
        f1_score(labels, preds, average="macro", zero_division=0),
        preds,
        labels,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(ROOT / "data" / "manifest.csv"))
    ap.add_argument("--level", choices=["item", "category"], default="item")
    ap.add_argument("--arch", default="mobilenet_v3_small",
                    choices=["mobilenet_v3_small", "mobilenet_v3_large", "efficientnet_b0", "resnet18"])
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--img-size", type=int, default=224)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--wd", type=float, default=0.01)
    ap.add_argument("--freeze-epochs", type=int, default=2)
    ap.add_argument("--patience", type=int, default=6)
    ap.add_argument("--label-smoothing", type=float, default=0.1)
    ap.add_argument("--balanced", action="store_true", help="WeightedRandomSampler for heavy imbalance")
    ap.add_argument("--workers", type=int, default=0 if sys.platform == "win32" else 4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=str(ROOT / "artifacts"))
    args = ap.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.backends.cudnn.deterministic = True

    device = torch.device(
        "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    )
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"device: {device} | level: {args.level} | arch: {args.arch}")

    train_rows = read_manifest(Path(args.manifest), args.level, {"train"})
    val_rows = read_manifest(Path(args.manifest), args.level, {"val"})
    if not train_rows:
        print("ERROR: no training rows. Check data/manifest.csv and its 'split' column.")
        return 2
    if not val_rows:
        print("WARNING: no val rows; using 10% of train for validation.")
        random.shuffle(train_rows)
        cut = max(1, len(train_rows) // 10)
        val_rows, train_rows = train_rows[:cut], train_rows[cut:]

    class_names = sorted({r["_label"] for r in train_rows} | {r["_label"] for r in val_rows})
    label_to_idx = {c: i for i, c in enumerate(class_names)}
    print(f"classes ({len(class_names)}): {class_names}")
    print(f"train {len(train_rows)} | val {len(val_rows)}")

    model, head, mean, std = build_model(args.arch, len(class_names))
    model.to(device)

    tf_train = make_transforms(args.img_size, mean, std, train=True)
    tf_eval = make_transforms(args.img_size, mean, std, train=False)
    ds_train = ManifestDataset(train_rows, label_to_idx, tf_train)
    ds_val = ManifestDataset(val_rows, label_to_idx, tf_eval)

    counts = np.bincount([label_to_idx[r["_label"]] for r in train_rows], minlength=len(class_names))
    print("per-class train counts:", dict(zip(class_names, counts.tolist())))
    if counts.min() < 5:
        print("WARNING: a class has < 5 training images — results will be unreliable.")

    # class weights: inverse frequency, normalised to mean 1
    freq = np.clip(counts, 1, None).astype(np.float64)
    weights = freq.sum() / (len(freq) * freq)
    samples_per_class = freq[torch.tensor([label_to_idx[r["_label"]] for r in train_rows]).numpy()]
    sampler = None
    if args.balanced:
        sampler = WeightedRandomSampler(1.0 / samples_per_class, num_samples=len(train_rows), replacement=True)
        print("using WeightedRandomSampler")

    dl_train = DataLoader(
        ds_train, batch_size=args.batch, shuffle=sampler is None, sampler=sampler,
        num_workers=args.workers, pin_memory=device.type == "cuda", drop_last=False,
    )
    dl_val = DataLoader(ds_val, batch_size=args.batch, shuffle=False, num_workers=args.workers)

    criterion = nn.CrossEntropyLoss(
        weight=torch.tensor(weights, dtype=torch.float32, device=device),
        label_smoothing=args.label_smoothing,
    )
    head_params = [p for n, p in model.named_parameters() if n.startswith(head) and p.requires_grad]
    backbone_params = [p for n, p in model.named_parameters() if not n.startswith(head)]
    optimizer = torch.optim.AdamW(
        [{"params": head_params, "lr": args.lr}, {"params": backbone_params, "lr": args.lr * 0.1}],
        weight_decay=args.wd,
    )
    steps = max(1, len(dl_train))
    warmup = torch.optim.lr_scheduler.LinearLR(optimizer, start_factor=0.1, total_iters=min(2 * steps, 200))
    cosine = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, args.epochs * steps))
    sched = torch.optim.lr_scheduler.SequentialLR(optimizer, [warmup, cosine], milestones=[min(2 * steps, 200)])
    try:
        scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    except TypeError:  # older torch
        scaler = torch.cuda.amp.GradScaler(enabled=device.type == "cuda")

    log_path = out_dir / "train_log.csv"
    with log_path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["epoch", "lr", "train_loss", "train_acc", "train_f1", "val_loss", "val_acc", "val_f1", "seconds"])

    best_f1, best_epoch, bad_epochs = -1.0, -1, 0
    ckpt_path = out_dir / "model_best.pt"

    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        frozen = epoch <= args.freeze_epochs
        for n, p in model.named_parameters():
            p.requires_grad = (not frozen) or n.startswith(head)

        tr_loss, tr_acc, tr_f1, _, _ = run_epoch(
            model, dl_train, criterion, device, optimizer, scaler, frozen_backbone=frozen,
        )
        va_loss, va_acc, va_f1, _, _ = run_epoch(model, dl_val, criterion, device)
        for _ in range(steps):
            sched.step()

        lr_now = optimizer.param_groups[0]["lr"]
        secs = time.time() - t0
        print(f"epoch {epoch:3d}/{args.epochs} {'(frozen)' if frozen else '        '} "
              f"lr {lr_now:.2e} | train loss {tr_loss:.3f} acc {tr_acc:.3f} f1 {tr_f1:.3f} "
              f"| val loss {va_loss:.3f} acc {va_acc:.3f} f1 {va_f1:.3f} | {secs:.0f}s")
        with log_path.open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([epoch, f"{lr_now:.6g}", f"{tr_loss:.4f}", f"{tr_acc:.4f}", f"{tr_f1:.4f}",
                                    f"{va_loss:.4f}", f"{va_acc:.4f}", f"{va_f1:.4f}", f"{secs:.0f}"])

        if va_f1 > best_f1 + 1e-4:
            best_f1, best_epoch, bad_epochs = va_f1, epoch, 0
            torch.save(
                {
                    "model_state": model.state_dict(),
                    "arch": args.arch,
                    "class_names": class_names,
                    "img_size": args.img_size,
                    "mean": mean,
                    "std": std,
                    "level": args.level,
                    "val_f1": best_f1,
                    "epoch": epoch,
                    "args": vars(args),
                },
                ckpt_path,
            )
            print(f"  -> saved {ckpt_path} (val macro-F1 {best_f1:.4f})")
        else:
            bad_epochs += 1
            if bad_epochs >= args.patience:
                print(f"early stopping: no val-F1 improvement for {args.patience} epochs")
                break

    print(f"\nbest val macro-F1 {best_f1:.4f} @ epoch {best_epoch}")
    (out_dir / "train_summary.json").write_text(
        json.dumps({"best_val_f1": best_f1, "best_epoch": best_epoch, "classes": class_names,
                    "level": args.level, "arch": args.arch}, indent=2),
        encoding="utf-8",
    )
    print(f"next: python ml/evaluate.py --ckpt {ckpt_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
