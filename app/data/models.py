"""
app/data/models.py
──────────────────
SQLAlchemy ORM models for the entire application.
Single source of truth for all database tables.

Tables:
  Curriculum hierarchy:  boards → classes → subjects → chapters → topics → content_chunks
  Routing:               curriculum_routing (pgvector for semantic chapter/topic routing)
  Content:               curriculum_content (pgvector for RAG retrieval)
  Raw training data:     raw_content_chunks (for future fine-tuning)
  Students:              students, student_learning_preferences, student_streaks, student_goals
  Cognitive profiles:    overall_cognitive_profiles, student_subject_profiles
  Topic mastery:         student_topic_mastery (per-topic Bloom's + spaced repetition)
  Conversations:         conversation_sessions, conversation_messages, session_insights
  Learning:              student_tasks, student_memory, pending_metric_signals
  Quiz/Assignments:      quiz_attempts, quiz_questions, subject_quiz_feedback
  Diagnostics:           diagnostic_states, prompt_logs
"""
from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey, Date,
    DateTime, Float, Boolean, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

Base = declarative_base()


# ── Curriculum Hierarchy ──────────────────────────────────────────────────────

class Board(Base):
    """Educational board (e.g. NCERT, CBSE, ICSE)."""
    __tablename__ = "boards"
    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    classes     = relationship("SchoolClass", back_populates="board", cascade="all, delete-orphan")


class SchoolClass(Base):
    """A class level within a board (e.g. Class 10)."""
    __tablename__ = "classes"
    id       = Column(Integer, primary_key=True, index=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=False)
    name     = Column(String(50), nullable=False)
    level    = Column(Integer, nullable=False)
    board    = relationship("Board", back_populates="classes")
    subjects = relationship("Subject", back_populates="school_class", cascade="all, delete-orphan")


class Subject(Base):
    """A subject within a class (e.g. Science)."""
    __tablename__ = "subjects"
    id           = Column(Integer, primary_key=True, index=True)
    class_id     = Column(Integer, ForeignKey("classes.id"), nullable=False)
    name         = Column(String(100), nullable=False)
    school_class = relationship("SchoolClass", back_populates="subjects")
    chapters     = relationship("Chapter", back_populates="subject", cascade="all, delete-orphan")


class Chapter(Base):
    """A chapter within a subject."""
    __tablename__ = "chapters"
    id                  = Column(Integer, primary_key=True, index=True)
    subject_id          = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    title               = Column(String(200), nullable=False)
    chapter_number      = Column(Integer, nullable=False)
    summary             = Column(Text, nullable=True)
    learning_objectives = Column(Text, nullable=True)
    key_concepts        = Column(Text, nullable=True)
    subject             = relationship("Subject", back_populates="chapters")
    topics              = relationship("Topic", back_populates="chapter", cascade="all, delete-orphan")


class Topic(Base):
    """A topic within a chapter."""
    __tablename__ = "topics"
    id             = Column(Integer, primary_key=True, index=True)
    chapter_id     = Column(Integer, ForeignKey("chapters.id"), nullable=False)
    title          = Column(String(200), nullable=False)
    topic_number   = Column(String(50), nullable=True)
    chapter_number = Column(Integer, nullable=True)
    summary        = Column(Text, nullable=True)
    prerequisites  = Column(Text, nullable=True)
    chapter        = relationship("Chapter", back_populates="topics")
    chunks         = relationship("ContentChunk", back_populates="topic", cascade="all, delete-orphan")


class TopicPrerequisite(Base):
    """
    Structured prerequisite links between topics for cross-class backtracking.
    Column names matched to the actual DB schema in current_schema.md.
    """
    __tablename__ = "topic_prerequisites"
    id                   = Column(Integer, primary_key=True, index=True)
    topic_id             = Column(Integer, ForeignKey("topics.id"), nullable=False, index=True)
    prereq_topic_id      = Column(Integer, ForeignKey("topics.id"), nullable=True, index=True)
    prereq_class_num     = Column(Integer, nullable=False)
    prereq_subject       = Column(String(100), nullable=False)
    prereq_chapter       = Column(String(200), nullable=True)
    prereq_description   = Column(Text, nullable=False)
    difficulty_order     = Column(Integer, nullable=True)
    expected_keywords    = Column(Text, nullable=True)       # JSON list of keywords
    source               = Column(String(50), nullable=True)  # ai_generated | manual | ncert


class ContentChunk(Base):
    """A chunk of curriculum content linked to a topic."""
    __tablename__ = "content_chunks"
    id          = Column(Integer, primary_key=True, index=True)
    topic_id    = Column(Integer, ForeignKey("topics.id"), nullable=False)
    content     = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False, default=0)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    topic       = relationship("Topic", back_populates="chunks")


class RawContentChunk(Base):
    """Raw + fine-tuned text pairs for future model training."""
    __tablename__ = "raw_content_chunks"
    id                 = Column(Integer, primary_key=True, index=True)
    topic_id           = Column(Integer, ForeignKey("topics.id"), nullable=False)
    class_num          = Column(Integer, nullable=True)
    subject            = Column(String(100), nullable=True)
    chapter            = Column(String(200), nullable=True)
    topic              = Column(String(200), nullable=True)
    content            = Column(Text, nullable=True)
    chunk_index        = Column(Integer, nullable=False, default=0)
    fine_tuned_content = Column(Text, nullable=True)
    created_at         = Column(DateTime(timezone=True), server_default=func.now())


# ── Vector Stores (pgvector) ──────────────────────────────────────────────────

class CurriculumRouting(Base):
    """
    pgvector store for semantic routing.
    One row per topic — embedding of the topic summary.
    Used to find WHICH chapter/topic a student question belongs to.
    Pre-filtered by class_num + subject for fast, scoped lookups.
    """
    __tablename__ = "curriculum_routing"
    id        = Column(String, primary_key=True)
    class_num = Column(Integer, nullable=True, index=True)
    subject   = Column(String(100), nullable=True, index=True)
    chapter   = Column(String(200), nullable=True)
    topic     = Column(String(200), nullable=True)
    vector    = Column(Vector(384))


class CurriculumContent(Base):
    """
    pgvector store for RAG retrieval.
    One row per content chunk — embedding of the full repaired text.
    Used to find WHAT content to include in the LLM context.
    """
    __tablename__ = "curriculum_content"
    id        = Column(String, primary_key=True)
    class_num = Column(Integer, nullable=True, index=True)
    subject   = Column(String(100), nullable=True, index=True)
    chapter   = Column(String(200), nullable=True)
    topic     = Column(String(200), nullable=True)
    content   = Column(Text, nullable=True)
    vector    = Column(Vector(384))


# ── Students & Identity ───────────────────────────────────────────────────────

class Student(Base):
    """Core student identity record."""
    __tablename__ = "students"
    id                  = Column(String, primary_key=True)
    username            = Column(String(100), unique=True, nullable=False)
    email               = Column(String(200), unique=True, nullable=False)
    password_hash       = Column(String(500), nullable=False)
    class_num           = Column(Integer, nullable=False)
    board_id            = Column(Integer, ForeignKey("boards.id"), nullable=True)
    preferred_language  = Column(String(50), default="English")
    learning_style      = Column(String(50), nullable=True)    # visual | auditory | reading | kinesthetic
    onboarding_complete = Column(Boolean, default=False)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    last_active_at      = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    learning_preferences = relationship("StudentLearningPreference", back_populates="student", uselist=False, cascade="all, delete-orphan")
    streak               = relationship("StudentStreak", back_populates="student", uselist=False, cascade="all, delete-orphan")
    overall_profile      = relationship("OverallCognitiveProfile", back_populates="student", uselist=False, cascade="all, delete-orphan")


class StudentLearningPreference(Base):
    """
    AI-detected and student-declared learning preferences.
    These are continuously refined by observing how the student interacts
    with different explanation styles, and are injected into the LLM prompt
    to personalise teaching approach.
    """
    __tablename__ = "student_learning_preferences"
    __table_args__ = (UniqueConstraint("student_id"),)
    id                          = Column(String, primary_key=True)
    student_id                  = Column(String, ForeignKey("students.id"), nullable=False)
    prefers_examples            = Column(Float, default=0.5)    # 0 = minimal examples, 1 = lots of examples
    prefers_analogies           = Column(Float, default=0.5)    # 0 = direct explanation, 1 = analogy-heavy
    prefers_step_by_step        = Column(Float, default=0.5)    # 0 = summarised, 1 = detailed steps
    prefers_visuals             = Column(Float, default=0.5)    # 0 = text-only, 1 = wants diagrams/tables
    preferred_explanation_length = Column(String(20), default="medium")  # short | medium | detailed
    attention_span_estimate     = Column(Float, default=50.0)   # 0-100 (low→high)
    best_time_of_day            = Column(String(20), nullable=True)  # morning | afternoon | evening | night
    responds_to_encouragement   = Column(Float, default=0.5)    # how much motivational language helps
    prefers_hindi_mix           = Column(Float, default=0.0)    # 0 = pure English, 1 = Hinglish heavy
    ai_detected_notes           = Column(Text, nullable=True)   # JSON: free-form AI observations about this learner
    updated_at                  = Column(DateTime(timezone=True), onupdate=func.now())

    student = relationship("Student", back_populates="learning_preferences")


class StudentStreak(Base):
    """
    Daily engagement tracking for gamification and consistency detection.
    Updated on every chat turn / quiz attempt. The AI uses streak data to
    motivate consistent learners and gently re-engage lapsed ones.
    """
    __tablename__ = "student_streaks"
    __table_args__ = (UniqueConstraint("student_id"),)
    id                    = Column(String, primary_key=True)
    student_id            = Column(String, ForeignKey("students.id"), nullable=False)
    current_streak_days   = Column(Integer, default=0)
    longest_streak_days   = Column(Integer, default=0)
    last_active_date      = Column(Date, nullable=True)
    total_active_days     = Column(Integer, default=0)
    total_sessions        = Column(Integer, default=0)
    total_questions_asked = Column(Integer, default=0)
    total_quizzes_taken   = Column(Integer, default=0)
    updated_at            = Column(DateTime(timezone=True), onupdate=func.now())

    student = relationship("Student", back_populates="streak")


class StudentGoal(Base):
    """
    Student-set or AI-suggested learning goals.
    Goals give the student agency and let the AI track progress toward
    concrete milestones (e.g., "Master Chapter 5 by Friday").
    """
    __tablename__ = "student_goals"
    id            = Column(String, primary_key=True)
    student_id    = Column(String, ForeignKey("students.id"), nullable=False, index=True)
    subject       = Column(String(100), nullable=True)
    goal_type     = Column(String(50), nullable=False)   # daily_questions | master_topic | improve_score | complete_chapter
    goal_text     = Column(Text, nullable=False)
    target_value  = Column(Float, nullable=True)
    current_value = Column(Float, default=0.0)
    is_completed  = Column(Boolean, default=False)
    due_date      = Column(Date, nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    completed_at  = Column(DateTime(timezone=True), nullable=True)


# ── Cognitive Profiles ────────────────────────────────────────────────────────

class OverallCognitiveProfile(Base):
    """
    Overall (cross-subject) cognitive metrics for a student.
    Aggregated from all per-subject profiles. Used for the student's
    global dashboard and when subject context is not available.
    """
    __tablename__ = "overall_cognitive_profiles"
    __table_args__ = (UniqueConstraint("student_id"),)
    id                        = Column(String, primary_key=True)
    student_id                = Column(String, ForeignKey("students.id"), nullable=False)
    concept_master_score      = Column(Float, default=50.0)
    error_repetition_rate     = Column(Float, default=0.0)
    attempt_persistence       = Column(Float, default=50.0)
    struggle_recovery_rate    = Column(Float, default=50.0)
    practice_intensity        = Column(Float, default=50.0)
    learning_velocity         = Column(Float, default=50.0)
    knowledge_retention       = Column(Float, default=50.0)
    cognitive_thinking_level  = Column(Float, default=50.0)
    engagement_frequency      = Column(Float, default=50.0)
    assessment_accuracy       = Column(Float, default=50.0)
    updated_at                = Column(DateTime(timezone=True), onupdate=func.now())

    student = relationship("Student", back_populates="overall_profile")


class StudentSubjectProfile(Base):
    """
    Per-subject cognitive metrics for a student.

    The 10 core metrics (concept_master_score through assessment_accuracy)
    are the raw signals that get aggregated into 5 high-level cognitive skills:
      - Concept Understanding    = f(concept_master_score, assessment_accuracy)
      - Learning Effort          = f(practice_intensity, attempt_persistence, engagement_frequency)
      - Learning Adaptability    = f(struggle_recovery_rate, error_repetition_rate)
      - Knowledge Stability      = f(knowledge_retention, learning_velocity)
      - Cognitive Depth          = f(cognitive_thinking_level)

    Additional columns track Bloom's taxonomy progression, session analytics,
    and AI-detected emotional indicators to give the LLM richer context.
    """
    __tablename__ = "student_subject_profiles"
    __table_args__ = (UniqueConstraint("student_id", "subject"),)
    id                        = Column(String, primary_key=True)
    student_id                = Column(String, ForeignKey("students.id"), nullable=False)
    subject                   = Column(String(100), nullable=False)

    # ── 10 Core Cognitive Metrics (0-100 scale, except error_repetition_rate which is 0-1) ──
    concept_master_score      = Column(Float, default=50.0)   # How well concepts are understood
    error_repetition_rate     = Column(Float, default=0.0)    # 0-1: rate of repeating same mistakes
    attempt_persistence       = Column(Float, default=50.0)   # Willingness to retry after failure
    struggle_recovery_rate    = Column(Float, default=50.0)   # Speed of recovery from confusion
    practice_intensity        = Column(Float, default=50.0)   # Volume and regularity of practice
    learning_velocity         = Column(Float, default=50.0)   # Speed of mastering new concepts
    knowledge_retention       = Column(Float, default=50.0)   # Ability to recall previously learned material
    cognitive_thinking_level  = Column(Float, default=50.0)   # Higher-order thinking (Bloom's)
    engagement_frequency      = Column(Float, default=50.0)   # How actively the student participates
    assessment_accuracy       = Column(Float, default=50.0)   # Performance on quizzes/tests

    # ── Enhanced Tracking (new) ──
    bloom_level_avg           = Column(Float, default=1.0)    # Average Bloom's level reached (1-6)
    avg_session_duration_min  = Column(Float, default=0.0)    # Running average session length
    total_chat_turns          = Column(Integer, default=0)    # Lifetime chat turn count for this subject
    total_quizzes             = Column(Integer, default=0)    # Lifetime quiz count for this subject
    frustration_index         = Column(Float, default=0.0)    # 0-100: AI-detected frustration level
    confidence_index          = Column(Float, default=50.0)   # 0-100: AI-detected confidence level

    updated_at                = Column(DateTime(timezone=True), onupdate=func.now())


# ── Topic-Level Mastery ───────────────────────────────────────────────────────

class StudentTopicMastery(Base):
    """
    Per-topic mastery tracking for each student.
    Tracks understanding depth (Bloom's), visit history, misconceptions,
    and spaced-repetition scheduling for optimal review timing.

    Updated by:
      - Chat pipeline: when student discusses a topic
      - Quiz pipeline: when student takes a topic quiz
      - Spaced repetition engine: when review date arrives
    """
    __tablename__ = "student_topic_mastery"
    __table_args__ = (UniqueConstraint("student_id", "topic_id"),)
    id                  = Column(Integer, primary_key=True, index=True)
    student_id          = Column(String, ForeignKey("students.id"), nullable=False, index=True)
    topic_id            = Column(Integer, ForeignKey("topics.id"), nullable=False, index=True)
    mastery_level       = Column(Float, default=0.0)          # 0-100 overall mastery
    bloom_level_reached = Column(Integer, default=1)          # 1=Remember, 2=Understand, 3=Apply, 4=Analyze, 5=Evaluate, 6=Create
    times_visited       = Column(Integer, default=0)
    last_visited        = Column(DateTime(timezone=True), nullable=True)
    first_visited       = Column(DateTime(timezone=True), nullable=True)
    understood_concepts = Column(Text, nullable=True)         # JSON list of concept strings
    confused_concepts   = Column(Text, nullable=True)         # JSON list of concept strings
    common_mistakes     = Column(Text, nullable=True)         # JSON list of mistake descriptions
    required_backtrack  = Column(Boolean, nullable=True)      # Did student need to go to a lower class topic?
    backtrack_depth     = Column(Integer, nullable=True)      # How many classes back?
    backtrack_class     = Column(Integer, nullable=True)      # Which class did they backtrack to?

    # ── Spaced Repetition ──
    next_review_date    = Column(Date, nullable=True)         # When this topic should be reviewed
    review_count        = Column(Integer, default=0)          # How many times reviewed
    decay_rate          = Column(Float, default=0.0)          # Estimated forgetting curve rate (0-1)
    last_quiz_score     = Column(Float, nullable=True)        # Most recent quiz score on this topic
    confidence          = Column(Float, default=50.0)         # Student self-assessment or AI-inferred confidence


# ── Conversations ─────────────────────────────────────────────────────────────

class ConversationSession(Base):
    """
    A single tutoring session between a student and the AI.
    Enhanced with per-session analytics for the AI to detect engagement
    patterns, fatigue, and learning momentum.
    """
    __tablename__ = "conversation_sessions"
    id                  = Column(String, primary_key=True)
    student_id          = Column(String, ForeignKey("students.id"), nullable=False, index=True)
    subject             = Column(String(100), nullable=True)
    class_num           = Column(Integer, nullable=True)
    memory_summary      = Column(Text, nullable=True)
    last_remark         = Column(Text, nullable=True)
    last_remark_turn    = Column(Integer, nullable=True, default=0)
    # Quiz / assignment tracking
    topics_covered      = Column(Text, nullable=True, default="[]")    # JSON array of topic names covered
    last_topic_name     = Column(String(300), nullable=True)           # Most recent topic for assignment prompt

    # ── Session Analytics (new) ──
    ended_at            = Column(DateTime(timezone=True), nullable=True)
    session_duration_sec = Column(Integer, nullable=True)
    total_student_msgs  = Column(Integer, default=0)
    total_tutor_msgs    = Column(Integer, default=0)
    avg_student_msg_len = Column(Float, nullable=True)                 # Average character count of student messages
    avg_response_time_ms = Column(Float, nullable=True)                # Average time between student msg and tutor reply
    session_mood        = Column(String(50), nullable=True)            # positive | neutral | frustrated | confused
    bloom_levels_hit    = Column(Text, nullable=True)                  # JSON: {"remember": 3, "understand": 1, ...}

    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), onupdate=func.now())
    messages            = relationship("ConversationMessage", back_populates="session", cascade="all, delete-orphan")


class ConversationMessage(Base):
    """
    A single message within a session.
    Enhanced with per-message analytics: response timing, sentiment,
    Bloom's level, and topic linkage.
    """
    __tablename__ = "conversation_messages"
    id               = Column(Integer, primary_key=True, index=True)
    session_id       = Column(String, ForeignKey("conversation_sessions.id"), nullable=False, index=True)
    role             = Column(String(20), nullable=False)     # "student" or "tutor"
    content          = Column(Text, nullable=False)
    context_used     = Column(Text, nullable=True)
    routed_topic     = Column(String(200), nullable=True)
    is_archived      = Column(Boolean, nullable=False, default=False)

    # ── Per-Message Analytics (new) ──
    response_time_ms = Column(Integer, nullable=True)         # Time from student msg to tutor reply (ms)
    token_count      = Column(Integer, nullable=True)         # Approximate token count of the message
    sentiment        = Column(String(20), nullable=True)      # positive | neutral | negative | confused | frustrated
    bloom_level      = Column(String(30), nullable=True)      # remember | understand | apply | analyze | evaluate | create
    contains_question = Column(Boolean, nullable=True)        # Does this message contain a question?
    topic_id         = Column(Integer, ForeignKey("topics.id"), nullable=True)

    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    session          = relationship("ConversationSession", back_populates="messages")


# ── Session Insights ──────────────────────────────────────────────────────────

class SessionInsight(Base):
    """
    AI-generated insights extracted at session end (or on batch boundaries).
    Powers teacher dashboards and longitudinal student progress analysis.
    """
    __tablename__ = "session_insights"
    id                    = Column(String, primary_key=True)
    session_id            = Column(String, ForeignKey("conversation_sessions.id"), nullable=False, index=True)
    student_id            = Column(String, ForeignKey("students.id"), nullable=False, index=True)
    subject               = Column(String(100), nullable=True)
    topics_mastered       = Column(Text, nullable=True)       # JSON list of topic names
    topics_struggled      = Column(Text, nullable=True)       # JSON list of topic names
    misconceptions_found  = Column(Text, nullable=True)       # JSON list of misconception strings
    bloom_levels_achieved = Column(Text, nullable=True)       # JSON: {"remember": 3, "apply": 1, ...}
    engagement_rating     = Column(Float, nullable=True)      # 0-100
    session_summary       = Column(Text, nullable=True)       # AI narrative summary
    recommendations       = Column(Text, nullable=True)       # JSON: next steps for the student
    created_at            = Column(DateTime(timezone=True), server_default=func.now())


# ── Learning Metadata ─────────────────────────────────────────────────────────

class StudentTask(Base):
    """Assigned study tasks for a student."""
    __tablename__ = "student_tasks"
    id         = Column(Integer, primary_key=True, index=True)
    student_id = Column(String, ForeignKey("students.id"), nullable=False, index=True)
    subject    = Column(String(100), nullable=True)
    task       = Column(Text, nullable=False)
    done       = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class StudentMemory(Base):
    """
    Persistent AI-curated facts about a student that survive across sessions.
    Stored as a JSON array of strings per (student_id, subject).
    The AI merges new observations into this list periodically.
    """
    __tablename__ = "student_memory"
    __table_args__ = (UniqueConstraint("student_id", "subject"),)
    id         = Column(Integer, primary_key=True, index=True)
    student_id = Column(String, ForeignKey("students.id"), nullable=False)
    subject    = Column(String(100), nullable=False)
    memory     = Column(Text, nullable=True, default="[]")
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PendingMetricSignal(Base):
    """
    Queued per-turn cognitive signals waiting for the next batch update.
    Batch updates fire every N turns (see BATCH_TURN_INTERVAL in cognitive_repo).
    """
    __tablename__ = "pending_metric_signals"
    id         = Column(Integer, primary_key=True, index=True)
    student_id = Column(String, ForeignKey("students.id"), nullable=False, index=True)
    subject    = Column(String(100), nullable=False)
    session_id = Column(String, nullable=True)
    signals    = Column(Text, nullable=False)  # JSON
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DiagnosticState(Base):
    """Stores in-progress Socratic diagnostic state per session."""
    __tablename__ = "diagnostic_states"
    session_id = Column(String, ForeignKey("conversation_sessions.id"), primary_key=True)
    state_json = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PromptLog(Base):
    """
    Stores LLM prompt messages for debugging/inspection (auto-purged after 5 days).
    Column names aligned with actual DB schema.
    """
    __tablename__ = "prompt_logs"
    id             = Column(Integer, primary_key=True, index=True)
    session_id     = Column(String, nullable=True, index=True)
    student_id     = Column(String, nullable=True, index=True)
    prompt_payload = Column(Text, nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())


# ── Quiz / Assignments ────────────────────────────────────────────────────────

class QuizAttempt(Base):
    """
    One quiz/assignment attempt by a student.
    source: 'mid_concept' (triggered mid-chat) | 'yesterday' (session-start) |
            'manual' (student-initiated) | 'spaced_review' (spaced repetition)
    """
    __tablename__ = "quiz_attempts"
    id            = Column(String, primary_key=True)              # UUID
    student_id    = Column(String, ForeignKey("students.id"), nullable=False, index=True)
    session_id    = Column(String, ForeignKey("conversation_sessions.id"), nullable=True)
    subject       = Column(String(100), nullable=False)
    topic         = Column(String(300), nullable=True)            # Topic this quiz covers
    source        = Column(String(50), nullable=False, default="manual")
    num_questions = Column(Integer, nullable=False, default=7)
    score         = Column(Float, nullable=True)                  # 0.0 – 100.0 (set on finish)
    passed        = Column(Boolean, nullable=True)                # score >= 60
    finished_at   = Column(DateTime(timezone=True), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    questions     = relationship("QuizQuestion", back_populates="attempt", cascade="all, delete-orphan")


class QuizQuestion(Base):
    """
    One question in a quiz attempt.

    q_type: 'mcq' | 'theory'
    For MCQ: options is a JSON list, correct_index is 0-based.
    For theory: options is null, correct_index is null, correct_answer is the model answer.

    Enhanced with difficulty level, Bloom's taxonomy, and time tracking.
    """
    __tablename__ = "quiz_questions"
    id              = Column(Integer, primary_key=True, index=True)
    attempt_id      = Column(String, ForeignKey("quiz_attempts.id"), nullable=False, index=True)
    q_index         = Column(Integer, nullable=False)             # 0-based order within attempt
    q_type          = Column(String(10), nullable=False)          # 'mcq' | 'theory'
    question        = Column(Text, nullable=False)
    options         = Column(Text, nullable=True)                 # JSON list of 4 strings (MCQ only)
    correct_index   = Column(Integer, nullable=True)              # 0-based correct option (MCQ)
    correct_answer  = Column(Text, nullable=True)                 # Model answer (theory)
    explanation     = Column(Text, nullable=True)
    student_answer  = Column(Text, nullable=True)                 # Student's submitted answer
    is_correct      = Column(Boolean, nullable=True)              # Set after submission

    # ── Enhanced Question Analytics (new) ──
    difficulty      = Column(String(20), nullable=True)           # easy | medium | hard
    bloom_level     = Column(String(30), nullable=True)           # remember | understand | apply | analyze | evaluate | create
    time_taken_ms   = Column(Integer, nullable=True)              # How long the student spent on this question
    topic_id        = Column(Integer, ForeignKey("topics.id"), nullable=True)

    attempt         = relationship("QuizAttempt", back_populates="questions")


class SubjectQuizFeedback(Base):
    """
    Aggregated quiz/assignment feedback per student per subject.
    One row per (student_id, subject). Updated after each quiz attempt is finished.
    Stores cumulative stats + AI-generated feedback text.
    """
    __tablename__ = "subject_quiz_feedback"
    __table_args__ = (UniqueConstraint("student_id", "subject"),)
    id                    = Column(String, primary_key=True)
    student_id            = Column(String, ForeignKey("students.id"), nullable=False)
    subject               = Column(String(100), nullable=False)
    total_attempts        = Column(Integer, default=0)
    total_questions       = Column(Integer, default=0)
    total_correct         = Column(Integer, default=0)
    avg_score             = Column(Float, default=0.0)
    mcq_accuracy          = Column(Float, default=0.0)            # % correct on MCQ questions
    theory_accuracy       = Column(Float, default=0.0)            # % correct on theory questions
    weak_topics           = Column(Text, nullable=True)           # JSON list of topic names
    strong_topics         = Column(Text, nullable=True)           # JSON list of topic names
    ai_feedback           = Column(Text, nullable=True)           # AI-generated feedback paragraph
    updated_at            = Column(DateTime(timezone=True), onupdate=func.now())
