"""
Taxonomy loader — the ONE place that turns data/label_map.yaml into runtime objects.

Used by:
  * ml/export_onnx.py  -> builds artifacts/labels.json
  * backend/app/*      -> display names, guidance, text-hint matching, eco points
  * tools/build_manifest.py (indirectly, same file format)

Keeping the merge logic here means "what the model says" and "what the API explains"
can never drift apart.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data" / "label_map.yaml"

ECO_POINTS = {
    "ewaste": 10,
    "hazardous": 10,
    "biomedical": 10,
    "recyclable": 5,
    "organic": 5,
    "general": 2,
}

CATEGORY_ORDER = ["ewaste", "recyclable", "general", "organic", "hazardous", "biomedical"]


def norm(label: str) -> str:
    """'Misc. Trash' -> 'misc trash'; 'brown-glass' -> 'brown glass'; keeps Devanagari."""
    s = label.lower().strip()
    s = re.sub(r"[_\-/]+", " ", s)
    s = re.sub(r"[^\w\s.]", "", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip(" .")


def _is_word(tok: str) -> bool:
    # Devanagari words are short in characters but still meaningful
    return len(tok) >= 3 or any(ord(c) > 127 for c in tok)


# Function words that appear inside item names ("Metal can / tin") and would
# otherwise hijack plain questions ("Can I compost peels?").
STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at", "by", "with",
    "is", "are", "was", "were", "be", "been", "being", "do", "does", "did", "doing",
    "i", "me", "my", "we", "our", "you", "your", "it", "its", "this", "that",
    "these", "those", "can", "could", "would", "should", "may", "might", "will",
    "shall", "must", "how", "what", "when", "where", "which", "who", "why",
    "if", "but", "not", "no", "please",
}


@dataclass
class Item:
    id: str
    category: str
    flags: list[str] = field(default_factory=list)
    en: str = ""
    hi: str = ""
    mr: str = ""
    bin: str = ""
    steps: list[str] = field(default_factory=list)
    do_not: list[str] = field(default_factory=list)
    rule_refs: list[dict] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)

    def keywords(self) -> set[str]:
        words: set[str] = set()
        for text in [self.id, self.en, self.hi, self.mr, *self.examples]:
            for w in norm(text).split():
                if _is_word(w) and w not in STOPWORDS:
                    words.add(w)
        return words


class Taxonomy:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = path
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        self.classes: dict[str, dict] = raw["classes"]
        self.items: dict[str, Item] = {}
        for cat, block in self.classes.items():
            for it in block["items"]:
                override = it.get("override") or {}
                self.items[it["id"]] = Item(
                    id=it["id"],
                    category=cat,
                    flags=list(it.get("flags") or []),
                    en=it.get("en", it["id"]),
                    hi=it.get("hi", ""),
                    mr=it.get("mr", ""),
                    bin=block.get("bin", ""),
                    steps=list(override.get("steps", block.get("steps", []))) + list(it.get("steps_extra", [])),
                    do_not=list(override.get("do_not", block.get("do_not", []))),
                    rule_refs=list(block.get("rule_refs", [])),
                    examples=list(it.get("examples", [])),
                )
        self.sources = {
            src: {norm(k): v for k, v in mapping.items()} for src, mapping in (raw.get("sources") or {}).items()
        }

    # ------------------------------------------------------------------ lookups
    def item(self, item_id: str) -> Item | None:
        return self.items.get(item_id)

    def category_of(self, item_id: str) -> str | None:
        it = self.items.get(item_id)
        return it.category if it else None

    def display(self, item_id: str | None, lang: str = "en") -> str:
        if not item_id:
            return ""
        it = self.items.get(item_id)
        if not it:
            return item_id
        return {"hi": it.hi, "mr": it.mr}.get(lang) or it.en

    def category_display(self, category: str | None, lang: str = "en") -> str:
        if not category:
            return ""
        block = self.classes.get(category, {})
        return {"hi": block.get("hi"), "mr": block.get("mr")}.get(lang) or block.get("en", category)

    def eco_points(self, category: str | None) -> int:
        return ECO_POINTS.get(category or "", 0)

    def payload(self, item_id: str) -> dict:
        """Per-class object written into artifacts/labels.json."""
        it = self.items.get(item_id)
        if not it:
            return {"id": item_id, "name": item_id, "category": None, "flags": [], "bin": "",
                    "steps": [], "do_not": [], "rule_refs": [], "examples": []}
        return {
            "id": it.id,
            "name": it.en,
            "name_hi": it.hi,
            "name_mr": it.mr,
            "category": it.category,
            "category_name": self.category_display(it.category),
            "flags": it.flags,
            "bin": it.bin,
            "steps": it.steps,
            "do_not": it.do_not,
            "rule_refs": [r.get("title") for r in it.rule_refs],
            "examples": it.examples,
        }

    def match_text(self, text: str, limit: int = 3) -> list[str]:
        """
        Cheap text-hint fusion: 'old nokia charger' -> ['charger_cable'].
        Returns item ids ordered by keyword overlap. Used when the image is ambiguous.
        """
        raw = {w for w in norm(text).split() if _is_word(w)}
        tokens = set(raw)
        for w in raw:  # cheap singular forms so "batteries"/"bottles" still match
            if w.endswith("ies") and len(w) > 4:
                tokens.add(w[:-3] + "y")
            elif w.endswith("s") and len(w) > 3:
                tokens.add(w[:-1])
        if not tokens:
            return []
        scored = []
        for item_id, it in self.items.items():
            overlap = tokens & it.keywords()
            if overlap:
                scored.append((len(overlap), max(len(w) for w in overlap), item_id))
        scored.sort(reverse=True)
        return [item_id for _, _, item_id in scored[:limit]]

    def resolve(self, source: str, label: str) -> str | None:
        """Map a raw dataset label to an item id (used by the manifest builder)."""
        mapping = self.sources.get(source)
        if not mapping:
            return None
        key = norm(label)
        return mapping.get(key) or mapping.get(key.replace(".", ""))


_cache: dict[str, Taxonomy] = {}


def load_taxonomy(path: Path | str = DEFAULT_PATH) -> Taxonomy:
    key = str(path)
    if key not in _cache:
        _cache[key] = Taxonomy(Path(path))
    return _cache[key]
