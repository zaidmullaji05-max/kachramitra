"""Open-vocabulary identification with a vision LLM (optional).

Why this exists: a closed-set ONNX model can only return its trained classes. A vision
model can look at an arbitrary photo and choose the closest item from our fixed
taxonomy. It never writes disposal advice — the taxonomy card still owns that — so a
hallucinating model cannot invent unsafe instructions.

Configuration (Render environment or backend/.env):

    GEMINI_API_KEY=...          # free key from aistudio.google.com
    VISION_PROVIDER=auto        # auto | gemini | groq | off
    VISION_MODEL=               # optional override

`auto` uses Gemini when its key exists, otherwise Groq. With no key this module is a
no-op and the app falls back to the local pretrained ONNX classifier.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re

import httpx
from PIL import Image

from .config import Settings
from .taxonomy import get_taxonomy

log = logging.getLogger("waste.vision")

SYSTEM = (
    "You are a careful waste-identification model for India. Look at the single photo "
    "and identify the main discardable object. Choose exactly one id from the supplied "
    "taxonomy list; never invent an id. If the photo is unclear, or the main object is "
    "not waste (a person, animal, vehicle, building), choose mixed_trash with confidence "
    "at or below 0.30. Do not give disposal advice. Reply with JSON only."
)

JSON_HINT = (
    'Return exactly this shape: {"item":"<taxonomy id>","confidence":0.0,'
    '"alternatives":["<id>","<id>"],"reason":"<=15 words"}'
)


class VisionError(RuntimeError):
    """The vision provider is configured but the request/parse failed."""


def _resolve(settings: Settings) -> tuple[str, str, str, str] | None:
    """Return (provider, base_url, model, key) or None when vision is off."""
    choice = (settings.vision_provider or "auto").lower()
    if choice == "off":
        return None

    if choice in ("auto", "gemini") and settings.gemini_api_key:
        return (
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            settings.vision_model or "gemini-2.5-flash",
            settings.gemini_api_key,
        )
    if choice in ("auto", "groq") and settings.groq_api_key:
        return (
            "groq",
            "https://api.groq.com/openai/v1",
            settings.vision_model or "meta-llama/llama-4-scout-17b-16e-instruct",
            settings.groq_api_key,
        )
    return None


def enabled(settings: Settings) -> bool:
    return _resolve(settings) is not None


def status(settings: Settings) -> dict:
    """Honest capability flags for /health."""
    resolved = _resolve(settings)
    if not resolved:
        return {"enabled": False, "provider": None, "model": None}
    provider, _, model, _ = resolved
    return {"enabled": True, "provider": provider, "model": model}


def _taxonomy_prompt() -> str:
    tax = get_taxonomy()
    lines = []
    for item_id, it in tax.items.items():
        examples = ", ".join(it.examples[:4])
        suffix = f" — examples: {examples}" if examples else ""
        lines.append(f"- {item_id}: {it.en} [{it.category}]{suffix}")
    return "\n".join(lines)


def _jpeg_data_url(img: Image.Image, max_side: int = 768) -> str:
    im = img.convert("RGB")
    im.thumbnail((max_side, max_side), Image.BICUBIC)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise VisionError("empty vision response")
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise VisionError(f"no JSON in vision response: {text[:160]}")
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise VisionError(f"invalid JSON from vision model: {e}") from e
    if not isinstance(obj, dict):
        raise VisionError("vision JSON was not an object")
    return obj


def _clean_id(value: object, tax) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if raw in tax.items:
        return raw
    matches = tax.match_text(raw, limit=1)
    return matches[0] if matches else None


async def identify(img: Image.Image, lang: str, settings: Settings) -> dict | None:
    """Identify the main object. Returns None when vision is not configured."""
    resolved = _resolve(settings)
    if not resolved:
        return None
    provider, base_url, model, key = resolved

    prompt = (
        "Taxonomy (id: English name [category]):\n"
        f"{_taxonomy_prompt()}\n\n"
        "Pick the closest id for the main object in the photo. "
        "Use mixed_trash only when nothing fits or the object is not waste.\n"
        f"{JSON_HINT}"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _jpeg_data_url(img)}},
                ],
            },
        ],
        "temperature": 0.1,
        "max_tokens": 400,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=settings.vision_timeout_s) as client:
            r = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise VisionError(f"{provider}: network error: {e}") from e

    if r.status_code >= 400:
        raise VisionError(f"{provider}: HTTP {r.status_code}: {r.text[:240]}")

    try:
        content = r.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise VisionError(f"{provider}: unexpected response shape") from e

    obj = _extract_json(content)
    item = _clean_id(obj.get("item"), get_taxonomy()) or "mixed_trash"

    try:
        confidence = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    if item == "mixed_trash":
        confidence = min(confidence, 0.35)

    alternatives: list[str] = []
    for alt in obj.get("alternatives") or []:
        alt_id = _clean_id(alt.get("item") if isinstance(alt, dict) else alt, get_taxonomy())
        if alt_id and alt_id != item and alt_id not in alternatives:
            alternatives.append(alt_id)
        if len(alternatives) == 2:
            break

    reason = obj.get("reason")
    log.info("vision %s/%s -> %s (%.2f)", provider, model, item, confidence)
    return {
        "item": item,
        "confidence": confidence,
        "alternatives": alternatives,
        "reason": reason if isinstance(reason, str) else "",
        "provider": provider,
        "model": model,
        "uncertain": item == "mixed_trash" or confidence < settings.confidence_threshold,
    }
