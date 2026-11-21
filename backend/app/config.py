"""Configuration. Reads environment variables (and backend/.env if present)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # model
    onnx_path: str = "artifacts_pretrained/mobilenet_v3_large_imagenet.onnx"
    labels_path: str = "artifacts_pretrained/labels.json"
    classifier_enabled: bool = True
    # The synthetic `artifacts_demo` model is a pipeline test, not a waste classifier.
    # By default the API upgrades a stale demo-model path to the shipped pretrained model.
    # Set ALLOW_DEMO_MODEL=true to keep the synthetic model for a pipeline demo.
    allow_demo_model: bool = False
    # below this confidence the API sets uncertain=true and returns a follow-up question
    confidence_threshold: float = 0.60
    confidence_margin: float = 0.15

    # Open-vocabulary second opinion (MobileCLIP zero-shot). Covers the waste items the
    # ImageNet model cannot name at all: battery, charger, bulb, circuit board, syringe.
    # Set CLIP_ENABLED=false to run the ImageNet model alone.
    clip_enabled: bool = True
    clip_model_path: str = "artifacts_clip/mobileclip2_s0_visual_fp16.onnx"
    clip_embeds_path: str = "artifacts_clip/clip_text_embeds.npz"

    # storage
    db_path: str = "backend/data/app.db"

    # LLM: fake | groq | gemini
    llm_provider: str = "fake"
    groq_api_key: str = ""
    gemini_api_key: str = ""
    llm_model: str = ""
    llm_timeout_s: float = 20.0

    # Vision identification: auto | gemini | groq | off
    # "auto" uses Gemini when GEMINI_API_KEY is set, otherwise Groq. No key = off.
    vision_provider: str = "auto"
    vision_model: str = ""
    vision_timeout_s: float = 30.0

    # facilities: fixture | overpass
    facility_provider: str = "fixture"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    osrm_url: str = "https://router.project-osrm.org"
    facility_cache_days: int = 30

    # app
    allow_origins: str = "*"
    rate_limit_per_min: int = 30
    max_upload_mb: int = 8

    # admin panel: leave ADMIN_PASSWORD empty and the whole panel stays switched off.
    # Set it to a long passphrase on Render, then open /admin and log in with that value.
    admin_password: str = ""
    admin_token_ttl_hours: int = 12

    # image storage: opt-in, off by default (the app is image-free unless you say otherwise).
    # Set IMAGE_STORAGE=true and CLOUDINARY_URL=cloudinary://key:secret@cloud_name to enable.
    image_storage: bool = False
    cloudinary_url: str = ""
    cloudinary_folder: str = "kachra-mitra/scans"
    cloudinary_timeout_s: int = 15

    @property
    def onnx_file(self) -> Path:
        p = Path(self.onnx_path)
        return p if p.is_absolute() else ROOT / p

    @property
    def labels_file(self) -> Path:
        p = Path(self.labels_path)
        return p if p.is_absolute() else ROOT / p

    @property
    def clip_model_file(self) -> Path:
        p = Path(self.clip_model_path)
        return p if p.is_absolute() else ROOT / p

    @property
    def clip_embeds_file(self) -> Path:
        p = Path(self.clip_embeds_path)
        return p if p.is_absolute() else ROOT / p

    @property
    def db_file(self) -> Path:
        p = Path(self.db_path)
        return p if p.is_absolute() else ROOT / p

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allow_origins.split(",") if o.strip()]

    @property
    def image_storage_ready(self) -> bool:
        """Both the opt-in flag and a Cloudinary URL are required."""
        return bool(self.image_storage and self.cloudinary_url.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
