"""
003_chat.py
────────────
Migration: Chat domain — conversations, message tree, sources, artifacts.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── conversations ────────────────────────────────────────────────────────
    op.create_table(
        "conversations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("study_space_id", UUID(as_uuid=True), sa.ForeignKey("study_spaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("active_message_id", UUID(as_uuid=True), nullable=True),  # no FK — circular; validated in service
        sa.Column("is_pinned", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_archived", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        # Analytics
        sa.Column("total_messages", sa.Integer, nullable=False, server_default="0"),
        sa.Column("session_mood", sa.String(30), nullable=True),
        sa.Column("bloom_levels_hit", JSONB, nullable=True),
        sa.Column("topics_covered", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("last_topic_name", sa.String(300), nullable=True),
        sa.Column("memory_summary", sa.Text, nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_duration_sec", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_conversations_user_id", "conversations", ["user_id"])
    op.create_index("idx_conversations_subject_id", "conversations", ["subject_id"])
    op.create_index("idx_conversations_created_at", "conversations", ["created_at"])

    # ── messages ─────────────────────────────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("conversation_id", UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_message_id", UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active_branch", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("idempotency_key", sa.String(64), nullable=True, unique=True),
        # Analytics
        sa.Column("response_time_ms", sa.Integer, nullable=True),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column("sentiment", sa.String(20), nullable=True),
        sa.Column("bloom_level", sa.String(30), nullable=True),
        sa.Column("contains_question", sa.Boolean, nullable=True),
        sa.Column("topic_id", sa.Integer, sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("role IN ('student', 'assistant', 'system')", name="ck_messages_role"),
    )
    op.create_index("idx_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("idx_messages_parent_id", "messages", ["parent_message_id"])
    op.create_index("idx_messages_created_at", "messages", ["created_at"])

    # ── message_content_blocks ────────────────────────────────────────────────
    op.create_table(
        "message_content_blocks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("message_id", UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("block_type", sa.String(20), nullable=False, server_default="text"),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("block_index", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("message_id", "block_index", name="uq_msg_blocks_msg_index"),
        sa.CheckConstraint(
            "block_type IN ('text','code','image','citation','artifact_ref','tool_use','tool_result')",
            name="ck_msg_block_type",
        ),
    )
    op.create_index("idx_msg_content_blocks_message_id", "message_content_blocks", ["message_id"])

    # ── message_sources ───────────────────────────────────────────────────────
    op.create_table(
        "message_sources",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("message_id", UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("block_id", sa.Integer, sa.ForeignKey("content_blocks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rank", sa.SmallInteger, nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("used_in_answer", sa.Boolean, nullable=False, server_default="true"),
        sa.UniqueConstraint("message_id", "block_id", name="uq_msg_sources_msg_block"),
        sa.CheckConstraint("score BETWEEN 0.0 AND 1.0", name="ck_msg_sources_score"),
    )
    op.create_index("idx_msg_sources_message_id", "message_sources", ["message_id"])
    op.create_index("idx_msg_sources_block_id", "message_sources", ["block_id"])

    # ── artifacts ─────────────────────────────────────────────────────────────
    op.create_table(
        "artifacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("artifact_type", sa.String(30), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("current_version_id", UUID(as_uuid=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "artifact_type IN ('notes','flashcards','mindmap','practice_set')",
            name="ck_artifact_type",
        ),
    )
    op.create_index("idx_artifacts_user_id", "artifacts", ["user_id"])

    # ── artifact_versions ─────────────────────────────────────────────────────
    op.create_table(
        "artifact_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("artifact_id", UUID(as_uuid=True), sa.ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_num", sa.Integer, nullable=False),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("artifact_id", "version_num", name="uq_artifact_versions"),
    )
    op.create_index("idx_artifact_versions_artifact_id", "artifact_versions", ["artifact_id"])

    # ── share_links ───────────────────────────────────────────────────────────
    op.create_table(
        "share_links",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("conversation_id", UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("snapshot", JSONB, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_share_links_conversation_id", "share_links", ["conversation_id"])
    op.create_index("idx_share_links_token", "share_links", ["token"])

    # ── message_feedback ──────────────────────────────────────────────────────
    op.create_table(
        "message_feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("message_id", UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rating", sa.SmallInteger, nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("message_id", "user_id", name="uq_msg_feedback_msg_user"),
        sa.CheckConstraint("rating IN (-1, 0, 1)", name="ck_msg_feedback_rating"),
    )
    op.create_index("idx_msg_feedback_message_id", "message_feedback", ["message_id"])

    # ── tool_call_log ─────────────────────────────────────────────────────────
    op.create_table(
        "tool_call_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("message_id", UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("input", JSONB, nullable=True),
        sa.Column("output", JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_tool_call_log_message_id", "tool_call_log", ["message_id"])


def downgrade() -> None:
    op.drop_table("tool_call_log")
    op.drop_table("message_feedback")
    op.drop_table("share_links")
    op.drop_table("artifact_versions")
    op.drop_table("artifacts")
    op.drop_table("message_sources")
    op.drop_table("message_content_blocks")
    op.drop_table("messages")
    op.drop_table("conversations")
