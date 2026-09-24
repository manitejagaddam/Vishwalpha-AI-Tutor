"""
app/data/migrations/env.py
───────────────────────────
Alembic environment — reads DATABASE_URL from app.config.settings.
Supports both offline (SQL dump) and online (direct connection) migration modes.
"""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# ── Make sure the project root is on sys.path ─────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

# ── Import our settings and ALL models so autogenerate can see them ───────────
from app.config import settings  # noqa: E402
from app.data.models import Base  # noqa: E402 — imports all domain models

# ── Alembic Config object ─────────────────────────────────────────────────────
config = context.config

# Set URL from our settings (overrides the blank sqlalchemy.url in alembic.ini)
_db_url = settings.DATABASE_URL
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)
# Escape '%' to '%%' because configparser uses '%' for interpolation
config.set_main_option("sqlalchemy.url", _db_url.replace("%", "%%"))

# Set up Python logging from alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Use our Base.metadata for autogenerate ────────────────────────────────────
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode — generates SQL to stdout/file.
    Does NOT connect to the database.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode — connects directly to the database.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
