"""
app/data/database.py
─────────────────────
Database engine, session factory, and context manager.
Single file replaces db/database.py + core/db_session.py.
"""
from contextlib import contextmanager
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from app.config import settings
from app.data.models import Base

logger = logging.getLogger(__name__)

# ── Fix Supabase/Heroku postgres:// → postgresql:// ───────────────────────────
_db_url = settings.DATABASE_URL
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    _db_url,
    pool_pre_ping=True,    # reconnects on stale connections
    pool_recycle=1800,     # recycle connections every 30 min
    pool_size=10,          # max persistent connections
    max_overflow=20,       # burst capacity
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ── Context manager (used in services) ───────────────────────────────────────

@contextmanager
def managed_session():
    """
    Yields a transactional DB session. Rolls back on error, always closes.

    Usage:
        with managed_session() as db:
            db.query(Model).all()
    """
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── FastAPI dependency (used in router handlers via Depends) ──────────────────

def get_db():
    """FastAPI dependency that yields a DB session."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── One-time schema initialisation ────────────────────────────────────────────

def init_db() -> None:
    """Creates all tables. Run once manually — NOT on every app startup."""
    logger.info("Initialising database schema...")
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
    except Exception as exc:
        logger.warning(f"pgvector extension already exists or unavailable: {exc}")
    Base.metadata.create_all(bind=engine)
    logger.info("Database schema ready.")
