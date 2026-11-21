"""Build the downloadable release zip from exactly the files git tracks.

Why git ls-files: the repo deliberately ships two binary model artifacts, but nothing
else that is not source. Using git as the file list means the zip can never pick up a
stray venv, __pycache__, .pytest_cache or .vscode directory.

    python tools/build_zip.py [output.zip]
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT.parent / "kachra-mitra.zip"
PREFIX = "kachra-mitra"


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    names = [n for n in out.decode("utf-8").split("\0") if n]
    return [ROOT / n for n in names]


def build(output: Path) -> tuple[int, int]:
    files = [p for p in tracked_files() if p.exists()]
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    total = 0
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(files):
            arc = Path(PREFIX) / path.relative_to(ROOT)
            zf.write(path, arc.as_posix())
            total += path.stat().st_size
    return len(files), total


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    count, size = build(out)
    print(f"{out}  {count} files  {size / 1e6:.1f} MB uncompressed  "
          f"{out.stat().st_size / 1e6:.1f} MB zipped")
