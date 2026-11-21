"""
Chat service — phase 1 (step 4).

This is a single-shot LLM call with the scan as context, plus a rule-based fallback that
works with zero API keys. Step 5 replaces the body of `answer()` with the tool-calling
agent loop (classifier / facilities / knowledge-base tools) and RAG grounding; the
fallback, prompt and safety wiring here are already the final shape.
"""
from __future__ import annotations

import logging
import uuid

from . import safety
from .config import Settings
from .llm import LLMError, get_provider
from .schemas import ChatRequest, ChatResponse, Facility, SourceRef
from .taxonomy import get_taxonomy

log = logging.getLogger("waste.chat")

LANGUAGE_NAME = {"en": "English", "hi": "Hindi (हिन्दी)", "mr": "Marathi (मराठी)"}

SYSTEM_PROMPT = """You are "Kachra Mitra", a waste-segregation and disposal assistant for users in India.
You help with: segregation rules, recycling methods, e-waste and battery handling, composting,
reuse ideas, environmental impact, and finding the right kind of drop-off point.

Rules you must follow:
1. Answer in {language}. Use simple words and short sentences; the user may be reading on a phone.
2. Ground your answer in Indian rules: Solid Waste Management Rules 2016 (wet/dry/domestic
   hazardous segregation), E-Waste (Management) Rules 2022 (authorised recyclers only),
   Plastic Waste Management Rules (single-use plastic ban), Battery Waste Management Rules 2022,
   Bio-Medical Waste Management Rules 2016. Name the rule when you cite it, and add
   "please verify with your municipal corporation" for anything location-specific.
3. Never tell a user to burn waste, dump it in a drain or open land, or give e-waste to an
   informal scrap dealer.
4. Never invent a facility name, address, phone number or opening hours. Only mention a place
   if it came from a tool result. Otherwise say "I can look it up if you share your location".
5. If the item could be hazardous (battery, CFL/tube light, mercury thermometer, chemicals,
   sharps, biomedical), lead with the safety warning before anything else.
6. If you are unsure what the item is, say so and ask ONE clarifying question.
7. Never give medical, legal or financial advice. Point to a doctor, lawyer or official helpline.
8. Keep answers under ~150 words unless the user explicitly asks for detail.
9. You have tools. Use `search_rules` for any rule/bin/composting question and cite the rule
   name it returns. Use `get_item_guide` before giving disposal steps for a specific item.
   Use `find_facilities` only when a location is available. Use `classify_image` only when the
   user attached a photo and you do not already know the item.

{context}"""


def build_messages(req: ChatRequest) -> list[dict]:
    tax = get_taxonomy()
    ctx: list[str] = []
    c = req.context
    if c:
        if c.item:
            it = tax.item(c.item)
            cat = it.category if it else c.category
            ctx.append(
                f"- the user just scanned: {tax.display(c.item, 'en')} "
                f"(id={c.item}, category={cat}, confidence={c.confidence or 'n/a'})"
            )
            if it and it.flags:
                ctx.append(f"- flags for that item: {', '.join(it.flags)}")
        elif c.category:
            ctx.append(f"- the user's last scan category: {c.category}")
        if c.lat is not None and c.lng is not None:
            ctx.append("- the user's approximate location is available for facility search")
    context = ("Context for this conversation:\n" + "\n".join(ctx)) if ctx else "No scan context yet."

    system = SYSTEM_PROMPT.replace("{language}", LANGUAGE_NAME.get(req.lang, "English")).replace(
        "{context}", context
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": req.message}]


# --------------------------------------------------------------------- fallback
CARD = {
    "en": ("Category", "Put it here", "Steps", "Avoid", "Rules"),
    "hi": ("श्रेणी", "कहाँ डालें", "क्या करें", "क्या न करें", "नियम"),
    "mr": ("श्रेणी", "कुठे टाकावे", "काय करावे", "काय करू नका", "नियम"),
}

GENERIC = {
    "en": (
        "I can help you decide what to do with a specific item, explain segregation rules, "
        "or find a drop-off point.\n\n"
        "Try: *\"What do I do with a broken tube light?\"*, *\"Is this milk packet recyclable?\"*, "
        "or take a photo of the item.\n\n"
        "Quick rule: green bin = wet/organic, blue bin = dry/recyclable, red/black = domestic "
        "hazardous. Batteries, CFLs and e-waste never go in the regular bin."
    ),
    "hi": (
        "मैं किसी वस्तु के निपटान का तरीका बता सकता हूँ, कचरा अलग करने के नियम समझा सकता हूँ, "
        "या नज़दीकी ड्रॉप-ऑफ केंद्र ढूँढ सकता हूँ।\n\n"
        "पूछें: *\"ट्यूबलाइट फूट गई है, क्या करूँ?\"*, *\"क्या यह दूध का पैकेट रीसाइकल होता है?\"*, "
        "या वस्तु की फोटो लें।\n\n"
        "आसान नियम: हरा डिब्बा = गीला/जैविक, नीला = सूखा/रीसाइकल, लाल/काला = घरेलू खतरनाक। "
        "बैटरी, CFL और ई-कचरा सामान्य कचरे में कभी नहीं।"
    ),
    "mr": (
        "मी एखाद्या वस्तूचे विल्हेवाट कशी करावी हे सांगू शकतो, कचरा वेगळा करण्याचे नियम समजावू शकतो, "
        "किंवा जवळचे ड्रॉप-ऑफ केंद्र शोधू शकतो.\n\n"
        "विचारा: *\"ट्यूबलाईट फुटली आहे, काय करू?\"*, *\"हे दुधाचे पाकीट रिसायकल होते का?\"*, "
        "किंवा वस्तूचा फोटो घ्या.\n\n"
        "सोपा नियम: हिरवा डबा = ओला/सेंद्रिय, निळा = कोरडा/पुनर्वापर, लाल/काळा = घरगुती धोकादायक. "
        "बॅटरी, CFL आणि ई-कचरा सामान्य कचऱ्यात कधीही नाही."
    ),
}


def item_card(item_id: str, lang: str = "en") -> str:
    tax = get_taxonomy()
    it = tax.item(item_id)
    if not it:
        return GENERIC.get(lang, GENERIC["en"])
    h = CARD.get(lang, CARD["en"])
    name = tax.display(item_id, lang)
    cat = tax.category_display(it.category, lang)
    lines = [
        f"**{name}**",
        f"{h[0]}: {cat}",
        f"{h[1]}: {it.bin}",
        "",
        f"**{h[2]}**",
        *[f"{i}. {s}" for i, s in enumerate(it.steps, 1)],
    ]
    if it.do_not:
        lines += ["", f"**{h[3]}**", *[f"- {s}" for s in it.do_not]]
    if it.rule_refs:
        titles = [r.get("title", "") for r in it.rule_refs if r.get("title")]
        if titles:
            lines += ["", f"{h[4]}: " + "; ".join(titles)]
    return "\n".join(lines)


def rule_answer(req: ChatRequest) -> str:
    """Deterministic answer from the taxonomy — no model, no network."""
    tax = get_taxonomy()
    # A named item in the question wins over the scan context, so "is a chips
    # packet recyclable?" is not answered with the last scanned item.
    item = None
    if req.message:
        matches = tax.match_text(req.message, limit=1)
        if matches:
            item = matches[0]
    if not item and req.context:
        item = req.context.item
    return item_card(item, req.lang) if item else GENERIC.get(req.lang, GENERIC["en"])


# --------------------------------------------------------------------- public API
async def answer(req: ChatRequest, settings: Settings, extra_warnings=None,
                 facilities: list[Facility] | None = None) -> ChatResponse:
    session = req.session_id or f"ses_{uuid.uuid4().hex[:16]}"
    tax = get_taxonomy()

    warnings = []
    if req.context and req.context.item:
        warnings.extend(safety.warnings_for(req.context.item, tax, req.lang))
    warnings.extend(safety.keywords_for(req.message, req.lang))
    if extra_warnings:
        warnings = list(extra_warnings) + warnings
    # de-duplicate by text, keep order
    seen, uniq = set(), []
    for w in warnings:
        if w.text not in seen:
            seen.add(w.text)
            uniq.append(w)

    source_refs: list[SourceRef] = []
    if req.context and req.context.item:
        it = tax.item(req.context.item)
        if it:
            source_refs = [SourceRef(title=r.get("title", "")) for r in it.rule_refs if r.get("title")]

    provider = get_provider(settings)
    tool_trace: list[str] = []
    if provider is None:
        text = rule_answer(req)
        tool_trace.append("rules")
        source_refs = source_refs or [SourceRef(title="label_map.yaml rule cards")]
    else:
        try:
            reply = await provider.complete(build_messages(req), temperature=0.2, max_tokens=700)
            text = reply.text or rule_answer(req)
            tool_trace.append(f"llm:{provider.name}")
        except LLMError as e:
            log.warning("LLM failed, serving rule answer: %s", e)
            text = rule_answer(req)
            tool_trace.append("llm_failed")
            tool_trace.append("rules")

    return ChatResponse(
        session_id=session,
        answer=text,
        language=req.lang,
        warnings=uniq,
        facilities=facilities or [],
        sources=source_refs,
        tool_trace=tool_trace,
    )
