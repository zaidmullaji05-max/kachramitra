"""
Safety layer: hazard warnings and input triage.

These strings are HARD-CODED on purpose. A model (or a hallucinating LLM) must never be
the only thing standing between a user and a swollen lithium battery or a broken mercury
tube light. The API injects these warnings server-side; the chat agent cannot remove them.
"""
from __future__ import annotations

import re

from .schemas import SafetyWarning

LANG_KEY = {"en": "en", "hi": "hi", "mr": "mr"}

HAZARDS: dict[str, dict[str, str]] = {
    "battery": {
        "en": "Battery safety: tape both terminals, keep it away from metal, and if it is swollen, "
              "leaking or hot, isolate it outdoors, do not charge it, and call the helpline.",
        "hi": "बैटरी सुरक्षा: दोनों टर्मिनल पर टेप लगाएँ, धातु से दूर रखें। अगर बैटरी फूली, लीक या गरम है "
              "तो उसे बाहर अलग रखें, चार्ज न करें और हेल्पलाइन पर कॉल करें।",
        "mr": "बॅटरी सुरक्षा: दोन्ही टर्मिनलवर टेप लावा, धातूपासून दूर ठेवा. बॅटरी फुगली, गळत किंवा गरम असेल "
              "तर बाहेर वेगळी ठेवा, चार्ज करू नका आणि हेल्पलाइनला कॉल करा.",
    },
    "mercury": {
        "en": "Contains mercury: do not break, crush or vacuum it. Ventilate the room, wear gloves, "
              "seal it in a rigid container and hand it to an authorised e-waste recycler.",
        "hi": "इसमें पारा है: तोड़ें, कुचलें या वैक्यूम न करें। कमरा हवादार करें, दस्ताने पहनें, "
              "किसी सीलबंद डिब्बे में रखें और अधिकृत ई-कचरा रीसाइक्लर को दें।",
        "mr": "यात पारा आहे: तोडू, चिरडू किंवा व्हॅक्यूम करू नका. खोली हवेशीर करा, हातमोजे घाला, "
              "बंद डब्यात ठेवा आणि अधिकृत ई-कचरा रिसायकलरकडे द्या.",
    },
    "sharps": {
        "en": "Sharps: never recap, bend or break a needle. Use a puncture-proof container and hand it "
              "to a biomedical waste collection point.",
        "hi": "नुकीली वस्तु: सुई पर दोबारा ढक्कन न लगाएँ, न मोड़ें, न तोड़ें। छेद न होने वाले डिब्बे में रखें "
              "और बायोमेडिकल कचरा केंद्र पर दें।",
        "mr": "टोकदार वस्तू: सुई पुन्हा झाकू नका, वाकवू नका, तोडू नका. भोक न पडणाऱ्या डब्यात ठेवा "
              "आणि बायोमेडिकल कचरा केंद्रात द्या.",
    },
    "hazardous": {
        "en": "Domestic hazardous waste: keep it in the original sealed container with the label readable "
              "and hand it to a hazardous-waste collection point — never the regular bin or a drain.",
        "hi": "घरेलू खतरनाक कचरा: मूल डिब्बे में सीलबंद रखें, लेबल पढ़ा जा सके। नगर निगम के खतरनाक कचरा "
              "केंद्र पर दें — सामान्य कचरे के डिब्बे या नाली में कभी नहीं।",
        "mr": "घरगुती धोकादायक कचरा: मूळ डब्यात बंद ठेवा, लेबल वाचता आले पाहिजे. महानगरपालिकेच्या "
              "धोकादायक कचरा केंद्रात द्या — सामान्य कचऱ्याच्या डब्यात किंवा गटारात कधीही नाही.",
    },
    "fire_risk": {
        "en": "Fire risk: keep away from heat and flames; do not puncture or incinerate.",
        "hi": "आग का जोखिम: गर्मी और आग से दूर रखें; छेद न करें, जलाएँ नहीं।",
        "mr": "आगीचा धोका: उष्णता आणि ज्वालापासून दूर ठेवा; भोक करू नका, जाळू नका.",
    },
}

# item ids that map to a specific hazard message
ITEM_HAZARD = {
    "battery": "battery",
    "bulb_tube_light": "mercury",
    "mercury_item": "mercury",
    "syringe": "sharps",
    "aerosol": "fire_risk",
}

# keywords used to catch hazards even when the user has not scanned anything
KEYWORD_HAZARD = [
    (("battery", "बैटरी", "बॅटरी", "power bank", "lithium"), "battery"),
    (("tube light", "tubelight", "cfl", "bulb", "mercury", "ट्यूबलाइट", "बल्ब", "ट्यूबलाईट", "पारा"), "mercury"),
    (("syringe", "needle", "सुई", "सिरिंज"), "sharps"),
    (("paint", "pesticide", "aerosol", "spray", "acid", "पेंट", "कीटनाशक", "पेंट"), "hazardous"),
]

MAX_WARNINGS = 2


def warnings_for(item_id: str | None, taxonomy, lang: str = "en") -> list[SafetyWarning]:
    """Warnings derived from the ITEM's flags — not from free text, so they are reliable."""
    lang = LANG_KEY.get(lang, "en")
    out: list[SafetyWarning] = []
    if not item_id:
        return out
    it = taxonomy.item(item_id)
    if not it:
        return out

    named = ITEM_HAZARD.get(item_id)
    if named:
        level = "danger" if named in ("battery", "mercury", "sharps") else "caution"
        out.append(SafetyWarning(level=level, text=HAZARDS[named][lang]))
    elif "hazardous" in it.flags:
        out.append(SafetyWarning(level="danger", text=HAZARDS["hazardous"][lang]))

    if "fire_risk" in it.flags and named != "fire_risk":
        out.append(SafetyWarning(level="caution", text=HAZARDS["fire_risk"][lang]))
    elif "sharps" in it.flags and named != "sharps":
        out.append(SafetyWarning(level="caution", text=HAZARDS["sharps"][lang]))
    return out[:MAX_WARNINGS]


def keywords_for(text: str, lang: str = "en") -> list[SafetyWarning]:
    """Catch 'my power bank is swollen' even with no scan context."""
    low = (text or "").lower()
    out = []
    for words, key in KEYWORD_HAZARD:
        if any(w in low for w in words):
            level = "caution" if key == "hazardous" else "danger"
            out.append(SafetyWarning(level=level, text=HAZARDS[key][LANG_KEY.get(lang, "en")]))
    return out[:MAX_WARNINGS]


# --------------------------------------------------------------------- PII / abuse
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def redact(text: str) -> str:
    """Mask phone numbers / emails before anything is logged."""
    text = PHONE_RE.sub("[phone]", text)
    return EMAIL_RE.sub("[email]", text)


def refusal_reason(text: str) -> str | None:
    """
    Out-of-scope or unsafe requests. Returns a short reason key or None.
    Medical/legal advice and 'how do I dispose of something alive/explosive' are refused
    in favour of a human authority.
    """
    low = (text or "").lower()
    if any(w in low for w in ("prescribe", "dosage", "diagnose", "legal advice", "court case")):
        return "medical_or_legal"
    if any(w in low for w in ("explosive", "detonate", "make a bomb")):
        return "unsafe"
    return None
