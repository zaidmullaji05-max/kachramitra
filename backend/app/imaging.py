"""Image intake: validate, strip metadata, downscale. Never writes the upload to disk."""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "BMP"}


def decode_upload(data: bytes, max_mb: int = 8, max_side: int = 1024) -> Image.Image:
    """
    Turn raw upload bytes into a clean RGB PIL image.

    * rejects huge payloads before decoding (DoS guard)
    * applies EXIF orientation so sideways phone photos classify correctly
    * drops ALL metadata (including GPS) by re-encoding into a fresh image
    * caps the long side at `max_side` so the model input stays cheap
    """
    if not data:
        raise ValueError("empty upload")
    if len(data) > max_mb * 1024 * 1024:
        raise ValueError(f"image larger than {max_mb} MB")

    try:
        img = Image.open(BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError("not a readable image") from e

    if (img.format or "").upper() not in ALLOWED_FORMATS:
        raise ValueError(f"unsupported image format: {img.format}")

    img = ImageOps.exif_transpose(img)  # orientation from EXIF, then EXIF is discarded
    img = img.convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.BICUBIC)
    # building a fresh image guarantees no EXIF/ICC/GPS chunks survive
    return img.copy()
