"""Register the generated sample documents (data/documents) as shared, indexed documents owned by the admin.

Run after seed_database.py and create_admin.py.  Usage (from repo root):  python scripts/index_documents.py
Documents already indexed (same content) are skipped, so the script is safe to re-run.
"""
import _bootstrap  # noqa: F401

import json
from pathlib import Path

from sqlalchemy import select

from app.config import DATA_DIR, get_settings
from app.database.session import Base, SessionLocal, engine
from app.models import User
from app.services import document_service as svc
import app.models  # noqa: F401,E402

CATEGORIES = {
    "Company_Refund_Policy.pdf": ("policy", "support"),
    "Customer_Support_Guidelines.txt": ("policy", "support"),
    "Customer_Retention_Strategy.txt": ("strategy", "marketing"),
    "Marketing_Strategy.txt": ("strategy", "marketing"),
}


def main() -> None:
    Base.metadata.create_all(engine)
    folder = Path(DATA_DIR) / "documents"
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".pdf", ".docx", ".txt", ".csv")) if folder.exists() else []
    if not files:
        raise SystemExit("No documents found. Run `python scripts/seed_database.py` first.")
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == get_settings().admin_email.lower(), User.role == "admin"))
        if admin is None:
            raise SystemExit("Admin user not found. Run `python scripts/create_admin.py` first.")
        for p in files:
            cat, dept = CATEGORIES.get(p.name, ("sales_report", "sales"))
            try:
                doc = svc.ingest_bytes(db, admin, p.name, p.read_bytes(), category=cat, department=dept)
                print(f"indexed {p.name}: {doc.chunk_count} chunks")
            except svc.DuplicateDocument:
                print(f"skipped {p.name} (already indexed)")
    print(json.dumps({"documents": len(files)}))


if __name__ == "__main__":
    main()
