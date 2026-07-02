"""
core/db_session.py
──────────────────
Context managers and decorators for clean database session handling.
"""

from contextlib import contextmanager
from db.database import SessionLocal

@contextmanager
def managed_session():
    """
    Context manager that provides a database session with proper rollback on error.
    
    Usage:
        with managed_session() as db:
            result = db.query(Model).all()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
