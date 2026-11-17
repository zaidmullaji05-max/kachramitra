"""Optional Cloudinary storage for scan photos.

This is **off by default**. The privacy-first design keeps uploads in memory for one
request and stores only the label. Turn it on deliberately:

    IMAGE_STORAGE=true
    CLOUDINARY_URL=cloudinary://<api_key>:<api_secret>@<cloud_name>

What is uploaded is not the raw phone photo: `imaging.decode_upload()` has already
applied EXIF orientation and re-encoded the pixels, so GPS/EXIF metadata is gone. We
re-encode once more as a sane-size JPEG before the signed server-side upload.

Failures are swallowed on purpose. A Cloudinary outage must never break `/classify`;
the scan still gets classified and saved, just without `image_url`.
"""
from __future__ import annotations

import io
import logging

from PIL import Image

from .config import Settings

log = logging.getLogger("waste.media")


def enabled(settings: Settings) -> bool:
    return settings.image_storage_ready


def _jpeg_bytes(img: Image.Image) -> bytes:
    """Re-encode to a clean RGB JPEG. No EXIF, no ICC profile, no original filename."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue()


def upload_scan_image(img: Image.Image, scan_id: str, settings: Settings) -> str | None:
    """Upload one sanitized scan photo and return its HTTPS URL (or None)."""
    if not enabled(settings):
        return None

    try:
        import cloudinary
        import cloudinary.uploader
    except ImportError:  # pragma: no cover - only hit on a half-installed deploy
        log.warning("IMAGE_STORAGE is on but `cloudinary` is not installed; run "
                    "`pip install -r backend/requirements.txt`")
        return None

    try:
        cloudinary.config(cloudinary_url=settings.cloudinary_url, secure=True)
        buf = io.BytesIO(_jpeg_bytes(img))
        buf.name = f"{scan_id}.jpg"  # SDK uses the name only as a hint

        result = cloudinary.uploader.upload(
            buf,
            public_id=scan_id,          # stable, unguessable id; no user filename leaks
            folder=settings.cloudinary_folder,
            resource_type="image",
            type="upload",
            overwrite=False,
            unique_filename=False,
            use_filename=False,
            timeout=settings.cloudinary_timeout_s,
            tags=["kachra-mitra", "scan"],
            transformation=[
                {"width": 1024, "height": 1024, "crop": "limit"},
                {"quality": "auto:good", "fetch_format": "auto"},
            ],
        )
        url = result.get("secure_url")
        if not url:
            log.warning("Cloudinary accepted %s but returned no secure_url", scan_id)
            return None
        log.info("stored scan image %s in Cloudinary", scan_id)
        return url
    except Exception as e:  # noqa: BLE001 - storage must never break classification
        log.warning("Cloudinary upload failed for %s: %s", scan_id, e)
        return None
