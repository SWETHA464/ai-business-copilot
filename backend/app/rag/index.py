"""Hybrid index (FAISS dense + BM25 sparse) built from the database, which is the single source of truth.

Consistency strategy:
  * `document_chunks` rows (text + stored embedding) are authoritative; FAISS/BM25 are derived caches.
  * Any ingest/delete/reindex calls `invalidate()`; the next search rebuilds the in-memory index from the DB.
  * The FAISS file on disk is only reused when its manifest (embedding model + hash of all chunk ids) matches
    the database exactly, so a stale file can never serve deleted content.
  * Embeddings are stored in the DB, so rebuilding never re-embeds unless a chunk has no vector yet or was
    embedded with a different model.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path

import faiss
import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, DocumentChunk
from app.rag.embeddings import from_bytes, get_embedder, to_bytes
from app.rag.text_utils import tokenize
from app.utils.logging import get_logger

log = get_logger("index")


@dataclass
class ChunkRec:
    id: str
    document_id: int
    page: int | None
    index: int
    text: str


def _ids_hash(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(ids).encode()).hexdigest()


class HybridIndex:
    def __init__(self, chunks: list[ChunkRec], faiss_index, bm25, model: str, from_cache: bool):
        self.chunks = chunks                       # position == FAISS row == BM25 doc
        self.pos = {c.id: i for i, c in enumerate(chunks)}
        self.faiss = faiss_index
        self.bm25 = bm25
        self.model = model
        self.from_cache = from_cache

    @property
    def size(self) -> int:
        return len(self.chunks)

    def dense_search(self, qvec: np.ndarray, k: int, allowed_docs: set[int] | None) -> list[tuple[str, float]]:
        if not self.size or self.faiss is None:
            return []
        want = min(self.size, max(k * 8, 100)) if allowed_docs is not None else min(self.size, k)
        while True:
            scores, idx = self.faiss.search(np.asarray(qvec, dtype=np.float32).reshape(1, -1), want)
            hits = [(self.chunks[i].id, float(s)) for s, i in zip(scores[0], idx[0])
                    if i >= 0 and (allowed_docs is None or self.chunks[i].document_id in allowed_docs)]
            if len(hits) >= k or want >= self.size:
                return hits[:k]
            want = self.size

    def bm25_search(self, query: str, k: int, allowed_docs: set[int] | None) -> list[tuple[str, float]]:
        if not self.size or self.bm25 is None:
            return []
        toks = tokenize(query)
        if not toks:
            return []
        scores = self.bm25.get_scores(toks)
        order = np.argsort(-scores)
        hits: list[tuple[str, float]] = []
        for i in order:
            if scores[i] <= 0:
                break
            c = self.chunks[int(i)]
            if allowed_docs is None or c.document_id in allowed_docs:
                hits.append((c.id, float(scores[i])))
                if len(hits) >= k:
                    break
        return hits


# --------------------------------------------------------------------------- building
def _store_dir() -> Path:
    p = Path(get_settings().vector_store_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load_chunk_rows(db: Session) -> list[ChunkRec]:
    rows = db.execute(
        select(DocumentChunk.id, DocumentChunk.document_id, DocumentChunk.page,
               DocumentChunk.chunk_index, DocumentChunk.text)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.status == "ready").order_by(DocumentChunk.id)
    ).all()
    return [ChunkRec(r[0], r[1], r[2], r[3], r[4]) for r in rows]


def ensure_embeddings(db: Session, embedder) -> int:
    """Embed only chunks that have no vector or a vector from another model. Returns #chunks embedded."""
    todo = db.scalars(
        select(DocumentChunk).join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.status == "ready")
        .where((DocumentChunk.embedding.is_(None)) | (DocumentChunk.embedding_model != embedder.name))
    ).all()
    for i in range(0, len(todo), 64):
        batch = todo[i:i + 64]
        vecs = embedder.embed([c.text for c in batch])
        for c, v in zip(batch, vecs):
            c.embedding, c.embedding_model = to_bytes(v), embedder.name
    if todo:
        db.commit()
    return len(todo)


def build_index(db: Session, use_cache: bool = True) -> HybridIndex:
    embedder = get_embedder()
    recs = _load_chunk_rows(db)
    ids = [r.id for r in recs]
    manifest_path, faiss_path = _store_dir() / "manifest.json", _store_dir() / "index.faiss"
    bm25 = BM25Okapi([tokenize(r.text) or ["_"] for r in recs]) if recs else None

    faiss_index, from_cache = None, False
    if recs and use_cache and manifest_path.exists() and faiss_path.exists():
        try:
            m = json.loads(manifest_path.read_text())
            if m.get("model") == embedder.name and m.get("ids_hash") == _ids_hash(ids) and m.get("n") == len(ids):
                faiss_index, from_cache = faiss.read_index(str(faiss_path)), True
        except Exception:
            log.warning("vector store cache unreadable; rebuilding")
    if recs and faiss_index is None:
        ensure_embeddings(db, embedder)
        blobs = dict(db.execute(select(DocumentChunk.id, DocumentChunk.embedding)
                                .where(DocumentChunk.id.in_(ids))).all()) if len(ids) < 900 else None
        if blobs is None:  # avoid huge IN() lists
            blobs = {}
            for i in range(0, len(ids), 500):
                part = ids[i:i + 500]
                blobs.update(dict(db.execute(select(DocumentChunk.id, DocumentChunk.embedding)
                                             .where(DocumentChunk.id.in_(part))).all()))
        mat = np.vstack([from_bytes(blobs[i]) for i in ids]).astype(np.float32)
        faiss_index = faiss.IndexFlatIP(mat.shape[1])
        faiss_index.add(mat)
        try:
            faiss.write_index(faiss_index, str(faiss_path))
            manifest_path.write_text(json.dumps({"model": embedder.name, "n": len(ids), "dim": int(mat.shape[1]),
                                                 "ids_hash": _ids_hash(ids)}))
        except Exception:
            log.warning("could not persist vector store cache")
    if not recs:
        for f in (manifest_path, faiss_path):
            f.unlink(missing_ok=True)
    log.info("index built chunks=%d from_cache=%s model=%s", len(recs), from_cache, embedder.name)
    return HybridIndex(recs, faiss_index, bm25, embedder.name, from_cache)


# --------------------------------------------------------------------------- manager
_lock = threading.Lock()
_index: HybridIndex | None = None
_dirty = True


def invalidate() -> None:
    global _dirty
    with _lock:
        _dirty = True


def get_index(db: Session) -> HybridIndex:
    global _index, _dirty
    with _lock:
        if _index is None or _dirty:
            _index = build_index(db, use_cache=True)
            _dirty = False
        return _index


def rebuild_index(db: Session) -> HybridIndex:
    """Force a full rebuild from the database (drops the on-disk cache first)."""
    global _index, _dirty
    with _lock:
        for f in ("manifest.json", "index.faiss"):
            (_store_dir() / f).unlink(missing_ok=True)
        _index = build_index(db, use_cache=False)
        _dirty = False
        return _index


def verify_consistency(db: Session) -> dict:
    idx = get_index(db)
    db_ids = [r.id for r in _load_chunk_rows(db)]
    f_n = idx.faiss.ntotal if idx.faiss is not None else 0
    b_n = len(idx.bm25.doc_len) if idx.bm25 is not None else 0
    return {"db_chunks": len(db_ids), "faiss_vectors": f_n, "bm25_documents": b_n,
            "consistent": len(db_ids) == f_n == b_n == idx.size and [c.id for c in idx.chunks] == db_ids}
