from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings

from .models import Base

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None


def _sqlite_path_from_url(url: str) -> Path | None:
    if url.startswith("sqlite:///"):
        return Path(url.replace("sqlite:///", "", 1))
    return None


def init_db() -> None:
    global _engine, _SessionLocal
    settings = get_settings()
    path = _sqlite_path_from_url(settings.database_url)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
    connect_args = (
        {"check_same_thread": False, "timeout": 30}
        if settings.database_url.startswith("sqlite")
        else {}
    )
    _engine = create_engine(settings.database_url, connect_args=connect_args)

    if settings.database_url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _sqlite_wal(dbapi_connection, connection_record):  # type: ignore
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    Base.metadata.create_all(bind=_engine)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    logger.info("Database initialized at %s", settings.database_url)


def get_engine():
    if _engine is None:
        init_db()
    return _engine


def session_scope() -> Session:
    if _SessionLocal is None:
        init_db()
    return _SessionLocal()
