"""Thin wrapper around the exported ONNX model + taxonomy enrichment.

Loads once at startup (see main.py lifespan) so the first request is not slow.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

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

        if not settings.classifier_enabled:
            self.reason = "CLASSIFIER_ENABLED=false"
        elif not settings.onnx_file.exists():
            self.reason = f"model not found: {settings.onnx_file} (run ml/export_onnx.py)"
        elif not settings.labels_file.exists():
            self.reason = f"labels not found: {settings.labels_file}"
        else:
            try:
                from predict import OnnxClassifier  # ml/predict.py

                self.model = OnnxClassifier(settings.onnx_file, settings.labels_file)
                self.ready = True
                log.info("classifier ready: %s", settings.onnx_file.name)
            except Exception as e:  # noqa: BLE001 - a broken model must not kill the API
                self.reason = f"failed to load model: {e}"
                log.exception("classifier load failed")

        if not self.ready:
            log.warning("classifier disabled: %s", self.reason)

    # ------------------------------------------------------------------ predict
    def classify(self, img: Image.Image, lang: str = "en", text_hint: str | None = None) -> dict:
        if not self.ready or self.model is None:
            raise RuntimeError(self.reason or "classifier unavailable")

        out = self.model.predict(
            img,
            top_k=3,
            threshold=self.settings.confidence_threshold,
            margin=self.settings.confidence_margin,
        )
        item = out["item"]
        confidence = float(out["confidence"])
        source = "model"

        # ---- optional text-hint fusion (image unclear, user typed a description)
        hint_matches: list[str] = []
        if text_hint:
            hint_matches = self.taxonomy.match_text(text_hint)
            if out["uncertain"] and len(hint_matches) == 1:
                item = hint_matches[0]
                confidence = max(confidence, 0.55)
                source = "text_hint"
                out["uncertain"] = True  # still ask for confirmation, but steer the answer

        it = self.taxonomy.item(item)
        category = it.category if it else out["category"]
        top = [
            {"item": t["id"], "name": t["name"], "category": t.get("category"), "p": t["p"]}
            for t in out["top_k"]
        ]
        a, b = (top[0]["name"], top[1]["name"]) if len(top) > 1 else (top[0]["name"] if top else item, "")
        tpl = FOLLOW_UP.get(lang, FOLLOW_UP["en"])
        follow_up = (tpl[0].format(a=a, b=b) if b else tpl[1]) if out["uncertain"] else None

        return {
            "item": item,
            "item_display": self.taxonomy.display(item, lang),
            "category": category,
            "category_display": self.taxonomy.category_display(category, lang),
            "confidence": round(confidence, 4),
            "top_k": top,
            "uncertain": bool(out["uncertain"]),
            "source": source,
            "hazards": (it.flags if it else out.get("flags", [])),
            "disposal": out["disposal"],
            "facility_category": category,
            "follow_up": follow_up,
            "hint_matches": hint_matches,
            "eco_points": self.taxonomy.eco_points(category),
        }
