"""
004_learning.py
────────────────
Migration: Adaptive learning domain — all cognitive, mastery, quiz, memory tables.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── student_profiles (1:1 with users) ────────────────────────────────────
    op.create_table(
        "student_profiles",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("board_id", sa.Integer, sa.ForeignKey("boards.id", ondelete="SET NULL"), nullable=True),
        sa.Column("preferred_lang", sa.String(10), nullable=False, server_default="en"),
        sa.Column("learning_style", sa.String(50), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── student_subject_profiles ──────────────────────────────────────────────
    op.create_table(
        "student_subject_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        # Core 10 metrics
        sa.Column("concept_master_score", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("error_repetition_rate", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("attempt_persistence", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("struggle_recovery_rate", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("practice_intensity", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("learning_velocity", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("knowledge_retention", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("cognitive_thinking_level", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("engagement_frequency", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("assessment_accuracy", sa.Float, nullable=False, server_default="50.0"),
        # Extended metrics
        sa.Column("bloom_level_avg", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("frustration_index", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("confidence_index", sa.Float, nullable=False, server_default="50.0"),
        # Counters
        sa.Column("total_chat_turns", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_quizzes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_session_duration_min", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "subject_id", name="uq_subject_profiles_user_subject"),
        sa.CheckConstraint("concept_master_score BETWEEN 0 AND 100", name="ck_ssp_cms"),
        sa.CheckConstraint("error_repetition_rate BETWEEN 0.0 AND 1.0", name="ck_ssp_err"),
        sa.CheckConstraint("attempt_persistence BETWEEN 0 AND 100", name="ck_ssp_ap"),
        sa.CheckConstraint("struggle_recovery_rate BETWEEN 0 AND 100", name="ck_ssp_srr"),
        sa.CheckConstraint("practice_intensity BETWEEN 0 AND 100", name="ck_ssp_pi"),
        sa.CheckConstraint("learning_velocity BETWEEN 0 AND 100", name="ck_ssp_lv"),
        sa.CheckConstraint("knowledge_retention BETWEEN 0 AND 100", name="ck_ssp_kr"),
        sa.CheckConstraint("cognitive_thinking_level BETWEEN 0 AND 100", name="ck_ssp_ctl"),
        sa.CheckConstraint("engagement_frequency BETWEEN 0 AND 100", name="ck_ssp_ef"),
        sa.CheckConstraint("assessment_accuracy BETWEEN 0 AND 100", name="ck_ssp_aa"),
        sa.CheckConstraint("bloom_level_avg BETWEEN 1.0 AND 6.0", name="ck_ssp_bla"),
        sa.CheckConstraint("frustration_index BETWEEN 0 AND 100", name="ck_ssp_fi"),
        sa.CheckConstraint("confidence_index BETWEEN 0 AND 100", name="ck_ssp_ci"),
    )
    op.create_index("idx_subject_profiles_user_id", "student_subject_profiles", ["user_id"])

    # ── overall_cognitive_profiles (1:1 with users) ───────────────────────────
    op.create_table(
        "overall_cognitive_profiles",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("concept_master_score", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("error_repetition_rate", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("attempt_persistence", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("struggle_recovery_rate", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("practice_intensity", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("learning_velocity", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("knowledge_retention", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("cognitive_thinking_level", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("engagement_frequency", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("assessment_accuracy", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("concept_master_score BETWEEN 0 AND 100", name="ck_ocp_cms"),
        sa.CheckConstraint("error_repetition_rate BETWEEN 0.0 AND 1.0", name="ck_ocp_err"),
    )

    # ── cognitive_metric_history ──────────────────────────────────────────────
    op.create_table(
        "cognitive_metric_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("metric_name", sa.String(60), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_cmh_user_subject", "cognitive_metric_history", ["user_id", "subject_id"])
    op.create_index("idx_cmh_recorded_at", "cognitive_metric_history", ["recorded_at"])

    # ── learning_preferences (1:1 with users) ────────────────────────────────
    op.create_table(
        "learning_preferences",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("prefers_examples", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("prefers_analogies", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("prefers_step_by_step", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("prefers_visuals", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("preferred_length", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("attention_span", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("responds_to_encouragement", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("ai_detected_notes", JSONB, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("prefers_examples BETWEEN 0.0 AND 1.0", name="ck_lp_examples"),
        sa.CheckConstraint("prefers_analogies BETWEEN 0.0 AND 1.0", name="ck_lp_analogies"),
        sa.CheckConstraint("prefers_step_by_step BETWEEN 0.0 AND 1.0", name="ck_lp_step"),
        sa.CheckConstraint("prefers_visuals BETWEEN 0.0 AND 1.0", name="ck_lp_visuals"),
        sa.CheckConstraint("attention_span BETWEEN 0.0 AND 100.0", name="ck_lp_attn"),
        sa.CheckConstraint("responds_to_encouragement BETWEEN 0.0 AND 1.0", name="ck_lp_enc"),
        sa.CheckConstraint("preferred_length IN ('short','medium','detailed')", name="ck_lp_length"),
    )

    # ── student_memory_items ──────────────────────────────────────────────────
    op.create_table(
        "student_memory_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_message_id", UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("fact", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_memory_items_user_subject", "student_memory_items", ["user_id", "subject_id"])
    op.create_index("idx_memory_items_is_active", "student_memory_items", ["is_active"])

    # ── topic_mastery ─────────────────────────────────────────────────────────
    op.create_table(
        "topic_mastery",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", sa.Integer, sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mastery_level", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("bloom_level_reached", sa.SmallInteger, nullable=False, server_default="1"),
        sa.Column("times_visited", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_visited", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_visited", sa.DateTime(timezone=True), nullable=True),
        sa.Column("understood_concepts", JSONB, nullable=True, server_default=sa.text("'[]'::jsonb")),
        sa.Column("confused_concepts", JSONB, nullable=True, server_default=sa.text("'[]'::jsonb")),
        sa.Column("common_mistakes", JSONB, nullable=True, server_default=sa.text("'[]'::jsonb")),
        sa.Column("required_backtrack", sa.Boolean, nullable=True),
        sa.Column("backtrack_depth", sa.Integer, nullable=True),
        sa.Column("backtrack_class", sa.Integer, nullable=True),
        sa.Column("next_review_date", sa.Date, nullable=True),
        sa.Column("review_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("decay_rate", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("last_quiz_score", sa.Float, nullable=True),
        sa.Column("confidence", sa.Float, nullable=False, server_default="50.0"),
        sa.UniqueConstraint("user_id", "topic_id", name="uq_topic_mastery_user_topic"),
        sa.CheckConstraint("mastery_level BETWEEN 0 AND 100", name="ck_tm_mastery"),
        sa.CheckConstraint("bloom_level_reached BETWEEN 1 AND 6", name="ck_tm_bloom"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_tm_confidence"),
        sa.CheckConstraint("decay_rate BETWEEN 0.0 AND 1.0", name="ck_tm_decay"),
    )
    op.create_index("idx_topic_mastery_user_id", "topic_mastery", ["user_id"])
    op.create_index("idx_topic_mastery_next_review", "topic_mastery", ["next_review_date"])

    # ── mastery_events ────────────────────────────────────────────────────────
    op.create_table(
        "mastery_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("mastery_id", sa.Integer, sa.ForeignKey("topic_mastery.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", sa.Integer, sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("delta", sa.Float, nullable=False),
        sa.Column("new_value", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("source IN ('chat','quiz','decay','manual')", name="ck_mastery_event_source"),
    )
    op.create_index("idx_mastery_events_mastery_id", "mastery_events", ["mastery_id"])
    op.create_index("idx_mastery_events_created_at", "mastery_events", ["created_at"])

    # ── topic_prerequisites ───────────────────────────────────────────────────
    op.create_table(
        "topic_prerequisites",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("topic_id", sa.Integer, sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prereq_topic_id", sa.Integer, sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True),
        sa.Column("prereq_class_num", sa.Integer, nullable=False),
        sa.Column("prereq_subject_id", sa.Integer, sa.ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("prereq_description", sa.Text, nullable=False),
        sa.Column("difficulty_order", sa.Integer, nullable=True),
        sa.Column("expected_keywords", JSONB, nullable=True),
        sa.Column("source", sa.String(50), nullable=True),
    )
    op.create_index("idx_topic_prereqs_topic_id", "topic_prerequisites", ["topic_id"])

    # ── quiz_attempts ─────────────────────────────────────────────────────────
    op.create_table(
        "quiz_attempts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", sa.Integer, sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True),
        sa.Column("topic", sa.String(300), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("num_questions", sa.Integer, nullable=False, server_default="7"),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column("passed", sa.Boolean, nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("source IN ('mid_concept','yesterday','manual','spaced_review')", name="ck_quiz_source"),
        sa.CheckConstraint("num_questions BETWEEN 1 AND 20", name="ck_quiz_num_q"),
        sa.CheckConstraint("score IS NULL OR score BETWEEN 0 AND 100", name="ck_quiz_score"),
    )
    op.create_index("idx_quiz_attempts_user_id", "quiz_attempts", ["user_id"])
    op.create_index("idx_quiz_attempts_subject_id", "quiz_attempts", ["subject_id"])

    # ── quiz_questions ────────────────────────────────────────────────────────
    op.create_table(
        "quiz_questions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("attempt_id", UUID(as_uuid=True), sa.ForeignKey("quiz_attempts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("q_index", sa.Integer, nullable=False),
        sa.Column("q_type", sa.String(10), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("options", JSONB, nullable=True),
        sa.Column("correct_index", sa.SmallInteger, nullable=True),
        sa.Column("correct_answer", sa.Text, nullable=True),
        sa.Column("explanation", sa.Text, nullable=True),
        sa.Column("student_answer", sa.Text, nullable=True),
        sa.Column("is_correct", sa.Boolean, nullable=True),
        sa.Column("difficulty", sa.String(20), nullable=True),
        sa.Column("bloom_level", sa.String(30), nullable=True),
        sa.Column("time_taken_ms", sa.Integer, nullable=True),
        sa.Column("topic_id", sa.Integer, sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("attempt_id", "q_index", name="uq_quiz_questions_attempt_idx"),
        sa.CheckConstraint("q_type IN ('mcq','theory')", name="ck_qq_type"),
        sa.CheckConstraint("difficulty IS NULL OR difficulty IN ('easy','medium','hard')", name="ck_qq_difficulty"),
        sa.CheckConstraint(
            "bloom_level IS NULL OR bloom_level IN ('remember','understand','apply','analyze','evaluate','create')",
            name="ck_qq_bloom",
        ),
    )
    op.create_index("idx_quiz_questions_attempt_id", "quiz_questions", ["attempt_id"])

    # ── quiz_question_sources ─────────────────────────────────────────────────
    op.create_table(
        "quiz_question_sources",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("question_id", sa.Integer, sa.ForeignKey("quiz_questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("block_id", sa.Integer, sa.ForeignKey("content_blocks.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("question_id", "block_id", name="uq_qq_sources_q_block"),
    )

    # ── subject_quiz_feedback ─────────────────────────────────────────────────
    op.create_table(
        "subject_quiz_feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("total_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_questions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_correct", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_score", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("mcq_accuracy", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("theory_accuracy", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("weak_topics", JSONB, nullable=True, server_default=sa.text("'[]'::jsonb")),
        sa.Column("strong_topics", JSONB, nullable=True, server_default=sa.text("'[]'::jsonb")),
        sa.Column("ai_feedback", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "subject_id", name="uq_sqf_user_subject"),
        sa.CheckConstraint("avg_score IS NULL OR avg_score BETWEEN 0 AND 100", name="ck_sqf_avg"),
    )
    op.create_index("idx_sqf_user_id", "subject_quiz_feedback", ["user_id"])

    # ── session_insights ──────────────────────────────────────────────────────
    op.create_table(
        "session_insights",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("conversation_id", UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("topics_mastered", JSONB, nullable=True, server_default=sa.text("'[]'::jsonb")),
        sa.Column("topics_struggled", JSONB, nullable=True, server_default=sa.text("'[]'::jsonb")),
        sa.Column("misconceptions_found", JSONB, nullable=True, server_default=sa.text("'[]'::jsonb")),
        sa.Column("bloom_levels_achieved", JSONB, nullable=True),
        sa.Column("engagement_rating", sa.Float, nullable=True),
        sa.Column("session_summary", sa.Text, nullable=True),
        sa.Column("recommendations", JSONB, nullable=True, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_session_insights_conversation_id", "session_insights", ["conversation_id"])
    op.create_index("idx_session_insights_user_id", "session_insights", ["user_id"])

    # ── diagnostic_states ─────────────────────────────────────────────────────
    op.create_table(
        "diagnostic_states",
        sa.Column("conversation_id", UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("state", JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── student_goals ─────────────────────────────────────────────────────────
    op.create_table(
        "student_goals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("goal_type", sa.String(50), nullable=False),
        sa.Column("goal_text", sa.Text, nullable=False),
        sa.Column("target_value", sa.Float, nullable=True),
        sa.Column("current_value", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("is_completed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "goal_type IN ('daily_questions','master_topic','improve_score','complete_chapter','custom')",
            name="ck_goal_type",
        ),
    )
    op.create_index("idx_student_goals_user_id", "student_goals", ["user_id"])

    # ── student_streaks (1:1 with users) ──────────────────────────────────────
    op.create_table(
        "student_streaks",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("current_streak_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("longest_streak_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_active_date", sa.Date, nullable=True),
        sa.Column("total_active_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_sessions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_questions_asked", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_quizzes_taken", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("current_streak_days >= 0", name="ck_streak_current"),
        sa.CheckConstraint("longest_streak_days >= 0", name="ck_streak_longest"),
    )

    # ── student_tasks ─────────────────────────────────────────────────────────
    op.create_table(
        "student_tasks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("task", sa.Text, nullable=False),
        sa.Column("is_done", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_student_tasks_user_id", "student_tasks", ["user_id"])

    # ── pending_metric_signals ────────────────────────────────────────────────
    op.create_table(
        "pending_metric_signals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", UUID(as_uuid=True), nullable=True),
        sa.Column("signals", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_pending_signals_user_subject", "pending_metric_signals", ["user_id", "subject_id"])


def downgrade() -> None:
    op.drop_table("pending_metric_signals")
    op.drop_table("student_tasks")
    op.drop_table("student_streaks")
    op.drop_table("student_goals")
    op.drop_table("diagnostic_states")
    op.drop_table("session_insights")
    op.drop_table("subject_quiz_feedback")
    op.drop_table("quiz_question_sources")
    op.drop_table("quiz_questions")
    op.drop_table("quiz_attempts")
    op.drop_table("topic_prerequisites")
    op.drop_table("mastery_events")
    op.drop_table("topic_mastery")
    op.drop_table("student_memory_items")
    op.drop_table("learning_preferences")
    op.drop_table("cognitive_metric_history")
    op.drop_table("overall_cognitive_profiles")
    op.drop_table("student_subject_profiles")
    op.drop_table("student_profiles")
