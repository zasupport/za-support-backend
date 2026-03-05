"""
Database engine, session factory, and dependency injection.
Engine is created lazily on first use (not at import time).
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

Base = declarative_base()

_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        url = settings.database_url_sync
        if not url:
            raise RuntimeError("DATABASE_URL not set")
        _engine = create_engine(
            url, pool_size=10, max_overflow=20,
            pool_pre_ping=True, pool_recycle=300,
        )
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            autocommit=False, autoflush=False, bind=get_engine()
        )
    return _session_factory


def get_db():
    """FastAPI dependency — yields a DB session, auto-closes."""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()
