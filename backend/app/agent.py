"""
The chat agent: a bounded tool-calling loop with hard guardrails.

    user message
        -> system prompt (rules, language, scan context)
        -> LLM decides to call 0..n tools
        -> tools run with a per-call timeout, inside a 4-hop budget
        -> post-filter (banned advice, length, citations)
        -> answer + warnings + facilities + sources + tool_trace

If no LLM is configured, or the upstream fails, or the loop exceeds its budget without
producing text, we serve the deterministic rule card. The user always gets an answer.

Session memory is in-process (a dict with a TTL). That is the right size for one uvicorn
worker and a student project; docs/09 explains when to move it to Redis.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import safety
from .chat import SYSTEM_PROMPT, LANGUAGE_NAME, rule_answer
from .config import Settings
from .facilities import FacilityService
from .knowledge import get_knowledge
from .llm import LLMError, LLMReply, ToolCall, get_provider
from .schemas import ChatRequest, ChatResponse, Facility, SourceRef
from .taxonomy import get_taxonomy
from .tools import TOOL_SCHEMAS, ToolContext, run_tool

log = logging.getLogger("waste.agent")

MAX_HOPS = 4
TOOL_TIMEOUT_S = 10.0
MAX_HISTORY_TURNS = 6          # user+assistant pairs kept in memory
SESSION_TTL_S = 30 * 60
MAX_SESSIONS = 500

BANNED_PATTERNS = (
    "burn it", "burn the", "burn your", "incinerate at home", "dump it in the drain",
    "throw it in the drain", "flush it down the toilet", "give it to the scrap dealer",
    "throw it in the river", "bury it in the garden",
)


# --------------------------------------------------------------------------- memory
@dataclass
class Session:
    session_id: str
    turns: list[dict[str, str]] = field(default_factory=list)
    updated: float = field(default_factory=time.time)
    last_item: str | None = None


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def get(self, session_id: str) -> Session:
        self._evict()
        s = self._sessions.get(session_id)
        if s is None:
            s = Session(session_id)
            self._sessions[session_id] = s
        s.updated = time.time()
        return s

    def remember(self, session_id: str, user: str, assistant: str, item: str | None) -> None:
        s = self.get(session_id)
        s.turns.extend([{"role": "user", "content": user}, {"role": "assistant", "content": assistant}])
        s.turns = s.turns[-MAX_HISTORY_TURNS * 2:]
        s.last_item = item or s.last_item

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def _evict(self) -> None:
        now = time.time()
        for sid in [k for k, v in self._sessions.items() if now - v.updated > SESSION_TTL_S]:
            self._sessions.pop(sid, None)
        while len(self._sessions) > MAX_SESSIONS:
            oldest = min(self._sessions.values(), key=lambda s: s.updated)
            self._sessions.pop(oldest.session_id, None)


STORE = SessionStore()


# --------------------------------------------------------------------------- prompt
def build_system(req: ChatRequest, extra_item: str | None = None) -> str:
    tax = get_taxonomy()
    ctx: list[str] = []
    c = req.context
    item = extra_item or (c.item if c else None)
    if item:
        it = tax.item(item)
        cat = it.category if it else (c.category if c else None)
        ctx.append(
            f"- the user just scanned: {tax.display(item, 'en')} "
            f"(id={item}, category={cat}, confidence={c.confidence if c and c.confidence else 'n/a'})"
        )
        if it and it.flags:
            ctx.append(f"- hazards attached to that item: {', '.join(it.flags)}")
    elif c and c.category:
        ctx.append(f"- the user's last scan category: {c.category}")
    if c and c.lat is not None and c.lng is not None:
        ctx.append("- the user's approximate location is available: call find_facilities instead of asking")
    else:
        ctx.append("- no location is available: do not call find_facilities, ask the user to share location")

    context = "Context for this conversation:\n" + "\n".join(ctx)
    return (SYSTEM_PROMPT
            .replace("{language}", LANGUAGE_NAME.get(req.lang, "English"))
            .replace("{context}", context))


# --------------------------------------------------------------------------- helpers
def _assistant_msg(reply: LLMReply) -> dict:
    msg: dict[str, Any] = {"role": "assistant", "content": reply.text or ""}
    if reply.tool_calls:
        msg["tool_calls"] = [
            {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments}}
            for tc in reply.tool_calls
        ]
    return msg


def _parse_args(raw: str) -> dict:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _collect(tool_name: str, result: dict, sources: list[SourceRef], facilities: list[Facility],
             item_holder: dict) -> None:
    if tool_name == "search_rules":
        for r in result.get("results") or []:
            if r.get("url") and all(s.title != r.get("title") for s in sources):
                sources.append(SourceRef(title=r["title"], url=r["url"]))
    elif tool_name == "find_facilities":
        for r in result.get("results") or []:
            try:
                facilities.append(Facility(id=str(r["id"]), name=str(r["name"]),
                                           category=str(r.get("category") or "recyclable"),
                                           lat=float(r["lat"]), lng=float(r["lng"]),
                                           address=r.get("address"), phone=r.get("phone"),
                                           hours=r.get("hours"), website=r.get("website"),
                                           distance_m=r.get("distance_m"),
                                           source=str(r.get("source") or "osm")))
            except (KeyError, TypeError, ValueError):
                continue
    elif tool_name == "get_item_guide" and result.get("item"):
        item_holder["item"] = result["item"]
        for title in result.get("rules") or []:
            if title and all(s.title != title for s in sources):
                sources.append(SourceRef(title=title))
    elif tool_name == "classify_image" and result.get("item"):
        item_holder["item"] = result["item"]


def _post_filter(text: str) -> tuple[str, str | None]:
    low = text.lower()
    for pat in BANNED_PATTERNS:
        if pat in low:
            return text, f"blocked:{pat}"
    return text.strip(), None


def _fallback_text(req: ChatRequest, item: str | None) -> str:
    if item and not (req.context and req.context.item):
        from .chat import item_card
        return item_card(item, req.lang)
    return rule_answer(req)


# --------------------------------------------------------------------------- main entry
async def run(req: ChatRequest, settings: Settings, classifier: Any,
              facilities_svc: FacilityService) -> ChatResponse:
    started = time.perf_counter()
    session_id = req.session_id or f"ses_{uuid.uuid4().hex[:16]}"
    session = STORE.get(session_id)

    warnings = _warnings(req)
    provider = get_provider(settings)
    tool_trace: list[str] = []
    sources: list[SourceRef] = []
    facilities: list[Facility] = []
    item_holder: dict[str, str] = {}

    # context from the scan, if any
    if req.context and req.context.item:
        it = get_taxonomy().item(req.context.item)
        if it:
            for r in it.rule_refs:
                title = r.get("title") if isinstance(r, dict) else r
                if title and all(s.title != title for s in sources):
                    sources.append(SourceRef(title=title))

    # ---- no LLM: deterministic path (still honours the image, via the tool)
    if provider is None:
        if req.image_base64 and classifier and getattr(classifier, "ready", False):
            ctx = ToolContext(settings=settings, classifier=classifier, facilities=facilities_svc,
                              lang=req.lang, lat=req.context.lat if req.context else None,
                              lng=req.context.lng if req.context else None)
            res = await run_tool("classify_image", {"image_base64": req.image_base64}, ctx)
            tool_trace.append(f"classify_image: {res.get('summary', '')}")
            _collect("classify_image", res, sources, facilities, item_holder)
            if res.get("item"):
                warnings = _merge_warnings(warnings, safety.warnings_for(res["item"], get_taxonomy(), req.lang))
        text = _fallback_text(req, item_holder.get("item"))
        tool_trace.append("rules")
        if not sources:
            sources = [SourceRef(title="Rule cards (data/label_map.yaml)")]
        return _respond(session_id, req, session, text, warnings, facilities, sources, tool_trace, started)

    # ---- agent loop
    messages: list[dict[str, Any]] = [{"role": "system", "content": build_system(req, session.last_item)}]
    messages.extend(session.turns[-MAX_HISTORY_TURNS * 2:])

    user_msg = req.message
    if req.image_base64:
        user_msg += "\n\n[The user attached a photo in this turn. Call classify_image with the base64 bytes you were given in the tool arguments if you need to know what it is.]"
    messages.append({"role": "user", "content": user_msg})

    ctx = ToolContext(
        settings=settings, classifier=classifier, facilities=facilities_svc, lang=req.lang,
        lat=req.context.lat if req.context else None,
        lng=req.context.lng if req.context else None,
    )

    text = ""
    try:
        for hop in range(1, MAX_HOPS + 1):
            reply = await asyncio.wait_for(
                provider.complete(messages, tools=TOOL_SCHEMAS, temperature=0.2, max_tokens=700),
                timeout=settings.llm_timeout_s,
            )
            messages.append(_assistant_msg(reply))

            if not reply.tool_calls:
                text = reply.text
                tool_trace.append(f"llm:{provider.name}:final")
                break

            for tc in reply.tool_calls:
                if tc.name not in {t["function"]["name"] for t in TOOL_SCHEMAS}:
                    result = {"error": f"unknown tool {tc.name!r}"}
                else:
                    args = _parse_args(tc.arguments)
                    if tc.name == "classify_image" and not args.get("image_base64") and req.image_base64:
                        args["image_base64"] = req.image_base64
                    try:
                        result = await asyncio.wait_for(run_tool(tc.name, args, ctx), timeout=TOOL_TIMEOUT_S)
                    except asyncio.TimeoutError:
                        result = {"error": "tool timed out", "summary": f"{tc.name} timed out"}
                    tool_trace.append(f"{tc.name}: {result.get('summary') or result.get('error') or 'ok'}")
                    _collect(tc.name, result, sources, facilities, item_holder)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": json.dumps(result, ensure_ascii=False)[:6000],
                })

            if hop == MAX_HOPS:
                tool_trace.append("max_hops")
                text = reply.text or ""
    except asyncio.TimeoutError:
        log.warning("agent loop timed out")
        tool_trace.append("llm_timeout")
    except LLMError as e:
        log.warning("LLM failed: %s", e)
        tool_trace.append("llm_failed")
    except Exception:  # noqa: BLE001 - never 500 the chat
        log.exception("unexpected agent failure")
        tool_trace.append("agent_error")

    if not text.strip():
        text = _fallback_text(req, item_holder.get("item"))
        tool_trace.append("rules")

    text, blocked = _post_filter(text)
    if blocked:
        log.warning("blocked unsafe model output (%s)", blocked)
        tool_trace.append(blocked)
        text = _fallback_text(req, item_holder.get("item"))
        tool_trace.append("rules")

    # ---- hazards: never let the model be the only guard
    if item_holder.get("item"):
        warnings = _merge_warnings(warnings, safety.warnings_for(item_holder["item"], get_taxonomy(), req.lang))
    warnings = _merge_warnings(warnings, safety.keywords_for(text, req.lang))

    # ---- citation enforcement: if the answer cites a rule we did not retrieve, ground it
    if not sources and any(w in text.lower() for w in ("rule", "2016", "2022", "act", "regulation")):
        hits = get_knowledge().search(req.message, k=1)
        if hits:
            sources.append(SourceRef(title=hits[0][0].title, url=hits[0][0].url))

    return _respond(session_id, req, session, text, warnings, facilities, sources, tool_trace, started)


# --------------------------------------------------------------------------- utils
def _warnings(req: ChatRequest):
    out = []
    tax = get_taxonomy()
    if req.context and req.context.item:
        out.extend(safety.warnings_for(req.context.item, tax, req.lang))
    out.extend(safety.keywords_for(req.message, req.lang))
    return _merge_warnings([], out)


def _merge_warnings(base, extra):
    seen = {w.text for w in base}
    out = list(base)
    for w in extra:
        if w.text not in seen:
            seen.add(w.text)
            out.append(w)
    return out[:3]


def _respond(session_id, req, session, text, warnings, facilities, sources, tool_trace, started) -> ChatResponse:
    text = text.strip()
    if len(text) > 2400:
        text = text[:2400].rsplit(" ", 1)[0] + " …"
    STORE.remember(session_id, req.message, text,
                   req.context.item if req.context and req.context.item else None)
    return ChatResponse(
        session_id=session_id,
        answer=text,
        language=req.lang,
        warnings=warnings,
        facilities=facilities[:5],
        sources=sources[:5],
        tool_trace=tool_trace,
    )
