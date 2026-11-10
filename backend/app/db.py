"""Database connection (platform step 2). One engine per process, created on first use."""
from __future__ import annotations

import os
from threading import Lock

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from . import config  # noqa: F401  loads .env (DATABASE_URL) on import

_engine: Engine | None = None
_lock = Lock()


def database_url() -> str | None:
    """DATABASE_URL from .env in SQLAlchemy form, or None when not set (database writes are skipped)."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None
    # .env keeps the plain postgresql:// form (LangGraph uses it as is); SQLAlchemy needs the psycopg 3 driver name.
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def get_engine() -> Engine | None:
    global _engine
    with _lock:
        if _engine is None:
            url = database_url()
            if url:
                _engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
        return _engine


def require_engine() -> Engine:
    """The engine, or a clear error: from stage 2.1 the database is the record, so writes cannot be skipped."""
    engine = get_engine()
    if engine is None:
        raise RuntimeError("DATABASE_URL is not set in .env")
    return engine
