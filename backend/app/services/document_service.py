"""Document lifecycle: validate -> store -> extract -> chunk -> embed -> index; plus access control.

Access rules (enforced here AND during retrieval, which only ever sees `accessible_doc_ids`):
  * admin: every document
  * employee: documents with visibility 'shared' plus their own private documents
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, DocumentChunk, User
from app.rag import index as rag_index
from app.rag.chunking import chunk_id, chunk_pages
from app.rag.embeddings import get_embedder, to_bytes
from app.rag.extract import ExtractionError, detect_type, extract_pages, safe_display_name
from app.utils.logging import get_logger

log = get_logger("documents")
VISIBILITIES = ("shared", "private")


class DuplicateDocument(Exception):
    def __init__(self, existing: Document):
        super().__init__("This file has already been uploaded.")
        self.existing = existing


class DocumentTooLarge(Exception):
    pass


def _upload_dir() -> Path:
    p = Path(get_settings().upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def visible_filter(user: User):
    if user.role == "admin":
        return None
    return or_(Document.visibility == "shared", Document.owner_id == user.id)


def can_view(doc: Document, user: User) -> bool:
    return user.role == "admin" or doc.visibility == "shared" or doc.owner_id == user.id


def can_modify(doc: Document, user: User) -> bool:
    return user.role == "admin" or doc.owner_id == user.id


def get_visible_document(db: Session, doc_id: int, user: User) -> Document | None:
    doc = db.get(Document, doc_id)
    return doc if doc is not None and can_view(doc, user) else None


def accessible_doc_ids(db: Session, user: User, *, category: str | None = None,
                       department: str | None = None, document_ids: list[int] | None = None) -> set[int]:
    q = select(Document.id).where(Document.status == "ready")
    vf = visible_filter(user)
    if vf is not None:
        q = q.where(vf)
    if category:
        q = q.where(Document.category == category)
    if department:
        q = q.where(Document.department == department)
    if document_ids:
        q = q.where(Document.id.in_(document_ids))
    return set(db.scalars(q).all())


def list_documents(db: Session, user: User, *, q: str | None = None, category: str | None = None,
                   department: str | None = None, status: str | None = None) -> list[Document]:
    stmt = select(Document).order_by(Document.created_at.desc(), Document.id.desc())
    vf = visible_filter(user)
    if vf is not None:
        stmt = stmt.where(vf)
    if q:
        stmt = stmt.where(Document.filename.ilike(f"%{q.strip()[:100]}%"))
    if category:
        stmt = stmt.where(Document.category == category)
    if department:
        stmt = stmt.where(Document.department == department)
    if status:
        stmt = stmt.where(Document.status == status)
    return list(db.scalars(stmt).all())


# --------------------------------------------------------------------------- indexing
def _index_content(db: Session, doc: Document, data: bytes) -> None:
    """(Re)build chunks + embeddings for `doc` from raw bytes. Raises ExtractionError on unreadable content."""
    s = get_settings()
    pages = extract_pages(data, doc.file_type)
    chunks = chunk_pages(pages, s.chunk_size, s.chunk_overlap)
    if not chunks:
        raise ExtractionError("The file contains too little text to index.")
    embedder = get_embedder()
    vecs = embedder.embed([c.text for c in chunks])
    db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete()
    for c, v in zip(chunks, vecs):
        db.add(DocumentChunk(id=chunk_id(doc.id, doc.content_hash, c.index), document_id=doc.id,
                             chunk_index=c.index, page=c.page, text=c.text,
                             embedding=to_bytes(v), embedding_model=embedder.name))
    doc.page_count = len([p for p in pages if p.number is not None]) or len(pages)
    doc.chunk_count = len(chunks)
    doc.status, doc.error = "ready", None


def ingest_bytes(db: Session, owner: User, filename: str, data: bytes, *, category: str = "general",
                 department: str = "general", visibility: str = "shared") -> Document:
    s = get_settings()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise DocumentTooLarge(f"File exceeds the {s.max_upload_mb} MB limit.")
    if visibility not in VISIBILITIES:
        raise ExtractionError("visibility must be 'shared' or 'private'.")
    display = safe_display_name(filename)
    ftype = detect_type(display, data)                      # raises ExtractionError
    digest = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(Document).where(Document.owner_id == owner.id, Document.content_hash == digest))
    if existing:
        raise DuplicateDocument(existing)
    extract_pages(data, ftype)                              # fail fast on corrupt/empty content, before any write

    stored = f"{uuid.uuid4().hex}.{ftype}"
    path = _upload_dir() / stored
    doc = Document(owner_id=owner.id, filename=display, stored_name=stored, file_type=ftype,
                   size_bytes=len(data), content_hash=digest, category=(category or "general")[:100],
                   department=(department or "general")[:100], visibility=visibility, status="processing")
    db.add(doc)
    db.flush()                                              # need doc.id for chunk ids
    try:
        _index_content(db, doc, data)
        path.write_bytes(data)
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    rag_index.invalidate()
    log.info("document ingested id=%s type=%s chunks=%s", doc.id, ftype, doc.chunk_count)
    return doc


def replace_content(db: Session, doc: Document, filename: str, data: bytes) -> Document:
    """Update a document with new file content, replacing its chunks atomically."""
    display = safe_display_name(filename)
    ftype = detect_type(display, data)
    digest = hashlib.sha256(data).hexdigest()
    clash = db.scalar(select(Document).where(Document.owner_id == doc.owner_id,
                                              Document.content_hash == digest, Document.id != doc.id))
    if clash:
        raise DuplicateDocument(clash)
    old_path = _upload_dir() / doc.stored_name
    new_stored = f"{uuid.uuid4().hex}.{ftype}"
    doc.file_type, doc.filename, doc.size_bytes = ftype, display, len(data)
    doc.content_hash, doc.stored_name = digest, new_stored
    try:
        _index_content(db, doc, data)
        (_upload_dir() / new_stored).write_bytes(data)
        db.commit()
    except Exception:
        db.rollback()
        (_upload_dir() / new_stored).unlink(missing_ok=True)
        raise
    old_path.unlink(missing_ok=True)
    rag_index.invalidate()
    return doc


def reindex_document(db: Session, doc: Document) -> Document:
    path = _upload_dir() / doc.stored_name
    if not path.exists():
        doc.status, doc.error = "failed", "Stored file is missing."
        db.commit()
        rag_index.invalidate()
        return doc
    try:
        _index_content(db, doc, path.read_bytes())
    except ExtractionError as exc:
        db.rollback()
        doc = db.get(Document, doc.id)
        doc.status, doc.error = "failed", str(exc)[:500]
    db.commit()
    rag_index.invalidate()
    return doc


def delete_document(db: Session, doc: Document) -> None:
    path = _upload_dir() / doc.stored_name
    db.delete(doc)                                          # ORM cascade removes chunks
    db.commit()
    path.unlink(missing_ok=True)
    rag_index.invalidate()
    log.info("document deleted id=%s", doc.id)


def distinct_values(db: Session, user: User) -> dict[str, list[str]]:
    docs = list_documents(db, user)
    return {"categories": sorted({d.category for d in docs}), "departments": sorted({d.department for d in docs})}
