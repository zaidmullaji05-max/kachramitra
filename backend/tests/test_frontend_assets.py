"""Frontend asset guards.

These exist because of a real bug: `index.html` was rewritten by a script that read
UTF-8 as Windows-1252. The file was still "valid HTML" and still opened, but every
character outside ASCII was destroyed — हिन्दी became à¤¹à¤¿à¤¨à¥à¤¦à¥€, the ♻ logo became
â™», and the nav emoji became â—‰. Nothing in the Python tests would have caught it, so
this file checks the raw bytes of every shipped asset.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"

UTF8_MOJIBAKE = ("\u00e2\u20ac", "\u00c3\u00a2", "\u00e0\u00a4", "\u00c3\u00a0",
                 "\u00e2\u201e", "\ufffd", "\u00c3\u00a2\u00e2\u201a\u00ac")


def assets() -> list[Path]:
    return sorted(p for p in FRONTEND.glob("*") if p.suffix in {".html", ".css", ".js"})


def test_frontend_has_assets():
    assert assets(), "frontend/ should contain html/css/js files"


@pytest.mark.parametrize("path", assets(), ids=lambda p: p.name)
def test_asset_is_utf8_without_bom(path: Path):
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), f"{path.name} starts with a UTF-8 BOM"
    text = raw.decode("utf-8")  # raises UnicodeDecodeError if it is not UTF-8
    assert not any(sig in text for sig in UTF8_MOJIBAKE), (
        f"{path.name} contains UTF-8 text that was re-encoded as Windows-1252"
    )


def test_devanagari_survives():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert "हिं" in html and "मर" in html, "the Hindi/Marathi language buttons lost their text"


def test_lens_ui_symbols_survive():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    for symbol in ("♻", "💬", "📍", "🌱"):
        assert symbol in html, f"{symbol} is missing from index.html"


def test_cache_busting_versions_match():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    versions = set(re.findall(r"\?v=(\d{8})", html))
    assert len(versions) == 1, f"mixed asset versions in index.html: {versions}"


def test_admin_panel_files_are_linked():
    html = (FRONTEND / "admin.html").read_text(encoding="utf-8")
    assert "admin.css" in html and "admin.js" in html and "config.js" in html
    for name in ("admin.css", "admin.js"):
        assert (FRONTEND / name).exists(), f"{name} is referenced but missing"


def test_admin_panel_is_not_indexed():
    html = (FRONTEND / "admin.html").read_text(encoding="utf-8")
    assert 'name="robots" content="noindex' in html
