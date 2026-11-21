#!/usr/bin/env python
"""
Export a trained checkpoint to ONNX (fp32 + int8) and verify it.

    python ml/export_onnx.py --ckpt artifacts/model_best.pt

Produces:
    artifacts/waste_model.onnx          fp32, dynamic batch
    artifacts/waste_model_int8.onnx     dynamically quantised (2-4x smaller, ~2x faster on CPU)
    artifacts/labels.json               class names + category + disposal text (used by the API)

The verification step is not optional: quantisation can silently destroy accuracy.
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import torch

warnings.filterwarnings("ignore", message=".*legacy TorchScript-based ONNX export.*")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml"))
sys.path.insert(0, str(ROOT))
from train import build_model  # noqa: E402
from tools.taxonomy import load_taxonomy  # noqa: E402


def class_payloads(ck: dict, taxonomy) -> list[dict]:
    """Flatten the taxonomy into the per-class objects the backend serves."""
    if ck.get("level", "item") == "category":
        out = []
        for idx, name in enumerate(ck["class_names"]):
            block = taxonomy.classes.get(name, {})
            out.append({
                "index": idx, "id": name, "name": block.get("en", name),
                "name_hi": block.get("hi"), "name_mr": block.get("mr"),
                "category": name, "category_name": block.get("en", name),
                "flags": [], "bin": block.get("bin", ""),
                "steps": block.get("steps", []), "do_not": block.get("do_not", []),
                "rule_refs": [r.get("title") for r in block.get("rule_refs", [])],
            })
        return out
    return [{"index": i, **taxonomy.payload(name)} for i, name in enumerate(ck["class_names"])]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ckpt", default=str(ROOT / "artifacts" / "model_best.pt"))
    ap.add_argument("--label-map", default=str(ROOT / "data" / "label_map.yaml"))
    ap.add_argument("--out", default=str(ROOT / "artifacts"))
    ap.add_argument("--opset", type=int, default=17)
    ap.add_argument("--no-int8", action="store_true")
    args = ap.parse_args()

    ck = torch.load(args.ckpt, map_location="cpu", weights_only=False)
    model, _, _, _ = build_model(ck["arch"], len(ck["class_names"]), pretrained=False)
    model.load_state_dict(ck["model_state"])
    model.eval()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    img_size = ck.get("img_size", 224)
    dummy = torch.randn(1, 3, img_size, img_size)
    fp32_path = out_dir / "waste_model.onnx"

    print(f"exporting {ck['arch']} -> {fp32_path}")
    kwargs = dict(
        input_names=["images"],
        output_names=["logits"],
        dynamic_axes={"images": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=args.opset,
    )
    try:
        torch.onnx.export(model, dummy, str(fp32_path), dynamo=False, **kwargs)
    except TypeError:  # older torch has no `dynamo` kwarg
        torch.onnx.export(model, dummy, str(fp32_path), **kwargs)

    import onnx

    onnx.checker.check_model(onnx.load(str(fp32_path)))
    print(f"  checker: OK  ({fp32_path.stat().st_size / 1e6:.2f} MB)")

    files = [fp32_path]
    if not args.no_int8:
        from onnxruntime.quantization import QuantType, quantize_dynamic

        int8_path = fp32_path.with_name(fp32_path.stem + "_int8.onnx")
        try:
            quantize_dynamic(str(fp32_path), str(int8_path), weight_type=QuantType.QInt8, per_channel=True)
        except TypeError:  # older onnxruntime
            quantize_dynamic(str(fp32_path), str(int8_path), weight_type=QuantType.QInt8)
        files.append(int8_path)
        print(f"  quantised: {int8_path}  ({int8_path.stat().st_size / 1e6:.2f} MB)")

    # ---- verification: does the ONNX graph agree with PyTorch?
    try:
        import onnxruntime as ort
    except ImportError:
        print("  onnxruntime not installed -> skipping numerical check (pip install onnxruntime)")
        ort = None

    if ort is not None:
        x = torch.randn(8, 3, img_size, img_size)
        with torch.no_grad():
            ref = model(x).numpy()
        for path in files:
            sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
            got = sess.run(None, {"images": x.numpy()})[0]
            diff = float(np.abs(got - ref).max())
            agree = float(np.mean(got.argmax(1) == ref.argmax(1)))
            status = "OK" if (diff < 1.0 and agree == 1.0) else "CHECK"
            print(f"  {path.name:28s} max|dlogit| {diff:.4f}  argmax agreement {agree:.0%}  [{status}]")
            if status == "CHECK":
                print("    -> quantisation is too aggressive; use the fp32 model or try --no-int8")

    # ---- labels.json for the API
    taxonomy = load_taxonomy(Path(args.label_map))
    labels = {
        "arch": ck["arch"],
        "level": ck.get("level", "item"),
        "img_size": img_size,
        "mean": list(ck.get("mean", (0.485, 0.456, 0.406))),
        "std": list(ck.get("std", (0.229, 0.224, 0.225))),
        "val_f1": ck.get("val_f1"),
        "classes": class_payloads(ck, taxonomy),
    }
    (out_dir / "labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  labels -> {out_dir / 'labels.json'} ({len(labels['classes'])} classes)")
    print("\nNext: point the backend at artifacts/waste_model_int8.onnx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
