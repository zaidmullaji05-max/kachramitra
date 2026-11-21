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
    # Local demo: SQLite at DB_PATH. Hosted: set DATABASE_URL to a Neon Postgres string
    # (postgresql://user:pass@ep-xxx.region.aws.neon.tech/db?sslmode=require) and accounts
    # survive redeploys. An empty DATABASE_URL always means SQLite.
    db_path: str = "backend/data/app.db"
    database_url: str = ""

    # Neon Managed Better Auth. These must be declared here so Pydantic Settings
    # reads NEON_AUTH_URL and NEON_AUTH_JWKS_URL from Render's environment.
    neon_auth_url: str = ""
    neon_auth_jwks_url: str = ""

    # user accounts
    # AUTH_SECRET signs user tokens. If empty, ADMIN_PASSWORD is reused so a single secret
    # can be managed; if both are empty the app falls back to an insecure dev value and
    # /health says so. Set AUTH_SECRET on any real deployment.
    auth_secret: str = ""
    auth_token_ttl_hours: int = 720  # 30 days

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

    # facilities: fixture | overpass | auto
    # auto tries live OpenStreetMap first and falls back to the demo fixtures, so the map
    # is never empty. Use overpass in production: fixture coordinates are sample data.
    facility_provider: str = "auto"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    osrm_url: str = "https://router.project-osrm.org"
    facility_cache_days: int = 30

    # app
    allow_origins: str = "*"
    rate_limit_per_min: int = 30
    max_upload_mb: int = 8

    # admin panel: leave ADMIN_PASSWORD empty and passphrase login stays switched off.
    # Set ADMIN_EMAIL as well to seed a real admin account in the users table (Neon or SQLite).
    # That account signs in with email + password from the app and from the admin panel.
    admin_password: str = ""
    admin_email: str = ""
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
    def auth_secret_value(self) -> str:
        """One signing secret for user tokens, with a loud, documented fallback."""
        return (self.auth_secret or self.admin_password or "dev-only-insecure-secret").strip()

    @property
    def auth_secret_is_default(self) -> bool:
        return not (self.auth_secret or self.admin_password)

    @property
    def accounts_ready(self) -> bool:
        return bool(self.database_url.strip())

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
