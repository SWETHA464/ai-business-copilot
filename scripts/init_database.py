"""Create all tables. Works for SQLite (default) and MySQL.

Usage (from repo root):  python scripts/init_database.py
"""
import _bootstrap  # noqa: F401

from app.config import get_settings
from app.database.session import Base, engine
import app.models  # noqa: F401


def main() -> None:
    s = get_settings()
    Base.metadata.create_all(engine)
    dialect = engine.dialect.name
    print(f"Tables created on {dialect} database.")
    if dialect == "mysql":
        print("Next: run docs/mysql_setup.sql as a MySQL admin to create the read-only user,")
        print("then set READONLY_DATABASE_URL in .env.")
    elif not s.readonly_database_url:
        print("SQLite: the SQL agent will open the same file in read-only mode automatically.")


if __name__ == "__main__":
    main()
