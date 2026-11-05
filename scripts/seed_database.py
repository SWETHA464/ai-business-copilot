"""Create tables, load the synthetic dataset and generate the sample business documents.

Usage (from repo root):  python scripts/seed_database.py [--seed 42] [--no-documents]
Re-running resets the business tables (customers..payments) and regenerates the documents.
"""
import _bootstrap  # noqa: F401

import argparse
from pathlib import Path

from app.config import DATA_DIR
from app.database.session import Base, SessionLocal, engine
from app.services import analytics_service as A
from app.services.sample_documents import generate_sample_documents
from app.services.seed_data import generate_dataset, insert_dataset
import app.models  # noqa: F401,E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-documents", action="store_true")
    args = ap.parse_args()

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        counts = insert_dataset(db, generate_dataset(args.seed))
    print("Inserted:", counts)

    if not args.no_documents:
        with engine.connect() as conn:
            sales, customers, payments = A.load_frames(conn)
        out = Path(DATA_DIR) / "documents"
        manifest = generate_sample_documents(out, sales, customers, payments)
        print(f"Wrote {len(manifest)} sample documents to {out}")
        print("Documents are registered and indexed by `python scripts/index_documents.py` (needs an admin user).")


if __name__ == "__main__":
    main()
