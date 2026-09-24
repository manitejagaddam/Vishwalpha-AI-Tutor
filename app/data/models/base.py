"""
app/data/models/base.py
────────────────────────
Shared SQLAlchemy declarative base and updated_at trigger helper.
All domain model files import Base from here.
"""
from sqlalchemy import Column, DateTime, event
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """
    Declarative base for all VishwAlpha ORM models.

    Every concrete model that inherits from Base gets its metadata
    registered here, which Alembic reads for autogenerate.
    """
    pass


# ── updated_at auto-fill helper ───────────────────────────────────────────────

def _touch_updated_at(mapper, connection, target):
    """SQLAlchemy event listener: sets updated_at on every UPDATE."""
    if hasattr(target, "updated_at"):
        target.updated_at = func.now()


def register_updated_at_listener(model_class):
    """
    Call once per model class that has an `updated_at` column
    to auto-set it on every in-process UPDATE.

    Usage:
        register_updated_at_listener(MyModel)
    """
    event.listen(model_class, "before_update", _touch_updated_at)
