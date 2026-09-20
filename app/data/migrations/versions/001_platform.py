"""
001_platform.py
────────────────
Migration: Platform tables — users, user_sessions, audit_log.

up:   Create tables, indexes, constraints; enable pgcrypto extension.
down: Drop tables in reverse dependency order.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Extensions ─────────────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── users ──────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column("email", sa.String(200), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(500), nullable=False),
        sa.Column("class_num", sa.Integer, nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="student"),
        sa.Column("onboarding_complete", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("class_num BETWEEN 6 AND 12", name="ck_users_class_num"),
        sa.CheckConstraint("role IN ('student', 'admin')", name="ck_users_role"),
    )
    op.create_index("idx_users_email", "users", ["email"])
    op.create_index("idx_users_username", "users", ["username"])

    # ── user_sessions ─────────────────────────────────────────────────────────
    op.create_table(
        "user_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("idx_user_sessions_token_hash", "user_sessions", ["refresh_token_hash"])

    # ── audit_log ─────────────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("table_name", sa.String(100), nullable=True),
        sa.Column("record_id", sa.String(100), nullable=True),
        sa.Column("diff", JSONB, nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("idx_audit_log_created_at", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("user_sessions")
    op.drop_table("users")
