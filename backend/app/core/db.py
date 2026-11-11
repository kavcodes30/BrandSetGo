from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _fk_pragma(dbapi_conn, _record):  # pragma: no cover - driver hook
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added after the first release. SQLite cannot ALTER a table's types but
# it can add a column, which is all an upgrade needs here.
_ADDED_COLUMNS = {
    "agent_findings": {
        "source": "VARCHAR(16) DEFAULT 'deterministic'",
        "guideline_code": "VARCHAR(40) DEFAULT ''",
        "guideline_title": "VARCHAR(240) DEFAULT ''",
        "guideline_authority": "VARCHAR(240) DEFAULT ''",
        "guideline_citation": "VARCHAR(240) DEFAULT ''",
        "legal_basis": "TEXT DEFAULT ''",
        "remediation": "TEXT DEFAULT ''",
        "timecode_start": "FLOAT",
        "timecode_end": "FLOAT",
    },
    "review_runs": {
        "classification": "JSON",
        "ai_meta": "JSON",
        "modality": "VARCHAR(24) DEFAULT 'text'",
    },
    "ai_disclosures": {"calls": "INTEGER DEFAULT 0", "latency_ms": "INTEGER DEFAULT 0"},
    "users": {
        "token_version": "INTEGER DEFAULT 1",
        "password_hash": "VARCHAR(255) DEFAULT ''",
        "account_type": "VARCHAR(16) DEFAULT 'business'",
        "platform_role": "VARCHAR(16)",
        "status": "VARCHAR(16) DEFAULT 'active'",
        "last_login_at": "DATETIME",
    },
    "organizations": {
        "account_type": "VARCHAR(16) DEFAULT 'business'",
        "status": "VARCHAR(16) DEFAULT 'active'",
        "seats": "INTEGER DEFAULT 1",
        "created_by": "VARCHAR(32)",
        "billing_email": "VARCHAR(200) DEFAULT ''",
    },
    "brands": {"owner_user_id": "VARCHAR(32)", "is_personal": "BOOLEAN DEFAULT 0"},
    "content_versions": {"transcript": "JSON", "duration_s": "FLOAT DEFAULT 0"},
}


def _upgrade_schema() -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_db() -> None:
    from app import models  # noqa: F401  (register metadata)

    Base.metadata.create_all(bind=engine)
    _upgrade_schema()
