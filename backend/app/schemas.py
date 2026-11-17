"""Request/response models — this file IS the API contract in docs/01-architecture.md."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Lang = Literal["en", "hi", "mr"]
Category = Literal["ewaste", "recyclable", "general", "organic", "hazardous", "biomedical"]


class TopK(BaseModel):
    item: str
    name: str
    category: str | None = None
    p: float


class DisposalInfo(BaseModel):
    bin: str = ""
    steps: list[str] = Field(default_factory=list)
    do_not: list[str] = Field(default_factory=list)
    rule_refs: list[str] = Field(default_factory=list)


class SafetyWarning(BaseModel):
    level: Literal["info", "caution", "danger"] = "info"
    text: str


class ClassifyResponse(BaseModel):
    item: str
    item_display: str
    category: str
    category_display: str
    confidence: float
    top_k: list[TopK] = Field(default_factory=list)
    uncertain: bool = False
    source: Literal["model", "text_hint"] = "model"
    hazards: list[str] = Field(default_factory=list)
    warnings: list[SafetyWarning] = Field(default_factory=list)
    disposal: DisposalInfo
    facility_category: str
    follow_up: str | None = None
    hint_matches: list[str] = Field(default_factory=list)
    barcode_hint: dict | None = None
    scan_id: str
    eco_points: int = 0
    # populated only when the operator enables Cloudinary image storage
    image_url: str | None = None


class ChatContext(BaseModel):
    """Everything the agent knows about the current situation."""

    scan_id: str | None = None
    item: str | None = None
    category: str | None = None
    confidence: float | None = None
    lat: float | None = None
    lng: float | None = None


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)
    lang: Lang = "en"
    context: ChatContext | None = None
    # optional: let the agent look at the photo the user attached in this turn
    image_base64: str | None = Field(default=None, max_length=12_000_000)


class SourceRef(BaseModel):
    title: str
    url: str | None = None


class Facility(BaseModel):
    id: str
    name: str
    category: str
    lat: float
    lng: float
    address: str | None = None
    phone: str | None = None
    hours: str | None = None
    website: str | None = None
    distance_m: int | None = None
    source: str = "osm"


class FacilityList(BaseModel):
    results: list[Facility] = Field(default_factory=list)
    source: Literal["cache", "overpass", "fixture", "google"] = "cache"
    stale: bool = False
    note: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    language: Lang = "en"
    warnings: list[SafetyWarning] = Field(default_factory=list)
    facilities: list[Facility] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    tool_trace: list[str] = Field(default_factory=list)


class ScanSummary(BaseModel):
    id: str
    item: str
    category: str
    confidence: float
    uncertain: bool
    eco_points: int
    created_at: str
    image_url: str | None = None


class HistoryResponse(BaseModel):
    scans: list[ScanSummary] = Field(default_factory=list)
    total: int = 0
    eco_points: int = 0
    by_category: dict[str, int] = Field(default_factory=dict)
    # lets the UI describe the privacy setting truthfully
    image_storage: bool = False


class FeedbackRequest(BaseModel):
    scan_id: str
    correct_item: str | None = None
    correct_category: Category | None = None
    comment: str | None = Field(default=None, max_length=500)


class DirectionsResponse(BaseModel):
    facility_id: str
    distance_m: float | None = None
    duration_s: float | None = None
    steps: list[str] = Field(default_factory=list)
    google_maps_url: str
    provider: Literal["osrm", "none"] = "none"


class TaxonomyClass(BaseModel):
    id: str
    en: str
    hi: str | None = None
    mr: str | None = None
    colour: str | None = None
    icon: str | None = None
    bin: str | None = None
    items: list[dict] = Field(default_factory=list)
