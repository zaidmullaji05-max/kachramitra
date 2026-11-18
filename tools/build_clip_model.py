"""Build the open-vocabulary CLIP head for the Kachra Mitra classifier.

What it produces (all committed, none downloaded at runtime):

    artifacts_clip/mobileclip2_s0_visual_fp16.onnx   ~23 MB  image encoder
    artifacts_clip/clip_text_embeds.npz              ~2 MB   32 items x ~29 prompts
    artifacts_clip/clip_meta.json                             sizes / logit scale

Why fp16 and not int8: dynamic int8 quantization of this backbone collapses the
embedding (cosine similarity vs PyTorch drops to ~0.0), while fp16 keeps cosine at
0.99998 for half the file size. Re-run the `--check-images` step after any change.

Usage
-----
    python tools/build_clip_model.py                 # build + verify
    python tools/build_clip_model.py --check-images DIR
    python tools/build_clip_model.py --skip-parity   # faster, no torch forward twice

Requires the ML extras (`pip install -r requirements-ml.txt`) plus `open_clip_torch`.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODEL_NAME = "MobileCLIP2-S0"
PRETRAINED = "dfndr2b"
OUT_DIR = ROOT / "artifacts_clip"
ONNX_NAME = "mobileclip2_s0_visual_fp16.onnx"
EMBEDS_NAME = "clip_text_embeds.npz"
META_NAME = "clip_meta.json"


def build_text_embeds(model, tokenizer, prompts: list[str], negatives: list[str]):
    import torch

    with torch.no_grad():
        pos = model.encode_text(tokenizer(prompts))
        pos = pos / pos.norm(dim=-1, keepdim=True)
        neg = model.encode_text(tokenizer(negatives))
        neg = neg / neg.norm(dim=-1, keepdim=True)
    scale = float(model.logit_scale.exp().item())
    return pos.numpy().astype(np.float32), neg.numpy().astype(np.float32), scale


def export_visual_fp16(model, out_path: Path, size: int = 256) -> Path:
    """Export the visual tower to ONNX and store it as fp16 (same file at half the size)."""
    import onnx
    import torch
    from onnxruntime.transformers.float16 import convert_float_to_float16

    model.eval()
    dummy = torch.randn(1, 3, size, size)
    with tempfile.TemporaryDirectory() as tmp:
        fp32_path = Path(tmp) / "visual_fp32.onnx"
        torch.onnx.export(
            model.visual,
            dummy,
            str(fp32_path),
            input_names=["pixel_values"],
            output_names=["image_embeds"],
            opset_version=17,
            do_constant_folding=True,
            dynamo=False,
        )
        graph = onnx.load(str(fp32_path))
        graph16 = convert_float_to_float16(graph, keep_io_types=True, disable_shape_infer=True)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        onnx.save(graph16, str(out_path))
    return out_path


def parity_report(model, onnx_path: Path, size: int, images: list[Path]) -> dict:
    """Compare the ONNX encoder against PyTorch on real photos (cosine + top-1 item)."""
    import onnxruntime as ort
    import torch
    from PIL import Image

    from ml.clip_predict import CLIPClassifier

    clf = CLIPClassifier(onnx_path, OUT_DIR / EMBEDS_NAME)
    rows = []
    for path in images:
        img = Image.open(path).convert("RGB")
        got = clf.embed(img)
        x = clf.preprocess(img)
        with torch.no_grad():
            t = model.encode_image(torch.from_numpy(x))
            t = t / t.norm(dim=-1, keepdim=True)
        cos = float((t.numpy().reshape(-1) * got).sum())
        out = clf.predict(img)
        rows.append({
            "image": path.name,
            "cosine": round(cos, 5),
            "item": out["item"],
            "p": out["confidence"],
            "is_waste": out["is_waste"],
            "negative_p": out["negative_p"],
        })
    return {"images": rows,
            "min_cosine": min((r["cosine"] for r in rows), default=None)}


def main() -> int:
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--model", default=MODEL_NAME)
    ap.add_argument("--pretrained", default=PRETRAINED)
    ap.add_argument("--check-images", type=Path, default=None,
                    help="folder of test photos for a parity + sanity report")
    ap.add_argument("--skip-parity", action="store_true")
    args = ap.parse_args()

    try:
        import open_clip
        import torch
    except ImportError:
        print("Install open_clip_torch and torch first: pip install -r requirements-ml.txt")
        return 2

    from tools.clip_prompts import build_prompts, negative_prompts
    from tools.taxonomy import load_taxonomy

    taxonomy = load_taxonomy(ROOT / "data" / "label_map.yaml")
    prompts, owners = build_prompts(taxonomy)
    negatives = negative_prompts()
    missing = {i for i in taxonomy.items} - set(owners)
    if missing:
        print(f"WARNING: items without any prompt: {sorted(missing)}")

    print(f"loading {args.model} ({args.pretrained}) ...", flush=True)
    model, _, preprocess = open_clip.create_model_and_transforms(
        args.model, pretrained=args.pretrained, device="cpu"
    )
    model.eval()
    tokenizer = open_clip.get_tokenizer(args.model)

    size = int(model.visual.image_size[0]) if isinstance(model.visual.image_size, (tuple, list)) \
        else int(model.visual.image_size)
    print(f"image size {size}, prompts {len(prompts)}, negatives {len(negatives)}")

    print("encoding text prompts ...", flush=True)
    pos, neg, logit_scale = build_text_embeds(model, tokenizer, prompts, negatives)
    args.out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.out / EMBEDS_NAME,
        embeds=pos,
        owners=np.array(owners, dtype="<U32"),
        neg_embeds=neg,
        logit_scale=np.float32(logit_scale),
    )
    print(f"wrote {args.out / EMBEDS_NAME} ({pos.shape[0]} x {pos.shape[1]})")

    print("exporting visual encoder ...", flush=True)
    onnx_path = export_visual_fp16(model, args.out / ONNX_NAME, size=size)
    print(f"wrote {onnx_path.name} ({onnx_path.stat().st_size / 1e6:.1f} MB)")

    mean, std = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]  # MobileCLIP ships without ImageNet stats
    meta = {
        "arch": args.model,
        "pretrained": args.pretrained,
        "onnx": onnx_path.name,
        "image_size": size,
        "resize_size": size,
        "mean": mean,
        "std": std,
        "logit_scale": round(logit_scale, 4),
        "prompts": len(prompts),
        "negatives": len(negatives),
        "items": sorted(set(owners)),
    }
    (args.out / META_NAME).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    if args.check_images and not args.skip_parity:
        images = sorted(p for p in args.check_images.iterdir()
                        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
        if images:
            report = parity_report(model, onnx_path, size, images)
            print(json.dumps(report, indent=2))
            if (report["min_cosine"] or 0) < 0.99:
                print("WARNING: ONNX output drifted from PyTorch; do not ship this file.")
                return 1

    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
