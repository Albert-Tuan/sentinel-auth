"""Database module with SQLAlchemy engine and session."""
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


def get_db():
    """Dependency that yields a DB session."""
    pass


def init_db():
    """Initialize all tables in public schema."""
    pass
