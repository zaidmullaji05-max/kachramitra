"""Thin wrapper around the exported ONNX model + taxonomy enrichment.

Two model kinds are supported:

* `mobilenet_v3_large_imagenet` — pretrained on 1,000 real objects and mapped onto the
  waste taxonomy. This is the default shipped model and it recognises real photos.
* the older 6/32-class fine-tuned head trained on the project datasets.

`ClassifierService` always owns the final answer: the model only proposes an item and a
confidence, and the taxonomy card supplies the disposal steps. That is what keeps a
vision model from inventing unsafe advice.
"""
from __future__ import annotations

import json
import logging
import sys

from PIL import Image

from .config import ROOT, Settings

log = logging.getLogger("waste.classifier")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "ml") not in sys.path:
    sys.path.insert(0, str(ROOT / "ml"))

from tools.taxonomy import load_taxonomy  # noqa: E402

FOLLOW_UP = {
    "en": ("Is it {a} or {b}?", "Could you retake the photo in better light, closer to the item?"),
    "hi": ("क्या यह {a} है या {b}?", "कृपया अच्छी रोशनी में, वस्तु के पास से दोबारा फोटो लें।"),
    "mr": ("हे {a} आहे की {b}?", "कृपया चांगल्या प्रकाशात, वस्तूच्या जवळून पुन्हा फोटो घ्या."),
}


class ClassifierService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.taxonomy = load_taxonomy(ROOT / "data" / "label_map.yaml")
        self.model = None
        self.ready = False
        self.reason = ""
        self.arch = ""
        self.model_name = ""
        self.clip = None
        self.clip_name = ""
        self.clip_reason = ""

        onnx_file = settings.onnx_file
        labels_file = settings.labels_file

        # Migration safeguard: old Render dashboards often still point ONNX_PATH at the
        # synthetic `artifacts_demo` model. That model cannot recognise real objects, so
        # prefer the shipped pretrained model unless the operator explicitly opts in.
        if "artifacts_demo" in str(onnx_file).replace("\\", "/") and not settings.allow_demo_model:
            pretrained = ROOT / "artifacts_pretrained" / "mobilenet_v3_large_imagenet.onnx"
            pretrained_labels = ROOT / "artifacts_pretrained" / "labels.json"
            if pretrained.exists() and pretrained_labels.exists():
                log.warning(
                    "ONNX_PATH points at the synthetic demo model; using the pretrained "
                    "ImageNet model instead (set ALLOW_DEMO_MODEL=true to override)"
                )
                onnx_file, labels_file = pretrained, pretrained_labels

        self.model_name = onnx_file.name

        if not settings.classifier_enabled:
            self.reason = "CLASSIFIER_ENABLED=false"
        elif not onnx_file.exists():
            self.reason = f"model not found: {onnx_file} (run tools/build_imagenet_model.py)"
        elif not labels_file.exists():
            self.reason = f"labels not found: {labels_file}"
        else:
            try:
                meta = json.loads(labels_file.read_text(encoding="utf-8"))
                self.arch = str(meta.get("arch", ""))
                if "imagenet" in self.arch:
                    from imagenet_predict import ImageNetClassifier

                    self.model = ImageNetClassifier(onnx_file, labels_file)
                else:
                    from predict import OnnxClassifier

                    self.model = OnnxClassifier(onnx_file, labels_file)
                self.ready = True
                log.info("classifier ready: %s (%s)", onnx_file.name, self.arch or "fine-tuned")
            except Exception as e:  # noqa: BLE001 - a broken model must not kill the API
                self.reason = f"failed to load model: {e}"
                log.exception("classifier load failed")

        if not self.ready:
            log.warning("classifier disabled: %s", self.reason)
        else:
            self._load_clip()

    # ------------------------------------------------------------------ clip head
    def _load_clip(self) -> None:
        """Load the optional zero-shot head.

        It is a second opinion, not a requirement: a missing or broken artifact only
        disables it, and `/health` reports why, so a deploy never dies because of it.
        """
        if not self.settings.clip_enabled:
            self.clip_reason = "CLIP_ENABLED=false"
            return
        if "imagenet" not in self.arch:
            self.clip_reason = "only used with the ImageNet model"
            return

        model_file = self.settings.clip_model_file
        embeds_file = self.settings.clip_embeds_file
        if not model_file.exists() or not embeds_file.exists():
            self.clip_reason = (
                f"clip artifacts missing: {model_file.name} "
                "(run tools/build_clip_model.py)"
            )
            log.warning("clip head disabled: %s", self.clip_reason)
            return

        try:
            from clip_predict import CLIPClassifier

            self.clip = CLIPClassifier(model_file, embeds_file)
            self.clip_name = model_file.name
            log.info("clip head ready: %s", model_file.name)
        except Exception as e:  # noqa: BLE001 - optional component
            self.clip_reason = f"clip load failed: {e}"
            log.exception("clip head load failed")

    @property
    def clip_status(self) -> dict:
        return {
            "enabled": self.clip is not None,
            "model": self.clip_name or None,
            "reason": None if self.clip is not None else (self.clip_reason or None),
        }

    # ------------------------------------------------------------------ predict
    def classify(self, img: Image.Image, lang: str = "en", text_hint: str | None = None) -> dict:
        if not self.ready or self.model is None:
            raise RuntimeError(self.reason or "classifier unavailable")

        # The pretrained model's aggregated item probability is naturally lower than a
        # closed-set softmax. A 0.60 gate would mark almost every real photo "uncertain".
        threshold = self.settings.confidence_threshold
        if "imagenet" in self.arch:
            threshold = min(threshold, 0.45)

        out = self.model.predict(
            img,
            top_k=3,
            threshold=threshold,
            margin=self.settings.confidence_margin,
        )

        # Second opinion: zero-shot CLIP knows the items ImageNet has no class for.
        # `fuse()` also refuses to answer when neither model found waste at all.
        clip_out = None
        if self.clip is not None:
            try:
                clip_out = self.clip.predict(img, top_k=3)
            except Exception:  # noqa: BLE001 - the optional head must not break a scan
                log.warning("clip prediction failed", exc_info=True)

        if clip_out is not None:
            from clip_predict import fuse

            merged = fuse(out, clip_out, threshold=min(threshold, 0.45))
            item = merged["item"]
            confidence = float(merged["confidence"])
            uncertain = bool(merged["uncertain"])
            top_k = merged.get("top_k") or []
            source = merged.get("source") or "model"
        else:
            item = out["item"]
            confidence = float(out["confidence"])
            uncertain = bool(out["uncertain"])
            top_k = out.get("top_k") or []
            source = "model"

        hint_matches = self.taxonomy.match_text(text_hint or "")
        if len(hint_matches) == 1 and (uncertain or item == "mixed_trash"):
            # A description the user typed themselves beats a low-confidence guess.
            item = hint_matches[0]
            confidence = max(confidence, 0.72)
            uncertain = False
            source = "text_hint"

        return self._enrich(
            item=item,
            confidence=confidence,
            top_k=top_k,
            uncertain=uncertain,
            source=source,
            lang=lang,
            hint_matches=hint_matches,
        )

    def from_vision(self, v: dict, lang: str = "en", text_hint: str | None = None) -> dict:
        """Build a full API result from `vision.identify()` output.

        Works even when the ONNX model is missing: the taxonomy still owns the advice.
        """
        item = v.get("item") or "mixed_trash"
        if item not in self.taxonomy.items:
            item = "mixed_trash"  # never trust a provider to invent a taxonomy id

        confidence = float(v.get("confidence") or 0.0)
        uncertain = bool(v.get("uncertain")) or item == "mixed_trash" \
            or confidence < self.settings.confidence_threshold
        if item == "mixed_trash":
            confidence = min(confidence, 0.35)
        source = "vision"

        hint_matches = self.taxonomy.match_text(text_hint or "")
        if len(hint_matches) == 1:
            item = hint_matches[0]
            confidence = max(confidence, 0.80)
            uncertain = False
            source = "text_hint"

        top = [{"id": item, "p": round(confidence, 4)}]
        for alt in v.get("alternatives") or []:
            alt_id = alt.get("item") if isinstance(alt, dict) else alt
            if alt_id and alt_id != item:
                p = alt.get("confidence", 0.0) if isinstance(alt, dict) else 0.0
                top.append({"id": alt_id, "p": round(float(p), 4)})

        return self._enrich(
            item=item,
            confidence=confidence,
            top_k=top,
            uncertain=uncertain,
            source=source,
            lang=lang,
            hint_matches=hint_matches,
        )

    # ------------------------------------------------------------------ enrichment
    def _enrich(self, item: str, confidence: float, top_k: list[dict], uncertain: bool,
                source: str, lang: str, hint_matches: list[str]) -> dict:
        it = self.taxonomy.item(item) or self.taxonomy.item("mixed_trash")
        if it is None:  # taxonomy file broken; fail loudly rather than silently mislead
            raise RuntimeError(f"unknown taxonomy item: {item}")
        item = it.id
        payload = self.taxonomy.payload(item)

        # Normalise top_k (models may return `id` or `item`; vision may return plain ids)
        top: list[dict] = []
        seen: set[str] = set()
        for t in top_k:
            tid = t.get("item") or t.get("id") if isinstance(t, dict) else t
            if not tid or tid in seen or tid not in self.taxonomy.items:
                continue
            seen.add(tid)
            top.append({
                "item": tid,
                "name": self.taxonomy.display(tid, "en"),
                "category": self.taxonomy.category_of(tid),
                "p": round(float(t.get("p", 0.0)) if isinstance(t, dict) else 0.0, 4),
            })
        if item not in seen:
            top.insert(0, {
                "item": item,
                "name": self.taxonomy.display(item, "en"),
                "category": it.category,
                "p": round(float(confidence), 4),
            })
        else:
            top.sort(key=lambda t: t["item"] != item)

        a = top[0]["name"] if top else item
        b = top[1]["name"] if len(top) > 1 else ""
        tpl = FOLLOW_UP.get(lang, FOLLOW_UP["en"])
        follow_up = (tpl[0].format(a=a, b=b) if b else tpl[1]) if uncertain else None

        return {
            "item": item,
            "item_display": self.taxonomy.display(item, lang),
            "category": it.category,
            "category_display": self.taxonomy.category_display(it.category, lang),
            "confidence": round(float(confidence), 4),
            "top_k": top,
            "uncertain": bool(uncertain),
            "source": source,
            "hazards": list(it.flags),
            "disposal": {
                "bin": payload["bin"],
                "steps": payload["steps"],
                "do_not": payload["do_not"],
                "rule_refs": payload["rule_refs"],
            },
            "facility_category": it.category,
            "follow_up": follow_up,
            "hint_matches": hint_matches,
            "eco_points": self.taxonomy.eco_points(it.category),
        }
