"""Barcode lookup — Open Food Facts (free, ODbL, no key).

This is a HINT, not ground truth: packaging data is crowd-sourced. It raises confidence
for packaged food/drink and gives the agent something concrete to say, nothing more.
"""
from __future__ import annotations

import logging
import re

import httpx

log = logging.getLogger("waste.barcode")

URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
FIELDS = "product_name,brands,packaging,packaging_tags,categories_tags,quantity"

RECYCLABLE_WORDS = ("cardboard", "paper", "glass", "metal", "aluminium", "aluminum", "tin", "pet", "hdpe")
NOT_RECYCLABLE_WORDS = ("plastic", "pp", "ldpe", "multilayer", "pouch", "sachet")


async def barcode_hint(code: str | None) -> dict | None:
    if not code or not re.fullmatch(r"\d{8,14}", code.strip()):
        return None
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(
                URL.format(code=code.strip()),
                params={"fields": FIELDS},
                headers={"User-Agent": "waste-assistant/0.1 (student project)"},
            )
        if r.status_code != 200:
            return None
        product = (r.json() or {}).get("product")
        if not product:
            return None
    except (httpx.HTTPError, ValueError) as e:
        log.info("barcode lookup failed: %s", e)
        return None

    tags = [t.lower() for t in (product.get("packaging_tags") or [])]
    packaging = [p for p in (product.get("packaging") or "").split(",") if p.strip()]
    blob = " ".join(tags + packaging).lower()

    hint = "unknown"
    if any(w in blob for w in RECYCLABLE_WORDS):
        hint = "likely_recyclable"
    if any(w in blob for w in NOT_RECYCLABLE_WORDS) and hint == "unknown":
        hint = "likely_not_recyclable"
    if "multilayer" in blob or "pouch" in blob:
        hint = "likely_not_recyclable"

    return {
        "code": code,
        "name": product.get("product_name") or "",
        "brand": product.get("brands") or "",
        "packaging": packaging[:5] or tags[:5],
        "recyclable_hint": hint,
        "disclaimer": "Packaging data is crowd-sourced (Open Food Facts) — treat as a hint.",
    }
