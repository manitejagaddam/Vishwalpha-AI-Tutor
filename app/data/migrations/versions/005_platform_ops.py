"""
005_platform_ops.py
────────────────────
Migration: Platform operations — LLM call logs, usage ledger, job queue, prompt templates.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── llm_call_logs ─────────────────────────────────────────────────────────
    op.create_table(
        "llm_call_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("conversation_id", UUID(as_uuid=True), nullable=True),  # no FK — survives conversation deletion
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("deployment", sa.String(100), nullable=False),
        sa.Column("prompt_template", sa.String(100), nullable=True, server_default="ad_hoc"),
        sa.Column("prompt_version", sa.Integer, nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("input_tokens >= 0", name="ck_llm_input_tokens"),
        sa.CheckConstraint("output_tokens >= 0", name="ck_llm_output_tokens"),
        sa.CheckConstraint("cost_usd >= 0.0", name="ck_llm_cost"),
    )
    op.create_index("idx_llm_logs_user_id", "llm_call_logs", ["user_id"])
    op.create_index("idx_llm_logs_created_at", "llm_call_logs", ["created_at"])
    op.create_index("idx_llm_logs_model", "llm_call_logs", ["model"])

    # ── usage_ledger ──────────────────────────────────────────────────────────
    op.create_table(
        "usage_ledger",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("messages_sent", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_input", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_output", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0.0"),
        sa.UniqueConstraint("user_id", "date", name="uq_usage_ledger_user_date"),
    )
    op.create_index("idx_usage_ledger_user_id", "usage_ledger", ["user_id"])
    op.create_index("idx_usage_ledger_date", "usage_ledger", ["date"])

    # ── job_queue ─────────────────────────────────────────────────────────────
    op.create_table(
        "job_queue",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="10"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending','running','done','failed','cancelled')", name="ck_job_status"),
        sa.CheckConstraint("priority >= 0", name="ck_job_priority"),
        sa.CheckConstraint("attempts >= 0", name="ck_job_attempts"),
    )
    op.create_index("idx_job_queue_status_priority", "job_queue", ["status", "priority"])
    op.create_index("idx_job_queue_created_at", "job_queue", ["created_at"])

    # ── prompt_templates ──────────────────────────────────────────────────────
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("template", sa.Text, nullable=False),
        sa.Column("slots", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("name", "version", name="uq_prompt_templates_name_version"),
    )
    op.create_index("idx_prompt_templates_name", "prompt_templates", ["name"])
    op.create_index("idx_prompt_templates_is_active", "prompt_templates", ["is_active"])


def downgrade() -> None:
    op.drop_table("prompt_templates")
    op.drop_table("job_queue")
    op.drop_table("usage_ledger")
    op.drop_table("llm_call_logs")
