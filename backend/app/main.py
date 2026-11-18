"""FastAPI app: /classify, /chat, /facilities, /history, /feedback, /health, /taxonomy."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import db, media, safety, vision
from .agent import STORE as SESSIONS
from .agent import run as run_agent
from .classifier import ClassifierService
from .config import ROOT, get_settings
from .facilities import FacilityService
from .hints import barcode_hint
from .imaging import decode_upload
from .knowledge import get_knowledge
from .llm import get_provider
from .taxonomy import get_taxonomy
from .schemas import (
    ChatRequest,
    ChatResponse,
    ClassifyResponse,
    DirectionsResponse,
    FacilityList,
    FeedbackRequest,
    HistoryResponse,
    TaxonomyClass,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("waste.api")

VERSION = "0.1.0"
CATEGORIES = {"ewaste", "recyclable", "general", "organic", "hazardous", "biomedical"}
LANGS = {"en", "hi", "mr"}


# --------------------------------------------------------------------------- lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    db.init_db(settings.db_file)
    app.state.settings = settings
    app.state.classifier = ClassifierService(settings)
    app.state.facilities = FacilityService(settings)
    log.info("ready: classifier=%s llm=%s facilities=%s",
             app.state.classifier.ready,
             (getattr(get_provider(settings), "name", "rules")),
             settings.facility_provider)
    yield


app = FastAPI(
    title="Smart Waste Assistant API",
    version=VERSION,
    description="Classify waste, explain disposal, find facilities, and chat about it.",
    lifespan=lifespan,
)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------- rate limit
_hits: dict[str, deque[float]] = defaultdict(deque)


async def rate_limit(request: Request) -> None:
    limit = request.app.state.settings.rate_limit_per_min
    if limit <= 0:
        return
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    q = _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(status_code=429, detail="too many requests, slow down")
    q.append(now)


# --------------------------------------------------------------------------- meta
@app.get("/", include_in_schema=False)
async def root():
    return {"name": "Smart Waste Assistant API", "version": VERSION, "docs": "/docs"}


@app.get("/health")
async def health(request: Request):
    st = request.app.state
    provider = get_provider(st.settings)
    return {
        "status": "ok",
        "version": VERSION,
        "classifier": {
            "ready": st.classifier.ready,
            "reason": st.classifier.reason or None,
            "arch": st.classifier.arch or None,
            "model": st.classifier.settings.onnx_file.name,
        },
        "vision": vision.status(st.settings),
        "llm": getattr(provider, "name", "rules"),
        "facilities_provider": st.settings.facility_provider,
        "confidence_threshold": st.settings.confidence_threshold,
        "image_storage": st.settings.image_storage_ready,
        "knowledge": get_knowledge().stats(),
    }


@app.get("/taxonomy", response_model=list[TaxonomyClass])
async def taxonomy():
    tax = get_taxonomy()
    out = []
    for cat, block in tax.classes.items():
        out.append(
            TaxonomyClass(
                id=cat,
                en=block.get("en", cat),
                hi=block.get("hi"),
                mr=block.get("mr"),
                colour=block.get("color"),
                icon=block.get("icon"),
                bin=block.get("bin"),
                items=[
                    {"id": it["id"], "en": it.get("en"), "hi": it.get("hi"),
                     "mr": it.get("mr"), "flags": it.get("flags", [])}
                    for it in block["items"]
                ],
            )
        )
    return out


# --------------------------------------------------------------------------- classify
@app.post("/classify", response_model=ClassifyResponse, dependencies=[Depends(rate_limit)])
async def classify(
    request: Request,
    file: UploadFile = File(..., description="photo of a single waste item"),
    text_hint: str | None = Form(None, description="optional description, e.g. 'old nokia charger'"),
    barcode: str | None = Form(None),
    lang: str = Form("en"),
    device_id: str | None = Form(None),
):
    st = request.app.state
    if lang not in LANGS:
        raise HTTPException(status_code=400, detail=f"lang must be one of {sorted(LANGS)}")

    # validate the payload first: a malformed request is a 400 even when the model is down
    data = await file.read()
    try:
        img = decode_upload(data, st.settings.max_upload_mb)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Identification: a configured vision model reads the actual object; otherwise the
    # local ImageNet-pretrained ONNX model. Either way the taxonomy owns the advice.
    vision_info = None
    if vision.enabled(st.settings):
        try:
            vision_info = await vision.identify(img, lang, st.settings)
        except vision.VisionError as e:
            log.warning("vision identification failed, falling back: %s", e)

    if vision_info:
        result = st.classifier.from_vision(vision_info, lang=lang, text_hint=text_hint)
    elif st.classifier.ready:
        try:
            result = st.classifier.classify(img, lang=lang, text_hint=text_hint)
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
    else:
        detail = f"classifier unavailable: {st.classifier.reason}"
        if vision.status(st.settings)["enabled"]:
            detail += "; vision provider also failed (check server logs)"
        else:
            detail += "; add GEMINI_API_KEY or GROQ_API_KEY for open-vocabulary scanning"
        raise HTTPException(status_code=503, detail=detail)

    scan_id = f"scn_{uuid.uuid4().hex[:16]}"
    dev = device_id or request.headers.get("x-device-id") or "anonymous"

    # Optional Cloudinary upload. It is off by default, and a failure returns None
    # instead of failing the scan. `to_thread` keeps the blocking upload off the loop.
    image_url = await asyncio.to_thread(media.upload_scan_image, img, scan_id, st.settings)

    db.insert_scan(
        st.settings.db_file,
        {
            "id": scan_id,
            "device_id": dev,
            "item": result["item"],
            "category": result["category"],
            "confidence": result["confidence"],
            "uncertain": int(result["uncertain"]),
            "lang": lang,
            "eco_points": result["eco_points"],
            "image_url": image_url,
            "created_at": db.now_iso(),
        },
    )

    barcode_info = await barcode_hint(barcode) if barcode else None
    warnings = safety.warnings_for(result["item"], get_taxonomy(), lang)
    return ClassifyResponse(
        scan_id=scan_id,
        warnings=warnings,
        barcode_hint=barcode_info,
        image_url=image_url,
        **result,
    )


# --------------------------------------------------------------------------- chat
REFUSAL = {
    "medical_or_legal": (
        "I can't give medical or legal advice. For a health concern please contact a doctor; "
        "for a legal question contact your municipal corporation or a lawyer. "
        "I can still explain how to dispose of the item safely."
    ),
    "unsafe": (
        "I can't help with that. For anything explosive or dangerous, contact local emergency "
        "services (112) instead."
    ),
}


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(rate_limit)])
async def chat(req: ChatRequest, request: Request):
    if req.lang not in LANGS:
        raise HTTPException(status_code=400, detail=f"lang must be one of {sorted(LANGS)}")

    reason = safety.refusal_reason(req.message)
    if reason:
        return ChatResponse(
            session_id=req.session_id or f"ses_{uuid.uuid4().hex[:16]}",
            answer=REFUSAL[reason],
            language=req.lang,
            warnings=[],
            tool_trace=["refused"],
        )

    st = request.app.state
    return await run_agent(req, st.settings, st.classifier, st.facilities)


@app.post("/chat/reset")
async def chat_reset(session_id: str = Query(..., min_length=3)):
    SESSIONS.reset(session_id)
    return {"ok": True, "session_id": session_id}


# --------------------------------------------------------------------------- facilities
@app.get("/facilities", response_model=FacilityList, dependencies=[Depends(rate_limit)])
async def facilities(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    category: str = Query("recyclable"),
    radius_m: int = Query(5000, ge=100, le=25000),
    limit: int = Query(20, ge=1, le=50),
    refresh: bool = Query(False),
):
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category must be one of {sorted(CATEGORIES)}")
    results, source, stale, note = await request.app.state.facilities.search(
        lat, lng, category, radius_m=radius_m, limit=limit, refresh=refresh
    )
    return FacilityList(results=results, source=source, stale=stale, note=note)


@app.get("/facilities/{facility_id:path}/directions", response_model=DirectionsResponse,
         dependencies=[Depends(rate_limit)])
async def directions(
    facility_id: str,
    request: Request,
    lat: float | None = Query(None, ge=-90, le=90),
    lng: float | None = Query(None, ge=-180, le=180),
):
    svc: FacilityService = request.app.state.facilities
    facility = await svc.get_by_id(facility_id)
    if not facility:
        raise HTTPException(status_code=404, detail="facility not found (search again to refresh the cache)")
    return await svc.directions(facility, lat, lng)


# --------------------------------------------------------------------------- history
@app.get("/history", response_model=HistoryResponse)
async def history(request: Request, device_id: str = Query(..., min_length=1), limit: int = Query(50, ge=1, le=200)):
    st = request.app.state
    scans = db.list_scans(st.settings.db_file, device_id, limit)
    summary = db.scan_summary(st.settings.db_file, device_id)
    return HistoryResponse(
        scans=[
            {
                "id": s["id"],
                "item": s["item"],
                "category": s["category"],
                "confidence": s["confidence"],
                "uncertain": bool(s["uncertain"]),
                "eco_points": s["eco_points"],
                "created_at": s["created_at"],
                "image_url": s.get("image_url"),
            }
            for s in scans
        ],
        total=summary["total"],
        eco_points=summary["eco_points"],
        by_category=summary["by_category"],
        image_storage=st.settings.image_storage_ready,
    )


@app.post("/feedback", dependencies=[Depends(rate_limit)])
async def feedback(req: FeedbackRequest, request: Request):
    db.insert_feedback(
        request.app.state.settings.db_file,
        {
            "scan_id": req.scan_id,
            "correct_item": req.correct_item,
            "correct_category": req.correct_category,
            "comment": safety.redact(req.comment) if req.comment else None,
            "created_at": db.now_iso(),
        },
    )
    return {"ok": True}


# --------------------------------------------------------------------------- static (step 6)
if (ROOT / "frontend").exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/app", StaticFiles(directory=str(ROOT / "frontend"), html=True), name="app")
