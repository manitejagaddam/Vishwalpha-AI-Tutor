"""
app/data/models/platform_ops.py
────────────────────────────────
Platform operations models: LLM call logging, usage ledger, job queue, prompt templates.

Design decisions:
  - LLMCallLog: partitioned by month (via application-level + pg_partman later);
    for now, just a regular table with a strong date index.
  - UsageLedger: one row per (user, date) — upserted with ON CONFLICT.
  - JobQueue: simple Postgres-backed job queue; can be replaced with
    Redis Streams worker later without schema changes.
  - PromptTemplate: versioned prompt templates stored in DB for hot-swapping.
"""
import uuid
from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Date, Text, Float,
    ForeignKey, UniqueConstraint, Index, CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.data.models.base import Base


class ABExperiment(Base):
    """
    Configuration for A/B prompt experiments.
    Determines which variant of a prompt a user sees based on deterministic hashing.
    """
    __tablename__ = "ab_experiments"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    name               = Column(String(100), nullable=False, unique=True, index=True)
    variant_a_template = Column(Text, nullable=False)
    variant_b_template = Column(Text, nullable=False)
    traffic_split      = Column(Integer, nullable=False, default=50) # % assigned to variant A
    is_active          = Column(Boolean, nullable=False, default=True)
    created_at         = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at         = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class LLMCallLog(Base):
    """
    Audit record for every LLM API call made by the backend.

    model: 'gpt-4.1-mini' | 'text-embedding-3-small'
    deployment: the Azure deployment name
    prompt_template: name of the PromptTemplate used (or 'ad_hoc')
    prompt_version: version of the template
    input_tokens / output_tokens: from the API response usage field
    cost_usd: calculated at log time using the pricing table in config
    duration_ms: end-to-end latency including network
    """
    __tablename__ = "llm_call_logs"
    __table_args__ = (
        Index("idx_llm_logs_user_id", "user_id"),
        Index("idx_llm_logs_created_at", "created_at"),
        Index("idx_llm_logs_model", "model"),
        CheckConstraint("input_tokens >= 0", name="ck_llm_input_tokens"),
        CheckConstraint("output_tokens >= 0", name="ck_llm_output_tokens"),
        CheckConstraint("cost_usd >= 0.0", name="ck_llm_cost"),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    user_id         = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    conversation_id = Column(UUID(as_uuid=True), nullable=True)   # no FK — logs survive conversation deletion
    model           = Column(String(100), nullable=False)
    deployment      = Column(String(100), nullable=False)
    prompt_template = Column(String(100), nullable=True, default="ad_hoc")
    prompt_version  = Column(Integer, nullable=True)
    ab_experiment_id= Column(Integer, ForeignKey("ab_experiments.id", ondelete="SET NULL"), nullable=True)
    input_tokens    = Column(Integer, nullable=False, default=0)
    output_tokens   = Column(Integer, nullable=False, default=0)
    cost_usd        = Column(Float, nullable=False, default=0.0)
    duration_ms     = Column(Integer, nullable=True)
    created_at      = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class UsageLedger(Base):
    """
    Daily usage summary per user.
    UNIQUE(user_id, date) — upserted after each LLM call.
    Used for per-user quota checks and cost dashboards.
    """
    __tablename__ = "usage_ledger"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_usage_ledger_user_date"),
        Index("idx_usage_ledger_user_id", "user_id"),
        Index("idx_usage_ledger_date", "date"),
    )

    id             = Column(Integer, primary_key=True, autoincrement=True)
    user_id        = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    date           = Column(Date, nullable=False)
    messages_sent  = Column(Integer, nullable=False, default=0)
    tokens_input   = Column(Integer, nullable=False, default=0)
    tokens_output  = Column(Integer, nullable=False, default=0)
    cost_usd       = Column(Float, nullable=False, default=0.0)

    user = relationship("User")


class JobQueue(Base):
    """
    Postgres-backed job queue for async background tasks.
    Status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
    priority: lower number = higher priority (default 10)
    payload: JSONB with job-specific data
    error: filled in on failure
    """
    __tablename__ = "job_queue"
    __table_args__ = (
        Index("idx_job_queue_status_priority", "status", "priority"),
        Index("idx_job_queue_created_at", "created_at"),
        CheckConstraint(
            "status IN ('pending','running','done','failed','cancelled')",
            name="ck_job_status",
        ),
        CheckConstraint("priority >= 0", name="ck_job_priority"),
        CheckConstraint("attempts >= 0", name="ck_job_attempts"),
    )

    id          = Column(Integer, primary_key=True, autoincrement=True)
    job_type    = Column(String(100), nullable=False)
    payload     = Column(JSONB, nullable=False)
    status      = Column(String(20), nullable=False, default="pending")
    priority    = Column(Integer, nullable=False, default=10)
    attempts    = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    error       = Column(Text, nullable=True)
    created_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at  = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class PromptTemplate(Base):
    """
    Versioned prompt templates stored in DB for hot-swapping without redeploy.
    name: unique template identifier (e.g. 'tutor_system_v2')
    version: monotonically increasing integer
    template: the prompt string with {slot} placeholders
    slots: JSONB list of required slot names
    is_active: only one version per name should be active at a time
    """
    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_prompt_templates_name_version"),
        Index("idx_prompt_templates_name", "name"),
        Index("idx_prompt_templates_is_active", "is_active"),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    name       = Column(String(100), nullable=False)
    version    = Column(Integer, nullable=False, default=1)
    template   = Column(Text, nullable=False)
    slots      = Column(JSONB, nullable=False, default=list)
    is_active  = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
