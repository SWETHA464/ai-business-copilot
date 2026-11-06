from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import Report, User
from app.schemas.reports import ReportDetail, ReportRequest, ReportSummary
from app.security.auth import get_current_user
from app.security.rate_limit import general_limit
from app.services import report_service as svc
from app.utils.logging import get_logger

router = APIRouter(prefix="/api/reports", tags=["reports"], dependencies=[Depends(general_limit)])
log = get_logger("reports-api")


def _summary(r: Report) -> ReportSummary:
    return ReportSummary(id=r.id, title=r.title, question=r.question, created_at=r.created_at,
                         has_pdf=svc.pdf_path(r) is not None)


def _owned(db: Session, report_id: int, user: User) -> Report:
    r = db.get(Report, report_id)
    if r is None or (r.user_id != user.id and user.role != "admin"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    return r


@router.post("/generate", response_model=ReportDetail, status_code=status.HTTP_201_CREATED)
def generate(body: ReportRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        rep = svc.generate_report(db, user, body.question, allow_external=body.allow_external,
                                  category=body.category, department=body.department)
    except Exception:
        log.exception("report generation failed")
        db.rollback()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "The report could not be generated.")
    return ReportDetail(**_summary(rep).model_dump(), content=rep.content)


@router.get("", response_model=list[ReportSummary])
def list_reports(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Report).where(Report.user_id == user.id).order_by(Report.created_at.desc(), Report.id.desc()))
    return [_summary(r) for r in rows]


@router.get("/{report_id}", response_model=ReportDetail)
def get_report(report_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = _owned(db, report_id, user)
    return ReportDetail(**_summary(r).model_dump(), content=r.content)


@router.get("/{report_id}/download")
def download(report_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = _owned(db, report_id, user)
    path = svc.pdf_path(r)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The PDF file is no longer available")
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", r.title)[:60].strip("_") or "report"
    return FileResponse(path, media_type="application/pdf", filename=f"{safe}.pdf")
