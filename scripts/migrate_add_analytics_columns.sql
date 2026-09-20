-- ================================================================
-- VishwAlpha — COMPLETE one-shot migration
-- Adds every column the ORM expects that may be missing in Supabase.
-- All statements use IF NOT EXISTS → 100% safe to re-run.
-- Run this in: Supabase Dashboard → SQL Editor → Run
-- ================================================================


-- ────────────────────────────────────────────────────────────────
-- 1. students
-- ────────────────────────────────────────────────────────────────
ALTER TABLE students
  ADD COLUMN IF NOT EXISTS board_id            INTEGER      REFERENCES boards(id) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS preferred_language  VARCHAR(50)  DEFAULT 'English',
  ADD COLUMN IF NOT EXISTS learning_style      VARCHAR(50)  DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS onboarding_complete BOOLEAN      DEFAULT false,
  ADD COLUMN IF NOT EXISTS last_active_at      TIMESTAMPTZ  DEFAULT NULL;


-- ────────────────────────────────────────────────────────────────
-- 2. student_learning_preferences  (entire table may not exist)
-- ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS student_learning_preferences (
  id                           VARCHAR PRIMARY KEY,
  student_id                   VARCHAR NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  prefers_examples             FLOAT   DEFAULT 0.5,
  prefers_analogies            FLOAT   DEFAULT 0.5,
  prefers_step_by_step         FLOAT   DEFAULT 0.5,
  prefers_visuals              FLOAT   DEFAULT 0.5,
  preferred_explanation_length VARCHAR(20) DEFAULT 'medium',
  attention_span_estimate      FLOAT   DEFAULT 50.0,
  best_time_of_day             VARCHAR(20) DEFAULT NULL,
  responds_to_encouragement    FLOAT   DEFAULT 0.5,
  prefers_hindi_mix            FLOAT   DEFAULT 0.0,
  ai_detected_notes            TEXT    DEFAULT NULL,
  updated_at                   TIMESTAMPTZ DEFAULT NULL,
  UNIQUE (student_id)
);


-- ────────────────────────────────────────────────────────────────
-- 3. student_streaks  (entire table may not exist)
-- ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS student_streaks (
  id                    VARCHAR PRIMARY KEY,
  student_id            VARCHAR NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  current_streak_days   INTEGER DEFAULT 0,
  longest_streak_days   INTEGER DEFAULT 0,
  last_active_date      DATE    DEFAULT NULL,
  total_active_days     INTEGER DEFAULT 0,
  total_sessions        INTEGER DEFAULT 0,
  total_questions_asked INTEGER DEFAULT 0,
  total_quizzes_taken   INTEGER DEFAULT 0,
  updated_at            TIMESTAMPTZ DEFAULT NULL,
  UNIQUE (student_id)
);


-- ────────────────────────────────────────────────────────────────
-- 4. student_goals  (entire table may not exist)
-- ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS student_goals (
  id            VARCHAR PRIMARY KEY,
  student_id    VARCHAR NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  subject       VARCHAR(100) DEFAULT NULL,
  goal_type     VARCHAR(50)  NOT NULL,
  goal_text     TEXT         NOT NULL,
  target_value  FLOAT        DEFAULT NULL,
  current_value FLOAT        DEFAULT 0.0,
  is_completed  BOOLEAN      DEFAULT false,
  due_date      DATE         DEFAULT NULL,
  created_at    TIMESTAMPTZ  DEFAULT now(),
  completed_at  TIMESTAMPTZ  DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS student_goals_student_id_idx ON student_goals(student_id);


-- ────────────────────────────────────────────────────────────────
-- 5. overall_cognitive_profiles  (entire table may not exist)
-- ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS overall_cognitive_profiles (
  id                       VARCHAR PRIMARY KEY,
  student_id               VARCHAR NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  concept_master_score     FLOAT DEFAULT 50.0,
  error_repetition_rate    FLOAT DEFAULT 0.0,
  attempt_persistence      FLOAT DEFAULT 50.0,
  struggle_recovery_rate   FLOAT DEFAULT 50.0,
  practice_intensity       FLOAT DEFAULT 50.0,
  learning_velocity        FLOAT DEFAULT 50.0,
  knowledge_retention      FLOAT DEFAULT 50.0,
  cognitive_thinking_level FLOAT DEFAULT 50.0,
  engagement_frequency     FLOAT DEFAULT 50.0,
  assessment_accuracy      FLOAT DEFAULT 50.0,
  updated_at               TIMESTAMPTZ DEFAULT NULL,
  UNIQUE (student_id)
);


-- ────────────────────────────────────────────────────────────────
-- 6. student_subject_profiles — add enhanced columns
-- ────────────────────────────────────────────────────────────────
ALTER TABLE student_subject_profiles
  ADD COLUMN IF NOT EXISTS bloom_level_avg          FLOAT   DEFAULT 1.0,
  ADD COLUMN IF NOT EXISTS avg_session_duration_min FLOAT   DEFAULT 0.0,
  ADD COLUMN IF NOT EXISTS total_chat_turns         INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_quizzes            INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS frustration_index        FLOAT   DEFAULT 0.0,
  ADD COLUMN IF NOT EXISTS confidence_index         FLOAT   DEFAULT 50.0;


-- ────────────────────────────────────────────────────────────────
-- 7. student_topic_mastery — add Bloom's + spaced repetition cols
-- ────────────────────────────────────────────────────────────────
ALTER TABLE student_topic_mastery
  ADD COLUMN IF NOT EXISTS bloom_level_reached INTEGER     DEFAULT 1,
  ADD COLUMN IF NOT EXISTS times_visited       INTEGER     DEFAULT 0,
  ADD COLUMN IF NOT EXISTS first_visited       TIMESTAMPTZ DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS understood_concepts TEXT        DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS confused_concepts   TEXT        DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS common_mistakes     TEXT        DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS required_backtrack  BOOLEAN     DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS backtrack_depth     INTEGER     DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS backtrack_class     INTEGER     DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS next_review_date    DATE        DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS review_count        INTEGER     DEFAULT 0,
  ADD COLUMN IF NOT EXISTS decay_rate          FLOAT       DEFAULT 0.0,
  ADD COLUMN IF NOT EXISTS last_quiz_score     FLOAT       DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS confidence          FLOAT       DEFAULT 50.0;


-- ────────────────────────────────────────────────────────────────
-- 8. conversation_sessions — analytics columns (from prev migration)
--    Repeated here so this script is self-contained.
-- ────────────────────────────────────────────────────────────────
ALTER TABLE conversation_sessions
  ADD COLUMN IF NOT EXISTS ended_at             TIMESTAMPTZ  DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS session_duration_sec INTEGER      DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS total_student_msgs   INTEGER      DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_tutor_msgs     INTEGER      DEFAULT 0,
  ADD COLUMN IF NOT EXISTS avg_student_msg_len  FLOAT        DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS avg_response_time_ms FLOAT        DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS session_mood         VARCHAR(50)  DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS bloom_levels_hit     TEXT         DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS topics_covered       TEXT         DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS last_topic_name      VARCHAR(300) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS chat_title           VARCHAR(150) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS last_remark_turn     INTEGER      DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_remark          TEXT         DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS memory_summary       TEXT         DEFAULT NULL;


-- ────────────────────────────────────────────────────────────────
-- 9. conversation_messages — per-message analytics
-- ────────────────────────────────────────────────────────────────
ALTER TABLE conversation_messages
  ADD COLUMN IF NOT EXISTS response_time_ms  INTEGER     DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS token_count       INTEGER     DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS sentiment         VARCHAR(20) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS bloom_level       VARCHAR(30) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS contains_question BOOLEAN     DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS topic_id          INTEGER     REFERENCES topics(id) DEFAULT NULL;


-- ────────────────────────────────────────────────────────────────
-- 10. quiz_questions — difficulty / Bloom's / timing
-- ────────────────────────────────────────────────────────────────
ALTER TABLE quiz_questions
  ADD COLUMN IF NOT EXISTS difficulty    VARCHAR(20) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS bloom_level   VARCHAR(30) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS time_taken_ms INTEGER     DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS topic_id      INTEGER     REFERENCES topics(id) DEFAULT NULL;


-- ────────────────────────────────────────────────────────────────
-- 11. subject_quiz_feedback — accuracy + AI feedback
-- ────────────────────────────────────────────────────────────────
ALTER TABLE subject_quiz_feedback
  ADD COLUMN IF NOT EXISTS mcq_accuracy    FLOAT DEFAULT 0.0,
  ADD COLUMN IF NOT EXISTS theory_accuracy FLOAT DEFAULT 0.0,
  ADD COLUMN IF NOT EXISTS weak_topics     TEXT  DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS strong_topics   TEXT  DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS ai_feedback     TEXT  DEFAULT NULL;


-- ────────────────────────────────────────────────────────────────
-- 12. session_insights  (entire table may not exist)
-- ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS session_insights (
  id                    VARCHAR PRIMARY KEY,
  session_id            VARCHAR NOT NULL REFERENCES conversation_sessions(id) ON DELETE CASCADE,
  student_id            VARCHAR NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  subject               VARCHAR(100) DEFAULT NULL,
  topics_mastered       TEXT    DEFAULT NULL,
  topics_struggled      TEXT    DEFAULT NULL,
  misconceptions_found  TEXT    DEFAULT NULL,
  bloom_levels_achieved TEXT    DEFAULT NULL,
  engagement_rating     FLOAT   DEFAULT NULL,
  session_summary       TEXT    DEFAULT NULL,
  recommendations       TEXT    DEFAULT NULL,
  created_at            TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS session_insights_session_id_idx  ON session_insights(session_id);
CREATE INDEX IF NOT EXISTS session_insights_student_id_idx  ON session_insights(student_id);


-- ================================================================
-- Verification — run after the migration to confirm students table
-- ================================================================
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'students'
ORDER BY ordinal_position;
