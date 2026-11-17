"""
Tiny BM25 knowledge base over backend/knowledge/*.md.

Why hand-rolled instead of langchain / llama-index / a vector DB?

* the corpus is six markdown files, ~15 KB of text — an inverted index fits in memory
* zero extra dependencies, zero API cost, deterministic, works offline
* a student can read the whole retrieval path in one sitting and defend it

If the corpus ever grows past a few hundred chunks, swap `bm25()` for embeddings and
pgvector behind the same `KnowledgeBase.search()` signature. The agent does not care.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parents[1] / "knowledge"

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "were",
    "be", "been", "it", "its", "this", "that", "these", "those", "with", "as", "at", "by",
    "from", "but", "not", "do", "does", "did", "can", "could", "should", "would", "will",
    "what", "which", "who", "how", "when", "where", "why", "i", "you", "we", "they", "my",
    "your", "our", "their", "me", "us", "them", "if", "then", "than", "so", "also", "any",
    "have", "has", "had", "there", "here", "about", "into", "than", "up", "down", "out",
}

K1 = 1.5
B = 0.75

TOKEN_RE = re.compile(r"[^\W\d_]+|\d+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Unicode-aware: keeps Devanagari words, drops punctuation and stopwords."""
    toks = [t.lower() for t in TOKEN_RE.findall(text or "")]
    out = []
    for t in toks:
        if len(t) < 2:
            continue
        if t in STOPWORDS:
            continue
        # cheap singularisation so "batteries" matches "battery"
        if t.endswith("ies") and len(t) > 4:
            out.append(t[:-3] + "y")
        elif t.endswith("es") and len(t) > 4:
            out.append(t[:-2])
        elif t.endswith("s") and len(t) > 3:
            out.append(t[:-1])
        out.append(t)
    return out


@dataclass
class Chunk:
    doc: str            # file stem, e.g. "01-swm-2016"
    title: str          # front-matter title
    section: str        # "## " heading text
    text: str
    url: str | None = None
    tokens: list[str] = field(default_factory=list)

    def as_source(self) -> dict:
        return {"title": f"{self.title} — {self.section}" if self.section else self.title,
                "url": self.url}

    def quote(self, max_chars: int = 700) -> str:
        body = self.text.strip()
        if len(body) > max_chars:
            body = body[:max_chars].rsplit(" ", 1)[0] + " …"
        return body


def _front_matter(raw: str) -> tuple[dict[str, str], str]:
    meta: dict[str, str] = {}
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            block = raw[3:end].strip("\n")
            body = raw[end + 4:].lstrip("\n")
            for line in block.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip().lower()] = v.strip()
            return meta, body
    return meta, raw


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Split on '## ' headings. The H1 intro becomes the section named 'Overview'."""
    sections: list[tuple[str, str]] = []
    current = "Overview"
    buf: list[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            if buf and any(x.strip() for x in buf):
                sections.append((current, "\n".join(buf).strip()))
            current = line[3:].strip()
            buf = []
        elif line.startswith("# "):
            continue
        else:
            buf.append(line)
    if buf and any(x.strip() for x in buf):
        sections.append((current, "\n".join(buf).strip()))
    return sections


class KnowledgeBase:
    def __init__(self, directory: Path = KNOWLEDGE_DIR):
        self.directory = directory
        self.chunks: list[Chunk] = []
        self.df: dict[str, int] = {}
        self.avgdl: float = 0.0
        self._load()

    def _load(self) -> None:
        if not self.directory.exists():
            return
        for path in sorted(self.directory.glob("*.md")):
            raw = path.read_text(encoding="utf-8")
            meta, body = _front_matter(raw)
            title = meta.get("title", path.stem)
            url = meta.get("source") or None
            for section, text in _split_sections(body):
                toks = tokenize(f"{title} {section} {text}")
                if not toks:
                    continue
                self.chunks.append(Chunk(doc=path.stem, title=title, section=section,
                                         text=text, url=url, tokens=toks))
        seen: dict[str, int] = {}
        for c in self.chunks:
            for t in set(c.tokens):
                seen[t] = seen.get(t, 0) + 1
        self.df = seen
        self.avgdl = sum(len(c.tokens) for c in self.chunks) / max(len(self.chunks), 1)

    # ------------------------------------------------------------------ search
    def bm25(self, query_tokens: list[str], chunk: Chunk) -> float:
        n = len(self.chunks)
        tf: dict[str, int] = {}
        for t in chunk.tokens:
            tf[t] = tf.get(t, 0) + 1
        dl = len(chunk.tokens)
        score = 0.0
        for q in query_tokens:
            if q not in tf:
                continue
            df = self.df.get(q, 0)
            if df == 0:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            freq = tf[q]
            score += idf * (freq * (K1 + 1)) / (freq + K1 * (1 - B + B * dl / max(self.avgdl, 1e-9)))
        return score

    def search(self, query: str, k: int = 4, min_score: float = 0.35) -> list[tuple[Chunk, float]]:
        qt = tokenize(query)
        if not qt or not self.chunks:
            return []
        scored = [(c, self.bm25(qt, c)) for c in self.chunks]
        scored = [(c, s) for c, s in scored if s >= min_score]
        scored.sort(key=lambda x: x[1], reverse=True)
        # keep only one chunk per (doc, section) — they are unique already, but be safe
        out, seen = [], set()
        for c, s in scored:
            key = (c.doc, c.section)
            if key in seen:
                continue
            seen.add(key)
            out.append((c, s))
            if len(out) >= k:
                break
        return out

    def stats(self) -> dict:
        return {"docs": len({c.doc for c in self.chunks}), "chunks": len(self.chunks),
                "terms": len(self.df), "avg_tokens": round(self.avgdl, 1)}


@lru_cache
def get_knowledge() -> KnowledgeBase:
    return KnowledgeBase()
