"""
app/data/models/learning.py
────────────────────────────
Adaptive learning domain ORM models.

Tables:
  StudentProfile            — per-student preferences and board assignment
  StudentSubjectProfile     — 10 cognitive metrics per (student, subject)
  OverallCognitiveProfile   — aggregated cross-subject metrics per student
  CognitiveMetricHistory    — time-series of metric updates (for charts)
  LearningPreference        — AI-detected + student-declared learning style
  StudentMemoryItem         — one durable fact per row (with source message)
  TopicMastery              — per-topic mastery + spaced-rep state
  MasteryEvent              — append-only event log of mastery changes
  TopicPrerequisite         — prerequisite graph edges (cycle-safe at app layer)
  QuizAttempt               — one quiz session
  QuizQuestion              — one question within a quiz
  QuizQuestionSource        — block citations for each quiz question
  SubjectQuizFeedback       — aggregated quiz stats per (student, subject)
  SessionInsight            — AI-generated end-of-session analysis
  DiagnosticState           — in-progress Socratic diagnostic state per conversation
  StudentGoal               — student-set or AI-suggested goals
  StudentStreak             — daily engagement streak
  StudentTask               — assigned study tasks
  PendingMetricSignal       — queued per-turn signals for next batch update

Design decisions:
  - All FKs use `subject_id` (int) — no free-text subject strings.
  - StudentSubjectProfile: UNIQUE(user_id, subject_id) — exactly one row per pair.
  - All 0-100 float metrics have CHECK constraints.
  - TopicMastery: UNIQUE(user_id, topic_id) — one mastery row per pair.
  - StudentMemoryItem: one row per fact (not a JSON blob), with source_message_id for provenance.
  - MasteryEvent: append-only log for audit trail and sparkline charts.
  - QuizQuestion.options: JSONB list — no more TEXT JSON string.
"""
import uuid
from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Date, Text, Float,
    ForeignKey, UniqueConstraint, Index, CheckConstraint, SmallInteger,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.data.models.base import Base, register_updated_at_listener


# ── Student Profile ───────────────────────────────────────────────────────────

class StudentProfile(Base):
    """
    Extended profile for a student: board assignment and learning style.
    1:1 with User — created on registration, filled in during onboarding.
    """
    __tablename__ = "student_profiles"

    user_id             = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    board_id            = Column(Integer, ForeignKey("boards.id", ondelete="SET NULL"), nullable=True)
    preferred_lang      = Column(String(10), nullable=False, default="en")
    learning_style      = Column(String(50), nullable=True)   # visual | auditory | reading | kinesthetic
    updated_at          = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    user  = relationship("User", back_populates="profile")
    board = relationship("Board")


register_updated_at_listener(StudentProfile)


# ── Cognitive Profiles ────────────────────────────────────────────────────────

class StudentSubjectProfile(Base):
    """
    Per-(student, subject) cognitive metrics. 13 metrics total.
    UNIQUE(user_id, subject_id) — exactly one row per pair.

    Metric scales (all 0-100 except error_repetition_rate which is 0.0-1.0):
      concept_master_score    — concept understanding level
      error_repetition_rate   — rate of repeating same mistakes (0.0–1.0)
      attempt_persistence     — willingness to retry after failure
      struggle_recovery_rate  — speed of recovery from confusion
      practice_intensity      — volume and regularity of practice
      learning_velocity       — speed of mastering new concepts
      knowledge_retention     — recall of previously learned material
      cognitive_thinking_level — higher-order thinking (Bloom's)
      engagement_frequency    — active participation level
      assessment_accuracy     — performance on quizzes/tests
      bloom_level_avg         — running average Bloom's level (1.0–6.0)
      frustration_index       — AI-detected frustration (0–100)
      confidence_index        — AI-detected confidence (0–100)

    Update formulas documented in: app/services/learning_engine.py METRIC_FORMULAS
    """
    __tablename__ = "student_subject_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", "subject_id", name="uq_subject_profiles_user_subject"),
        Index("idx_subject_profiles_user_id", "user_id"),
        CheckConstraint("concept_master_score BETWEEN 0 AND 100", name="ck_ssp_cms"),
        CheckConstraint("error_repetition_rate BETWEEN 0.0 AND 1.0", name="ck_ssp_err"),
        CheckConstraint("attempt_persistence BETWEEN 0 AND 100", name="ck_ssp_ap"),
        CheckConstraint("struggle_recovery_rate BETWEEN 0 AND 100", name="ck_ssp_srr"),
        CheckConstraint("practice_intensity BETWEEN 0 AND 100", name="ck_ssp_pi"),
        CheckConstraint("learning_velocity BETWEEN 0 AND 100", name="ck_ssp_lv"),
        CheckConstraint("knowledge_retention BETWEEN 0 AND 100", name="ck_ssp_kr"),
        CheckConstraint("cognitive_thinking_level BETWEEN 0 AND 100", name="ck_ssp_ctl"),
        CheckConstraint("engagement_frequency BETWEEN 0 AND 100", name="ck_ssp_ef"),
        CheckConstraint("assessment_accuracy BETWEEN 0 AND 100", name="ck_ssp_aa"),
        CheckConstraint("bloom_level_avg BETWEEN 1.0 AND 6.0", name="ck_ssp_bla"),
        CheckConstraint("frustration_index BETWEEN 0 AND 100", name="ck_ssp_fi"),
        CheckConstraint("confidence_index BETWEEN 0 AND 100", name="ck_ssp_ci"),
    )

    id                       = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id                  = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subject_id               = Column(Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    # ── 10 Core Metrics ──
    concept_master_score     = Column(Float, nullable=False, default=50.0)
    error_repetition_rate    = Column(Float, nullable=False, default=0.0)
    attempt_persistence      = Column(Float, nullable=False, default=50.0)
    struggle_recovery_rate   = Column(Float, nullable=False, default=50.0)
    practice_intensity       = Column(Float, nullable=False, default=50.0)
    learning_velocity        = Column(Float, nullable=False, default=50.0)
    knowledge_retention      = Column(Float, nullable=False, default=50.0)
    cognitive_thinking_level = Column(Float, nullable=False, default=50.0)
    engagement_frequency     = Column(Float, nullable=False, default=50.0)
    assessment_accuracy      = Column(Float, nullable=False, default=50.0)
    # ── Extended Metrics ──
    bloom_level_avg          = Column(Float, nullable=False, default=1.0)
    frustration_index        = Column(Float, nullable=False, default=0.0)
    confidence_index         = Column(Float, nullable=False, default=50.0)
    # ── Counters ──
    total_chat_turns         = Column(Integer, nullable=False, default=0)
    total_quizzes            = Column(Integer, nullable=False, default=0)
    avg_session_duration_min = Column(Float, nullable=False, default=0.0)
    updated_at               = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    subject = relationship("Subject")


register_updated_at_listener(StudentSubjectProfile)


class OverallCognitiveProfile(Base):
    """
    Cross-subject aggregate of the 10 core cognitive metrics.
    One row per student. Updated when any subject profile changes.
    """
    __tablename__ = "overall_cognitive_profiles"
    __table_args__ = (
        CheckConstraint("concept_master_score BETWEEN 0 AND 100", name="ck_ocp_cms"),
        CheckConstraint("error_repetition_rate BETWEEN 0.0 AND 1.0", name="ck_ocp_err"),
    )

    user_id                  = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    concept_master_score     = Column(Float, nullable=False, default=50.0)
    error_repetition_rate    = Column(Float, nullable=False, default=0.0)
    attempt_persistence      = Column(Float, nullable=False, default=50.0)
    struggle_recovery_rate   = Column(Float, nullable=False, default=50.0)
    practice_intensity       = Column(Float, nullable=False, default=50.0)
    learning_velocity        = Column(Float, nullable=False, default=50.0)
    knowledge_retention      = Column(Float, nullable=False, default=50.0)
    cognitive_thinking_level = Column(Float, nullable=False, default=50.0)
    engagement_frequency     = Column(Float, nullable=False, default=50.0)
    assessment_accuracy      = Column(Float, nullable=False, default=50.0)
    updated_at               = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    user = relationship("User")


register_updated_at_listener(OverallCognitiveProfile)


class CognitiveMetricHistory(Base):
    """
    Time-series snapshots of individual metric values.
    Used for sparkline charts and trend analysis.
    One row per (user, subject, metric_name) update event.
    """
    __tablename__ = "cognitive_metric_history"
    __table_args__ = (
        Index("idx_cmh_user_subject", "user_id", "subject_id"),
        Index("idx_cmh_recorded_at", "recorded_at"),
    )

    id          = Column(Integer, primary_key=True, autoincrement=True)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subject_id  = Column(Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=True)
    metric_name = Column(String(60), nullable=False)
    value       = Column(Float, nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class LearningPreference(Base):
    """
    AI-detected + student-declared learning preferences. 1:1 with User.
    All preference floats are 0.0–1.0 (0 = less, 1 = more).
    ai_detected_notes: JSONB free-form AI observations about this learner.
    """
    __tablename__ = "learning_preferences"
    __table_args__ = (
        CheckConstraint("prefers_examples BETWEEN 0.0 AND 1.0", name="ck_lp_examples"),
        CheckConstraint("prefers_analogies BETWEEN 0.0 AND 1.0", name="ck_lp_analogies"),
        CheckConstraint("prefers_step_by_step BETWEEN 0.0 AND 1.0", name="ck_lp_step"),
        CheckConstraint("prefers_visuals BETWEEN 0.0 AND 1.0", name="ck_lp_visuals"),
        CheckConstraint("attention_span BETWEEN 0.0 AND 100.0", name="ck_lp_attn"),
        CheckConstraint("responds_to_encouragement BETWEEN 0.0 AND 1.0", name="ck_lp_enc"),
        CheckConstraint(
            "preferred_length IN ('short','medium','detailed')",
            name="ck_lp_length",
        ),
    )

    user_id                  = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    prefers_examples         = Column(Float, nullable=False, default=0.5)
    prefers_analogies        = Column(Float, nullable=False, default=0.5)
    prefers_step_by_step     = Column(Float, nullable=False, default=0.5)
    prefers_visuals          = Column(Float, nullable=False, default=0.5)
    preferred_length         = Column(String(20), nullable=False, default="medium")
    attention_span           = Column(Float, nullable=False, default=50.0)
    responds_to_encouragement = Column(Float, nullable=False, default=0.5)
    ai_detected_notes        = Column(JSONB, nullable=True)
    updated_at               = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    user = relationship("User")


register_updated_at_listener(LearningPreference)


class StudentMemoryItem(Base):
    """
    A single durable fact about a student that persists across sessions.
    One row = one fact (not a JSON blob — individual rows enable CRUD).

    source_message_id: the assistant message from which this fact was extracted.
    is_active: False = student has toggled this memory off (still stored, never sent to LLM).
    subject_id: NULL means it's a cross-subject fact (e.g. "student prefers short answers").
    """
    __tablename__ = "student_memory_items"
    __table_args__ = (
        Index("idx_memory_items_user_subject", "user_id", "subject_id"),
        Index("idx_memory_items_is_active", "is_active"),
    )

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id           = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subject_id        = Column(Integer, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True)
    source_message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    fact              = Column(Text, nullable=False)
    is_active         = Column(Boolean, nullable=False, default=True)
    created_at        = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    subject        = relationship("Subject")
    source_message = relationship("Message")


# ── Topic Mastery ─────────────────────────────────────────────────────────────

class TopicMastery(Base):
    """
    Per-(student, topic) mastery tracking with spaced-repetition scheduling.
    UNIQUE(user_id, topic_id) — exactly one row per pair.

    mastery_level: 0–100. Updated by chat turns and quiz results.
    bloom_level_reached: 1–6 (Bloom's taxonomy). Updated by chat signals.
    next_review_date: spaced-repetition next review date.
    decay_rate: estimated forgetting curve rate (0.0–1.0).
    understood_concepts / confused_concepts / common_mistakes: JSONB lists.
    """
    __tablename__ = "topic_mastery"
    __table_args__ = (
        UniqueConstraint("user_id", "topic_id", name="uq_topic_mastery_user_topic"),
        Index("idx_topic_mastery_user_id", "user_id"),
        Index("idx_topic_mastery_next_review", "next_review_date"),
        CheckConstraint("mastery_level BETWEEN 0 AND 100", name="ck_tm_mastery"),
        CheckConstraint("bloom_level_reached BETWEEN 1 AND 6", name="ck_tm_bloom"),
        CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_tm_confidence"),
        CheckConstraint("decay_rate BETWEEN 0.0 AND 1.0", name="ck_tm_decay"),
    )

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    user_id             = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    topic_id            = Column(Integer, ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    mastery_level       = Column(Float, nullable=False, default=0.0)
    bloom_level_reached = Column(SmallInteger, nullable=False, default=1)
    times_visited       = Column(Integer, nullable=False, default=0)
    last_visited        = Column(DateTime(timezone=True), nullable=True)
    first_visited       = Column(DateTime(timezone=True), nullable=True)
    understood_concepts = Column(JSONB, nullable=True, default=list)
    confused_concepts   = Column(JSONB, nullable=True, default=list)
    common_mistakes     = Column(JSONB, nullable=True, default=list)
    required_backtrack  = Column(Boolean, nullable=True)
    backtrack_depth     = Column(Integer, nullable=True)
    backtrack_class     = Column(Integer, nullable=True)
    # Spaced repetition
    next_review_date    = Column(Date, nullable=True)
    review_count        = Column(Integer, nullable=False, default=0)
    decay_rate          = Column(Float, nullable=False, default=0.0)
    last_quiz_score     = Column(Float, nullable=True)
    confidence          = Column(Float, nullable=False, default=50.0)

    topic  = relationship("Topic")
    events = relationship("MasteryEvent", back_populates="mastery", cascade="all, delete-orphan")


class MasteryEvent(Base):
    """
    Append-only log of every mastery change for audit trail + sparkline charts.
    source: 'chat' | 'quiz' | 'decay' | 'manual'
    delta: signed change in mastery_level (positive = improvement, negative = decay).
    """
    __tablename__ = "mastery_events"
    __table_args__ = (
        Index("idx_mastery_events_mastery_id", "mastery_id"),
        Index("idx_mastery_events_created_at", "created_at"),
        CheckConstraint(
            "source IN ('chat','quiz','decay','manual')",
            name="ck_mastery_event_source",
        ),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    mastery_id = Column(Integer, ForeignKey("topic_mastery.id", ondelete="CASCADE"), nullable=False)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    topic_id   = Column(Integer, ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    source     = Column(String(20), nullable=False)
    delta      = Column(Float, nullable=False)    # signed change in mastery_level
    new_value  = Column(Float, nullable=False)    # mastery_level after this event
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    mastery = relationship("TopicMastery", back_populates="events")


class TopicPrerequisite(Base):
    """
    Prerequisite graph edges for the curriculum.
    Cycle detection is enforced at the application layer during ingestion.

    topic_id: the topic that has a prerequisite.
    prereq_topic_id: the prerequisite topic (may be from a different class).
    prereq_subject_id: FK to subjects (can be different subject, e.g. Maths for Physics).
    """
    __tablename__ = "topic_prerequisites"
    __table_args__ = (
        Index("idx_topic_prereqs_topic_id", "topic_id"),
    )

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    topic_id           = Column(Integer, ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    prereq_topic_id    = Column(Integer, ForeignKey("topics.id", ondelete="SET NULL"), nullable=True)
    prereq_class_num   = Column(Integer, nullable=False)
    prereq_subject_id  = Column(Integer, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True)
    prereq_description = Column(Text, nullable=False)
    difficulty_order   = Column(Integer, nullable=True)
    expected_keywords  = Column(JSONB, nullable=True)
    source             = Column(String(50), nullable=True)  # 'ai_generated' | 'manual' | 'ncert'

    topic           = relationship("Topic", foreign_keys=[topic_id], back_populates="prerequisites_from")
    prereq_topic    = relationship("Topic", foreign_keys=[prereq_topic_id])
    prereq_subject  = relationship("Subject")


# ── Quiz / Assignments ────────────────────────────────────────────────────────

class QuizAttempt(Base):
    """
    One quiz session by a student.
    source: 'mid_concept' | 'yesterday' | 'manual' | 'spaced_review'
    score: NULL until finish; 0.0–100.0 after finish.
    passed: score >= 60 (set on finish).
    """
    __tablename__ = "quiz_attempts"
    __table_args__ = (
        CheckConstraint(
            "source IN ('mid_concept','yesterday','manual','spaced_review')",
            name="ck_quiz_source",
        ),
        CheckConstraint("num_questions BETWEEN 1 AND 20", name="ck_quiz_num_q"),
        CheckConstraint("score IS NULL OR score BETWEEN 0 AND 100", name="ck_quiz_score"),
        Index("idx_quiz_attempts_user_id", "user_id"),
        Index("idx_quiz_attempts_subject_id", "subject_id"),
    )

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id         = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    subject_id      = Column(Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    topic_id        = Column(Integer, ForeignKey("topics.id", ondelete="SET NULL"), nullable=True)
    topic           = Column(String(300), nullable=True)    # free-text fallback when topic_id is NULL
    source          = Column(String(20), nullable=False, default="manual")
    num_questions   = Column(Integer, nullable=False, default=7)
    score           = Column(Float, nullable=True)
    passed          = Column(Boolean, nullable=True)
    finished_at     = Column(DateTime(timezone=True), nullable=True)
    created_at      = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    conversation = relationship("Conversation", back_populates="quiz_attempts")
    subject      = relationship("Subject")
    topic_obj    = relationship("Topic")
    questions    = relationship("QuizQuestion", back_populates="attempt", cascade="all, delete-orphan")


class QuizQuestion(Base):
    """
    One question in a quiz attempt.

    q_type: 'mcq' | 'theory'
    For MCQ: options is JSONB list of 4 strings, correct_index is 0-based.
    For theory: options is NULL, correct_index is NULL, correct_answer is the model answer.
    student_answer: set when student submits; NULL until then.
    is_correct: NULL until graded; True/False after.
    bloom_level: taxonomic level this question targets.
    difficulty: 'easy' | 'medium' | 'hard'
    """
    __tablename__ = "quiz_questions"
    __table_args__ = (
        UniqueConstraint("attempt_id", "q_index", name="uq_quiz_questions_attempt_idx"),
        CheckConstraint("q_type IN ('mcq','theory')", name="ck_qq_type"),
        CheckConstraint(
            "difficulty IS NULL OR difficulty IN ('easy','medium','hard')",
            name="ck_qq_difficulty",
        ),
        CheckConstraint(
            "bloom_level IS NULL OR bloom_level IN "
            "('remember','understand','apply','analyze','evaluate','create')",
            name="ck_qq_bloom",
        ),
        Index("idx_quiz_questions_attempt_id", "attempt_id"),
    )

    id             = Column(Integer, primary_key=True, autoincrement=True)
    attempt_id     = Column(UUID(as_uuid=True), ForeignKey("quiz_attempts.id", ondelete="CASCADE"), nullable=False)
    q_index        = Column(Integer, nullable=False)          # 0-based
    q_type         = Column(String(10), nullable=False)
    question       = Column(Text, nullable=False)
    options        = Column(JSONB, nullable=True)              # ["A text","B text","C text","D text"]
    correct_index  = Column(SmallInteger, nullable=True)       # 0-based (MCQ only)
    correct_answer = Column(Text, nullable=True)               # model answer (theory only)
    explanation    = Column(Text, nullable=True)               # shown after submission
    student_answer = Column(Text, nullable=True)               # set on submission
    is_correct     = Column(Boolean, nullable=True)            # set on grading
    difficulty     = Column(String(20), nullable=True)
    bloom_level    = Column(String(30), nullable=True)
    time_taken_ms  = Column(Integer, nullable=True)
    topic_id       = Column(Integer, ForeignKey("topics.id", ondelete="SET NULL"), nullable=True)

    attempt  = relationship("QuizAttempt", back_populates="questions")
    topic    = relationship("Topic")
    sources  = relationship("QuizQuestionSource", back_populates="question", cascade="all, delete-orphan")


class QuizQuestionSource(Base):
    """Links a quiz question to the content blocks it was generated from."""
    __tablename__ = "quiz_question_sources"
    __table_args__ = (
        UniqueConstraint("question_id", "block_id", name="uq_qq_sources_q_block"),
    )

    id          = Column(Integer, primary_key=True, autoincrement=True)
    question_id = Column(Integer, ForeignKey("quiz_questions.id", ondelete="CASCADE"), nullable=False)
    block_id    = Column(Integer, ForeignKey("content_blocks.id", ondelete="CASCADE"), nullable=False)

    question = relationship("QuizQuestion", back_populates="sources")
    block    = relationship("ContentBlock")


class SubjectQuizFeedback(Base):
    """
    Aggregated quiz/assignment feedback per (student, subject).
    UNIQUE(user_id, subject_id) — one row per pair, upserted after each quiz finish.
    weak_topics / strong_topics: JSONB lists of topic names.
    """
    __tablename__ = "subject_quiz_feedback"
    __table_args__ = (
        UniqueConstraint("user_id", "subject_id", name="uq_sqf_user_subject"),
        Index("idx_sqf_user_id", "user_id"),
        CheckConstraint("avg_score IS NULL OR avg_score BETWEEN 0 AND 100", name="ck_sqf_avg"),
    )

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id         = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subject_id      = Column(Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    total_attempts  = Column(Integer, nullable=False, default=0)
    total_questions = Column(Integer, nullable=False, default=0)
    total_correct   = Column(Integer, nullable=False, default=0)
    avg_score       = Column(Float, nullable=False, default=0.0)
    mcq_accuracy    = Column(Float, nullable=False, default=0.0)
    theory_accuracy = Column(Float, nullable=False, default=0.0)
    weak_topics     = Column(JSONB, nullable=True, default=list)
    strong_topics   = Column(JSONB, nullable=True, default=list)
    ai_feedback     = Column(Text, nullable=True)
    updated_at      = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    subject = relationship("Subject")


register_updated_at_listener(SubjectQuizFeedback)


# ── Session / Diagnostic ──────────────────────────────────────────────────────

class SessionInsight(Base):
    """AI-generated end-of-session analysis. Created as a background job."""
    __tablename__ = "session_insights"
    __table_args__ = (
        Index("idx_session_insights_conversation_id", "conversation_id"),
        Index("idx_session_insights_user_id", "user_id"),
    )

    id                    = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id       = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    user_id               = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subject_id            = Column(Integer, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True)
    topics_mastered       = Column(JSONB, nullable=True, default=list)
    topics_struggled      = Column(JSONB, nullable=True, default=list)
    misconceptions_found  = Column(JSONB, nullable=True, default=list)
    bloom_levels_achieved = Column(JSONB, nullable=True)   # {"remember": 3, "apply": 1, ...}
    engagement_rating     = Column(Float, nullable=True)
    session_summary       = Column(Text, nullable=True)
    recommendations       = Column(JSONB, nullable=True, default=list)
    created_at            = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    conversation = relationship("Conversation", back_populates="insights")


class DiagnosticState(Base):
    """In-progress Socratic diagnostic state per conversation."""
    __tablename__ = "diagnostic_states"

    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    state           = Column(JSONB, nullable=False)
    updated_at      = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    conversation = relationship("Conversation", back_populates="diagnostic")


register_updated_at_listener(DiagnosticState)


# ── Goals, Streaks, Tasks ─────────────────────────────────────────────────────

class StudentGoal(Base):
    """Student-set or AI-suggested learning goals."""
    __tablename__ = "student_goals"
    __table_args__ = (
        CheckConstraint(
            "goal_type IN ('daily_questions','master_topic','improve_score','complete_chapter','custom')",
            name="ck_goal_type",
        ),
        Index("idx_student_goals_user_id", "user_id"),
    )

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id       = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subject_id    = Column(Integer, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True)
    goal_type     = Column(String(50), nullable=False)
    goal_text     = Column(Text, nullable=False)
    target_value  = Column(Float, nullable=True)
    current_value = Column(Float, nullable=False, default=0.0)
    is_completed  = Column(Boolean, nullable=False, default=False)
    due_date      = Column(Date, nullable=True)
    created_at    = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at  = Column(DateTime(timezone=True), nullable=True)

    subject = relationship("Subject")


class StudentStreak(Base):
    """Daily engagement streak tracking. 1:1 with User."""
    __tablename__ = "student_streaks"
    __table_args__ = (
        CheckConstraint("current_streak_days >= 0", name="ck_streak_current"),
        CheckConstraint("longest_streak_days >= 0", name="ck_streak_longest"),
    )

    user_id               = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    current_streak_days   = Column(Integer, nullable=False, default=0)
    longest_streak_days   = Column(Integer, nullable=False, default=0)
    last_active_date      = Column(Date, nullable=True)
    total_active_days     = Column(Integer, nullable=False, default=0)
    total_sessions        = Column(Integer, nullable=False, default=0)
    total_questions_asked = Column(Integer, nullable=False, default=0)
    total_quizzes_taken   = Column(Integer, nullable=False, default=0)
    updated_at            = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    user = relationship("User")


register_updated_at_listener(StudentStreak)


class StudentTask(Base):
    """Assigned study tasks."""
    __tablename__ = "student_tasks"
    __table_args__ = (
        Index("idx_student_tasks_user_id", "user_id"),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subject_id = Column(Integer, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True)
    task       = Column(Text, nullable=False)
    is_done    = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    subject = relationship("Subject")


class PendingMetricSignal(Base):
    """
    Queued per-turn cognitive signals waiting for the next batch update.
    Batch updates fire every N turns (BATCH_TURN_INTERVAL in learning_engine.py).
    signals: JSONB list of signal dicts from each chat turn.
    """
    __tablename__ = "pending_metric_signals"
    __table_args__ = (
        Index("idx_pending_signals_user_subject", "user_id", "subject_id"),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    user_id         = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subject_id      = Column(Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    conversation_id = Column(UUID(as_uuid=True), nullable=True)
    signals         = Column(JSONB, nullable=False)    # list of per-turn signal dicts
    created_at      = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    subject = relationship("Subject")
