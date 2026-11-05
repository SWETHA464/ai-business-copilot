"""Create (or promote) the initial admin account. No credentials are hardcoded.

Reads ADMIN_EMAIL / ADMIN_PASSWORD from the environment or .env; prompts for the password if empty.
Usage (from repo root):  python scripts/create_admin.py
"""
import _bootstrap  # noqa: F401

import getpass
import re

from sqlalchemy import select

from app.config import get_settings
from app.database.session import Base, SessionLocal, engine
from app.models import User
from app.security.auth import hash_password
import app.models  # noqa: F401,E402


def main() -> None:
    s = get_settings()
    Base.metadata.create_all(engine)
    email = (s.admin_email or "").strip().lower()
    password = s.admin_password or getpass.getpass(f"Password for admin {email}: ")
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise SystemExit("Password must be at least 8 characters and contain a letter and a digit.")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user:
            user.role, user.is_active = "admin", True
            user.hashed_password = hash_password(password)
            print(f"Updated existing user {email} to admin.")
        else:
            db.add(User(email=email, full_name="Administrator", hashed_password=hash_password(password), role="admin"))
            print(f"Created admin {email}.")
        db.commit()


if __name__ == "__main__":
    main()
