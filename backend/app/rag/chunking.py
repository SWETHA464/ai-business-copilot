"""Paragraph/sentence-aware chunking with overlap. Chunks never span pages (so page citations stay exact)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.extract import Page


@dataclass
class Chunk:
    index: int
    page: int | None
    text: str


def chunk_id(document_id: int, content_hash: str, index: int) -> str:
    """Stable id: identical content + position always yields the same id for a given document."""
    return f"{document_id}-{content_hash[:16]}-{index}"


def _split_long(piece: str, size: int) -> list[str]:
    if len(piece) <= size:
        return [piece]
    sents = re.split(r"(?<=[.!?])\s+", piece)
    out, cur = [], ""
    for s in sents:
        if len(s) > size:  # unbreakable run: hard split on whitespace
            if cur:
                out.append(cur)
                cur = ""
            words, buf = s.split(" "), ""
            for w in words:
                if len(buf) + len(w) + 1 > size and buf:
                    out.append(buf)
                    buf = w
                else:
                    buf = f"{buf} {w}".strip()
            cur = buf
        elif len(cur) + len(s) + 1 > size and cur:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out


def _tail(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return ""
    t = text[-overlap:]
    cut = t.find(" ")
    return t[cut + 1:] if cut != -1 else t


def chunk_pages(pages: list[Page], size: int = 800, overlap: int = 120) -> list[Chunk]:
    size = max(size, 100)
    overlap = min(max(overlap, 0), size // 2)
    chunks: list[Chunk] = []
    for page in pages:
        units: list[str] = []
        for para in re.split(r"\n\s*\n|\n", page.text):
            para = para.strip()
            if para:
                units.extend(_split_long(para, size))
        cur = ""
        for u in units:
            if cur and len(cur) + len(u) + 1 > size:
                chunks.append(Chunk(0, page.number, cur))
                cur = (_tail(cur, overlap) + " " + u).strip()
            else:
                cur = f"{cur}\n{u}".strip() if cur else u
        if cur:
            chunks.append(Chunk(0, page.number, cur))
    good = [c for c in chunks if sum(ch.isalnum() for ch in c.text) >= 20]
    for i, c in enumerate(good):
        c.index = i
    return good
