"""
The four tools the chat agent can call.

Every tool returns a plain dict (JSON-serialisable) plus a short human-readable `summary`
the UI shows in `tool_trace`. Errors are returned as `{"error": ...}` instead of raising,
so one bad tool call cannot take down a conversation — the LLM gets to see the failure and
try something else (or the agent falls back to the rule card).
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .config import Settings
from .facilities import FacilityService
from .imaging import decode_upload
from .knowledge import get_knowledge
from .taxonomy import get_taxonomy

CATEGORIES = ["ewaste", "recyclable", "general", "organic", "hazardous", "biomedical"]


@dataclass
class ToolContext:
    settings: Settings
    classifier: Any            # ClassifierService (None-safe: /classify may be disabled)
    facilities: FacilityService
    lang: str = "en"
    item: str | None = None
    lat: float | None = None
    lng: float | None = None


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_rules",
            "description": (
                "Search the Indian waste-management rules and the practical household guide. "
                "Use this for any question about which bin, which rule applies, how to dispose of "
                "an item, composting, plastic grades, e-waste, batteries or biomedical waste. "
                "Returns numbered excerpts with a source title and URL — cite them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "what to look up, e.g. 'broken CFL mercury'"},
                    "k": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_item_guide",
            "description": (
                "Get the authoritative disposal card for one item id from the taxonomy: category, "
                "bin, steps, things to avoid, hazards and the rule names. Call this before giving "
                "disposal steps for a specific item."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item": {"type": "string", "description": "item id or common name, e.g. 'plastic_bottle', 'battery'"},
                },
                "required": ["item"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_facilities",
            "description": (
                "Find nearby collection points / recyclers for a waste category. Requires the "
                "user's latitude and longitude; if they are not known, do not call this — ask for "
                "location instead. Never invent a facility."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": CATEGORIES},
                    "lat": {"type": "number", "minimum": -90, "maximum": 90},
                    "lng": {"type": "number", "minimum": -180, "maximum": 180},
                    "radius_m": {"type": "integer", "minimum": 500, "maximum": 25000, "default": 5000},
                },
                "required": ["category", "lat", "lng"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_image",
            "description": (
                "Run the image classifier on a photo the user sent in this turn. Only call this when "
                "the user attached an image and you do not already have a scan for it. Returns the "
                "top item, category and confidence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "image_base64": {"type": "string", "description": "base64 of the JPEG/PNG (no data: prefix)"},
                    "hint": {"type": "string", "description": "optional short description from the user"},
                },
                "required": ["image_base64"],
            },
        },
    },
]


# --------------------------------------------------------------------------- tools
async def search_rules(ctx: ToolContext, query: str = "", k: int = 3, **_: Any) -> dict:
    kb = get_knowledge()
    hits = kb.search(query, k=max(1, min(int(k or 3), 5)))
    if not hits:
        return {"results": [], "summary": f"no rule passage matched {query!r}",
                "hint": "rephrase using the item name or the rule name"}
    results = [
        {"n": i + 1, "title": c.title, "section": c.section, "url": c.url,
         "excerpt": c.quote(), "score": round(s, 3)}
        for i, (c, s) in enumerate(hits)
    ]
    return {"results": results, "summary": f"{len(results)} excerpt(s) for {query!r}",
            "results_for_citation": [r["title"] + (" — " + r["section"] if r["section"] else "") for r in results]}


async def get_item_guide(ctx: ToolContext, item: str = "", **_: Any) -> dict:
    tax = get_taxonomy()
    item_id = item if tax.item(item) else None
    if not item_id:
        matches = tax.match_text(item, limit=1)
        item_id = matches[0] if matches else None
    if not item_id:
        names = [i.en for i in tax.items.values()]
        close = [n for n in names if item.lower() in n.lower()][:6]
        return {"error": f"unknown item {item!r}", "known_items_sample": close or names[:12],
                "summary": f"no taxonomy entry for {item!r}"}
    payload = tax.payload(item_id)
    return {
        "item": payload["id"],
        "name": payload["name"],
        "name_hi": payload.get("name_hi"),
        "name_mr": payload.get("name_mr"),
        "category": payload["category"],
        "category_display": payload.get("category_name"),
        "bin": payload["bin"],
        "steps": payload["steps"],
        "do_not": payload["do_not"],
        "hazards": payload["flags"],
        "rules": payload["rule_refs"],
        "summary": f"guide for {payload['name']} ({payload['category']})",
    }


async def find_facilities(ctx: ToolContext, category: str = "recyclable", lat: float | None = None,
                          lng: float | None = None, radius_m: int = 5000, **_: Any) -> dict:
    if lat is None or lng is None:
        if ctx.lat is None or ctx.lng is None:
            return {"error": "no location available", "summary": "facility search needs lat/lng",
                    "hint": "ask the user to share their location"}
        lat, lng = ctx.lat, ctx.lng
    if category not in CATEGORIES:
        return {"error": f"category must be one of {CATEGORIES}", "summary": "bad category"}

    rows, source, stale, note = await ctx.facilities.search(
        float(lat), float(lng), category, radius_m=int(radius_m), limit=5
    )
    if not rows:
        return {"results": [], "source": source, "stale": stale, "summary": "no facilities found",
                "note": note or "try a larger radius or a different category"}
    return {
        "results": [
            {"id": f.id, "name": f.name, "category": f.category, "lat": f.lat, "lng": f.lng,
             "address": f.address, "distance_m": f.distance_m, "hours": f.hours,
             "phone": f.phone, "website": f.website, "source": f.source}
            for f in rows
        ],
        "source": source,
        "stale": stale,
        "note": note,
        "summary": f"{len(rows)} {category} facility/facilities from {source}",
    }


async def classify_image(ctx: ToolContext, image_base64: str = "", hint: str | None = None, **_: Any) -> dict:
    if not ctx.classifier or not getattr(ctx.classifier, "ready", False):
        return {"error": "classifier unavailable", "summary": "image model not loaded"}
    if not image_base64:
        return {"error": "empty image", "summary": "no image bytes"}
    raw = image_base64.split(",", 1)[-1]  # tolerate data: URLs
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return {"error": "invalid base64", "summary": "image could not be decoded"}
    if len(data) > ctx.settings.max_upload_mb * 1024 * 1024:
        return {"error": "image too large", "summary": "image exceeds the upload limit"}
    try:
        img = decode_upload(data, ctx.settings.max_upload_mb)
    except ValueError as e:
        return {"error": str(e), "summary": "image rejected"}

    out = ctx.classifier.classify(img, lang=ctx.lang, text_hint=hint)
    return {
        "item": out["item"],
        "name": out["item_display"],
        "category": out["category"],
        "category_display": out["category_display"],
        "confidence": out["confidence"],
        "uncertain": out["uncertain"],
        "top_k": out["top_k"],
        "hazards": out["hazards"],
        "summary": f"{out['item']} @ {out['confidence']:.0%}" + (" (uncertain)" if out["uncertain"] else ""),
    }


REGISTRY: dict[str, Callable[..., Awaitable[dict]]] = {
    "search_rules": search_rules,
    "get_item_guide": get_item_guide,
    "find_facilities": find_facilities,
    "classify_image": classify_image,
}


async def run_tool(name: str, args: dict, ctx: ToolContext) -> dict:
    fn = REGISTRY.get(name)
    if fn is None:
        return {"error": f"unknown tool {name!r}", "summary": f"unknown tool {name}"}
    try:
        return await fn(ctx, **(args or {}))
    except TypeError as e:
        return {"error": f"bad arguments: {e}", "summary": f"{name}: bad arguments"}
    except Exception as e:  # noqa: BLE001 - a tool crash is data, not a 500
        return {"error": f"{type(e).__name__}: {e}", "summary": f"{name} failed"}
