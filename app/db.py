"""Database module with SQLAlchemy engine and session."""
import os
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()

_engine = None
_SessionLocal = None


def get_engine(database_url: str):
    """Create or return existing engine."""
    global _engine
    if _engine is None:
        _engine = create_engine(database_url, pool_pre_ping=True)
    return _engine


def get_session_maker(engine):
    """Create session maker."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return _SessionLocal


def get_db() -> Iterator:
    """Dependency that yields a DB session."""
    global _SessionLocal
    if _SessionLocal is None:
        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql://sentinel:sentinel@localhost:5432/sentinel",
        )
        get_session_maker(get_engine(database_url))
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables declared on Base in the public schema."""
    from app import models  # noqa: F401  (ensure models are registered)

    global _SessionLocal
    if _SessionLocal is None:
        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql://sentinel:sentinel@localhost:5432/sentinel",
        )
        get_session_maker(get_engine(database_url))
    Base.metadata.create_all(bind=_SessionLocal.kw["bind"])
