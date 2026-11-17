"""Taxonomy access for the backend (delegates to tools/taxonomy.py)."""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.taxonomy import Taxonomy, load_taxonomy as _load  # noqa: E402,F401


@lru_cache
def get_taxonomy() -> Taxonomy:
    return _load(ROOT / "data" / "label_map.yaml")
