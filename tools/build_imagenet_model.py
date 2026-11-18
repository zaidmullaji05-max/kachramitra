#!/usr/bin/env python
"""Build a real, pretrained waste classifier from ImageNet MobileNetV3-Large.

The old `artifacts_demo` model was trained on coloured rectangles: it proves the
pipeline but cannot recognise a laptop. This script exports a genuine ImageNet model
and maps its 1,000 object classes onto the 32-item Kachra Mitra taxonomy.

    python tools/build_imagenet_model.py --out artifacts_pretrained

Outputs:
    artifacts_pretrained/mobilenet_v3_large_imagenet.onnx   (~22 MB fp32)
    artifacts_pretrained/mobilenet_v3_large_int8.onnx       (~6 MB dynamic int8)
    artifacts_pretrained/labels.json                        (class -> item map)
    artifacts_pretrained/mapping_report.md

The backend reads `labels.json["arch"]` and uses the ImageNet aggregation path.
No training data and no API key are required.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from tools.imagenet_map import item_for  # noqa: E402
from tools.taxonomy import load_taxonomy  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "artifacts_pretrained"))
    ap.add_argument("--no-int8", action="store_true", help="skip dynamic quantization")
    ap.add_argument("--check", nargs="*", default=[], help="optional images for a torch/onnx parity check")
    args = ap.parse_args()

    import numpy as np
    import torch
    from PIL import Image
    from torchvision.models import MobileNet_V3_Large_Weights, mobilenet_v3_large

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    weights = MobileNet_V3_Large_Weights.IMAGENET1K_V1
    cats = list(weights.meta["categories"])
    model = mobilenet_v3_large(weights=weights).eval()
    taxonomy = load_taxonomy(ROOT / "data" / "label_map.yaml")

    assert len(cats) == 1000
    mapped = [item_for(i, name) for i, name in enumerate(cats)]
    invalid = sorted({m for m in mapped if m and m not in taxonomy.items})
    if invalid:
        raise SystemExit(f"mapping produced unknown item ids: {invalid}")

    counts = Counter(m for m in mapped if m)
    unmapped = [c for c, m in zip(cats, mapped) if m is None]
    print(f"mapped {1000 - len(unmapped)}/1000 classes into {len(counts)} waste items")
    for item, n in counts.most_common():
        print(f"  {item:22s} {n:3d}")

    # ---- export fp32 -------------------------------------------------------
    dummy = torch.randn(1, 3, 224, 224)
    fp32_path = out / "mobilenet_v3_large_imagenet.onnx"
    torch.onnx.export(
        model,
        dummy,
        str(fp32_path),
        input_names=["input"],
        output_names=["logits"],
        opset_version=17,
        do_constant_folding=True,
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
    )
    print(f"wrote {fp32_path} ({fp32_path.stat().st_size / 1e6:.1f} MB)")

    import onnx
    onnx.checker.check_model(str(fp32_path))
    # The new torch exporter may split weights into a .onnx.data sidecar. Merge it so
    # deployment is one file and uploads stay under GitHub's 25 MB web limit.
    merged = onnx.load(str(fp32_path), load_external_data=True)
    onnx.save_model(merged, str(fp32_path), save_as_external_data=False)
    print(f"merged external weights -> {fp32_path.stat().st_size / 1e6:.1f} MB")

    # ---- dynamic int8 ------------------------------------------------------
    int8_path = out / "mobilenet_v3_large_int8.onnx"
    if not args.no_int8:
        from onnxruntime.quantization import QuantType, quantize_dynamic

        quantize_dynamic(str(fp32_path), str(int8_path), weight_type=QuantType.QInt8)
        print(f"wrote {int8_path} ({int8_path.stat().st_size / 1e6:.1f} MB)")

    # ---- labels.json -------------------------------------------------------
    meta = {
        "arch": "mobilenet_v3_large_imagenet",
        "source": "torchvision MobileNet_V3_Large_Weights.IMAGENET1K_V1",
        "img_size": 224,
        "resize_size": 256,
        "mean": [0.485, 0.456, 0.406],
        "std": [0.229, 0.224, 0.225],
        "classes": [
            {"index": i, "name": name, "item": mapped[i]} for i, name in enumerate(cats)
        ],
    }
    labels_path = out / "labels.json"
    labels_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {labels_path}")

    # ---- report ------------------------------------------------------------
    lines = [
        "# ImageNet -> waste taxonomy mapping",
        "",
        f"Source: `{meta['source']}`",
        "",
        f"- classes mapped: **{1000 - len(unmapped)} / 1000**",
        f"- items covered: **{len(counts)} / {len(taxonomy.items)}**",
        f"- unmapped classes stay `None` at runtime (the API says \"not sure\")",
        "",
        "## Classes per item",
        "",
        "| Item | Classes |",
        "|---|---|",
    ]
    lines += [f"| `{item}` | {n} |" for item, n in counts.most_common()]
    lines += ["", "## Unmapped classes (first 200)", ""]
    lines += [f"- {name}" for name in unmapped[:200]]
    (out / "mapping_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- optional parity check --------------------------------------------
    if args.check:
        import onnxruntime as ort
        sess = ort.InferenceSession(str(fp32_path), providers=["CPUExecutionProvider"])
        tf = weights.transforms()
        for path in args.check:
            img = Image.open(path).convert("RGB")
            x = tf(img).unsqueeze(0)
            with torch.no_grad():
                tp = torch.softmax(model(x), dim=1)[0].numpy()
            op = sess.run(None, {"input": x.numpy()})[0][0]
            op = np.exp(op - op.max()); op = op / op.sum()
            t5 = np.argsort(-tp)[:5]
            o5 = np.argsort(-op)[:5]
            print(f"\n{path}: top5 torch={[cats[i] for i in t5]}")
            print(f"{'':>{len(path)}}  top5 onnx ={[cats[i] for i in o5]}")
            print(f"  max |diff| = {np.abs(tp - op).max():.2e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
