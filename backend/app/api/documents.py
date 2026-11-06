from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.session import get_db
from app.models import Document, DocumentChunk, User
from app.rag import index as rag_index
from app.rag.extract import ExtractionError
from app.rag.retrieval import RetrievalConfig, retrieve
from app.schemas.documents import (
    DocumentDetail, DocumentMetaUpdate, DocumentOut, DocumentSearchRequest, DocumentSearchResponse,
    FilterOptions, SearchHitOut,
)
from app.security.auth import get_current_user, require_admin
from app.security.rate_limit import general_limit
from app.services import document_service as svc

router = APIRouter(prefix="/api/documents", tags=["documents"], dependencies=[Depends(general_limit)])


def _out(doc: Document, user: User) -> DocumentOut:
    return DocumentOut(id=doc.id, filename=doc.filename, file_type=doc.file_type, size_bytes=doc.size_bytes,
                       category=doc.category, department=doc.department, visibility=doc.visibility,
                       status=doc.status, error=doc.error, page_count=doc.page_count,
                       chunk_count=doc.chunk_count, created_at=doc.created_at, owner_id=doc.owner_id,
                       can_modify=svc.can_modify(doc, user))


def _get_or_404(db: Session, doc_id: int, user: User) -> Document:
    doc = svc.get_visible_document(db, doc_id, user)
    if doc is None:  # same response for "missing" and "not yours": no information leak
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


def _get_modifiable(db: Session, doc_id: int, user: User) -> Document:
    doc = _get_or_404(db, doc_id, user)
    if not svc.can_modify(doc, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only modify your own documents")
    return doc


async def _read_upload(file: UploadFile) -> bytes:
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"File exceeds the {get_settings().max_upload_mb} MB limit")
    return data


@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload(file: UploadFile = File(...), category: str = Form("general"), department: str = Form("general"),
                 visibility: str = Form("shared"), db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)) -> DocumentOut:
    data = await _read_upload(file)
    try:
        doc = svc.ingest_bytes(db, user, file.filename or "document", data, category=category.strip() or "general",
                               department=department.strip() or "general", visibility=visibility)
    except svc.DuplicateDocument as dup:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"This file was already uploaded as '{dup.existing.filename}' (id {dup.existing.id}).")
    except svc.DocumentTooLarge as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc))
    except ExtractionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return _out(doc, user)


@router.get("", response_model=list[DocumentOut])
def list_docs(q: str | None = Query(default=None, max_length=100), category: str | None = None,
              department: str | None = None, doc_status: str | None = Query(default=None, alias="status"),
              db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[DocumentOut]:
    return [_out(d, user) for d in svc.list_documents(db, user, q=q, category=category, department=department,
                                                      status=doc_status)]


@router.get("/filters", response_model=FilterOptions)
def filters(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> FilterOptions:
    return FilterOptions(**svc.distinct_values(db, user))


@router.post("/search", response_model=DocumentSearchResponse)
def search(body: DocumentSearchRequest, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)) -> DocumentSearchResponse:
    cfg = RetrievalConfig.from_settings()
    cfg.top_k = body.top_k
    res = retrieve(db, body.query, user, config=cfg, category=body.category, department=body.department)
    return DocumentSearchResponse(
        query=body.query, sufficient_evidence=res.sufficient, queries_used=res.queries, timings_ms=res.timings_ms,
        hits=[SearchHitOut(document_id=h.document_id, filename=h.filename, page=h.page, category=h.category,
                           score=round(h.score, 4), snippet=(h.compressed or h.text)[:400]) for h in res.hits])


@router.post("/rebuild-index")
def rebuild_index(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    rag_index.rebuild_index(db)
    return rag_index.verify_consistency(db)


@router.get("/{document_id}", response_model=DocumentDetail)
def get_doc(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = _get_or_404(db, document_id, user)
    first = db.scalar(select(DocumentChunk.text).where(DocumentChunk.document_id == doc.id)
                      .order_by(DocumentChunk.chunk_index).limit(1))
    return DocumentDetail(**_out(doc, user).model_dump(), preview=(first or "")[:500])


@router.patch("/{document_id}", response_model=DocumentOut)
def update_meta(document_id: int, body: DocumentMetaUpdate, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> DocumentOut:
    doc = _get_modifiable(db, document_id, user)
    for field in ("category", "department", "visibility"):
        value = getattr(body, field)
        if value is not None:
            setattr(doc, field, value.strip())
    db.commit()
    rag_index.invalidate()
    return _out(doc, user)


@router.put("/{document_id}/content", response_model=DocumentOut)
async def replace(document_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)) -> DocumentOut:
    doc = _get_modifiable(db, document_id, user)
    data = await _read_upload(file)
    try:
        doc = svc.replace_content(db, doc, file.filename or doc.filename, data)
    except svc.DuplicateDocument as dup:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Identical content already exists (id {dup.existing.id}).")
    except ExtractionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return _out(doc, user)


@router.post("/{document_id}/reindex", response_model=DocumentOut)
def reindex(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = _get_modifiable(db, document_id, user)
    return _out(svc.reindex_document(db, doc), user)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    doc = _get_modifiable(db, document_id, user)
    svc.delete_document(db, doc)
