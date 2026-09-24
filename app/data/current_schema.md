## Table `boards`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int4` | Primary |
| `name` | `varchar(100)` |  Unique |
| `description` | `text` |  Nullable |

## Table `classes`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int4` | Primary |
| `board_id` | `int4` | FK → boards.id |
| `name` | `varchar(50)` |  |
| `level` | `int4` |  |

## Table `subjects`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int4` | Primary |
| `class_id` | `int4` | FK → classes.id |
| `name` | `varchar(100)` |  |

## Table `chapters`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int4` | Primary |
| `subject_id` | `int4` | FK → subjects.id |
| `title` | `varchar(200)` |  |
| `chapter_number` | `int4` |  |
| `summary` | `text` |  Nullable |
| `learning_objectives` | `text` |  Nullable |
| `key_concepts` | `text` |  Nullable |

## Table `topics`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int4` | Primary |
| `chapter_id` | `int4` | FK → chapters.id |
| `title` | `varchar(200)` |  |
| `topic_number` | `varchar(50)` |  Nullable |
| `chapter_number` | `int4` |  Nullable |
| `summary` | `text` |  Nullable |
| `prerequisites` | `text` |  Nullable |

## Table `topic_prerequisites`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int4` | Primary |
| `topic_id` | `int4` | FK → topics.id |
| `prereq_topic_id` | `int4` | FK → topics.id, Nullable |
| `prereq_class_num` | `int4` |  |
| `prereq_subject` | `varchar(100)` |  |
| `prereq_chapter` | `varchar(200)` |  Nullable |
| `prereq_description` | `text` |  |
| `difficulty_order` | `int4` |  Nullable |
| `expected_keywords` | `text` |  Nullable (JSON list) |
| `source` | `varchar(50)` |  Nullable |

## Table `content_chunks`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int4` | Primary |
| `topic_id` | `int4` | FK → topics.id |
| `content` | `text` |  |
| `chunk_index` | `int4` |  |
| `created_at` | `timestamptz` |  Nullable |

## Table `raw_content_chunks`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int4` | Primary |
| `topic_id` | `int4` | FK → topics.id |
| `content` | `text` |  |
| `chunk_index` | `int4` |  |
| `fine_tuned_content` | `text` |  |
| `class_num` | `int4` |  Nullable |
| `subject` | `varchar(100)` |  Nullable |
| `chapter` | `varchar(200)` |  Nullable |
| `topic` | `varchar(200)` |  Nullable |
| `created_at` | `timestamptz` |  Nullable |

## Table `curriculum_routing`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `varchar` | Primary |
| `class_num` | `int4` |  Nullable, Indexed |
| `subject` | `varchar(100)` |  Nullable, Indexed |
| `chapter` | `varchar(200)` |  Nullable |
| `topic` | `varchar(200)` |  Nullable |
| `vector` | `vector(384)` |  |

## Table `curriculum_content`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `varchar` | Primary |
| `class_num` | `int4` |  Nullable, Indexed |
| `subject` | `varchar(100)` |  Nullable, Indexed |
| `chapter` | `varchar(200)` |  Nullable |
| `topic` | `varchar(200)` |  Nullable |
| `content` | `text` |  |
| `vector` | `vector(384)` |  |

---

## Table `students`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `varchar` | Primary |
| `username` | `varchar(100)` |  Unique |
| `email` | `varchar(200)` |  Unique |
| `password_hash` | `varchar(500)` |  |
| `class_num` | `int4` |  |
| `board_id` | `int4` | FK → boards.id, Nullable |
| `preferred_language` | `varchar(50)` | Default: "English" |
| `learning_style` | `varchar(50)` |  Nullable |
| `onboarding_complete` | `bool` | Default: false |
| `created_at` | `timestamptz` |  Nullable |
| `last_active_at` | `timestamptz` |  Nullable |

## Table `student_learning_preferences` *(NEW)*

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `varchar` | Primary |
| `student_id` | `varchar` | FK → students.id, Unique |
| `prefers_examples` | `float8` | Default: 0.5 |
| `prefers_analogies` | `float8` | Default: 0.5 |
| `prefers_step_by_step` | `float8` | Default: 0.5 |
| `prefers_visuals` | `float8` | Default: 0.5 |
| `preferred_explanation_length` | `varchar(20)` | Default: "medium" |
| `attention_span_estimate` | `float8` | Default: 50.0 |
| `best_time_of_day` | `varchar(20)` |  Nullable |
| `responds_to_encouragement` | `float8` | Default: 0.5 |
| `prefers_hindi_mix` | `float8` | Default: 0.0 |
| `ai_detected_notes` | `text` |  Nullable (JSON) |
| `updated_at` | `timestamptz` |  Nullable |

## Table `student_streaks` *(NEW)*

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `varchar` | Primary |
| `student_id` | `varchar` | FK → students.id, Unique |
| `current_streak_days` | `int4` | Default: 0 |
| `longest_streak_days` | `int4` | Default: 0 |
| `last_active_date` | `date` |  Nullable |
| `total_active_days` | `int4` | Default: 0 |
| `total_sessions` | `int4` | Default: 0 |
| `total_questions_asked` | `int4` | Default: 0 |
| `total_quizzes_taken` | `int4` | Default: 0 |
| `updated_at` | `timestamptz` |  Nullable |

## Table `student_goals` *(NEW)*

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `varchar` | Primary |
| `student_id` | `varchar` | FK → students.id |
| `subject` | `varchar(100)` |  Nullable |
| `goal_type` | `varchar(50)` |  |
| `goal_text` | `text` |  |
| `target_value` | `float8` |  Nullable |
| `current_value` | `float8` | Default: 0.0 |
| `is_completed` | `bool` | Default: false |
| `due_date` | `date` |  Nullable |
| `created_at` | `timestamptz` |  Nullable |
| `completed_at` | `timestamptz` |  Nullable |

---

## Table `overall_cognitive_profiles`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `varchar` | Primary |
| `student_id` | `varchar` | FK → students.id, Unique |
| `concept_master_score` | `float8` | Default: 50.0 |
| `error_repetition_rate` | `float8` | Default: 0.0 |
| `attempt_persistence` | `float8` | Default: 50.0 |
| `struggle_recovery_rate` | `float8` | Default: 50.0 |
| `practice_intensity` | `float8` | Default: 50.0 |
| `learning_velocity` | `float8` | Default: 50.0 |
| `knowledge_retention` | `float8` | Default: 50.0 |
| `cognitive_thinking_level` | `float8` | Default: 50.0 |
| `engagement_frequency` | `float8` | Default: 50.0 |
| `assessment_accuracy` | `float8` | Default: 50.0 |
| `updated_at` | `timestamptz` |  Nullable |

## Table `student_subject_profiles`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `varchar` | Primary |
| `student_id` | `varchar` | FK → students.id |
| `subject` | `varchar(100)` |  Unique(student_id, subject) |
| `concept_master_score` | `float8` | Default: 50.0 |
| `error_repetition_rate` | `float8` | Default: 0.0 |
| `attempt_persistence` | `float8` | Default: 50.0 |
| `struggle_recovery_rate` | `float8` | Default: 50.0 |
| `practice_intensity` | `float8` | Default: 50.0 |
| `learning_velocity` | `float8` | Default: 50.0 |
| `knowledge_retention` | `float8` | Default: 50.0 |
| `cognitive_thinking_level` | `float8` | Default: 50.0 |
| `engagement_frequency` | `float8` | Default: 50.0 |
| `assessment_accuracy` | `float8` | Default: 50.0 |
| `bloom_level_avg` | `float8` | Default: 1.0 |
| `avg_session_duration_min` | `float8` | Default: 0.0 |
| `total_chat_turns` | `int4` | Default: 0 |
| `total_quizzes` | `int4` | Default: 0 |
| `frustration_index` | `float8` | Default: 0.0 |
| `confidence_index` | `float8` | Default: 50.0 |
| `updated_at` | `timestamptz` |  Nullable |

---

## Table `student_topic_mastery`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int4` | Primary |
| `student_id` | `varchar` | FK → students.id, Unique(student_id, topic_id) |
| `topic_id` | `int4` | FK → topics.id |
| `mastery_level` | `float8` | Default: 0.0 |
| `bloom_level_reached` | `int4` | Default: 1 (1=Remember → 6=Create) |
| `times_visited` | `int4` | Default: 0 |
| `last_visited` | `timestamptz` |  Nullable |
| `first_visited` | `timestamptz` |  Nullable |
| `understood_concepts` | `text` |  Nullable (JSON list) |
| `confused_concepts` | `text` |  Nullable (JSON list) |
| `common_mistakes` | `text` |  Nullable (JSON list) |
| `required_backtrack` | `bool` |  Nullable |
| `backtrack_depth` | `int4` |  Nullable |
| `backtrack_class` | `int4` |  Nullable |
| `next_review_date` | `date` |  Nullable |
| `review_count` | `int4` | Default: 0 |
| `decay_rate` | `float8` | Default: 0.0 |
| `last_quiz_score` | `float8` |  Nullable |
| `confidence` | `float8` | Default: 50.0 |

---

## Table `conversation_sessions`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `varchar` | Primary |
| `student_id` | `varchar` | FK → students.id |
| `class_num` | `int4` |  Nullable |
| `subject` | `varchar(100)` |  Nullable |
| `memory_summary` | `text` |  Nullable |
| `last_remark` | `text` |  Nullable |
| `last_remark_turn` | `int4` |  Nullable |
| `topics_covered` | `text` |  Nullable (JSON array) |
| `last_topic_name` | `varchar(300)` |  Nullable |
| `ended_at` | `timestamptz` |  Nullable |
| `session_duration_sec` | `int4` |  Nullable |
| `total_student_msgs` | `int4` | Default: 0 |
| `total_tutor_msgs` | `int4` | Default: 0 |
| `avg_student_msg_len` | `float8` |  Nullable |
| `avg_response_time_ms` | `float8` |  Nullable |
| `session_mood` | `varchar(50)` |  Nullable |
| `bloom_levels_hit` | `text` |  Nullable (JSON) |
| `created_at` | `timestamptz` |  Nullable |
| `updated_at` | `timestamptz` |  Nullable |

## Table `conversation_messages`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int4` | Primary |
| `session_id` | `varchar` | FK → conversation_sessions.id |
| `role` | `varchar(20)` |  |
| `content` | `text` |  |
| `context_used` | `text` |  Nullable |
| `routed_topic` | `varchar(200)` |  Nullable |
| `is_archived` | `bool` | Default: false |
| `response_time_ms` | `int4` |  Nullable |
| `token_count` | `int4` |  Nullable |
| `sentiment` | `varchar(20)` |  Nullable |
| `bloom_level` | `varchar(30)` |  Nullable |
| `contains_question` | `bool` |  Nullable |
| `topic_id` | `int4` | FK → topics.id, Nullable |
| `created_at` | `timestamptz` |  Nullable |

## Table `session_insights` *(NEW)*

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `varchar` | Primary |
| `session_id` | `varchar` | FK → conversation_sessions.id |
| `student_id` | `varchar` | FK → students.id |
| `subject` | `varchar(100)` |  Nullable |
| `topics_mastered` | `text` |  Nullable (JSON list) |
| `topics_struggled` | `text` |  Nullable (JSON list) |
| `misconceptions_found` | `text` |  Nullable (JSON list) |
| `bloom_levels_achieved` | `text` |  Nullable (JSON) |
| `engagement_rating` | `float8` |  Nullable |
| `session_summary` | `text` |  Nullable |
| `recommendations` | `text` |  Nullable (JSON) |
| `created_at` | `timestamptz` |  Nullable |

---

## Table `student_tasks`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int4` | Primary |
| `student_id` | `varchar` | FK → students.id |
| `subject` | `varchar(100)` |  Nullable |
| `task` | `text` |  |
| `done` | `bool` | Default: false |
| `created_at` | `timestamptz` |  Nullable |

## Table `student_memory`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int4` | Primary |
| `student_id` | `varchar` | FK → students.id |
| `subject` | `varchar(100)` | Unique(student_id, subject) |
| `memory` | `text` |  Nullable (JSON array) |
| `updated_at` | `timestamptz` |  Nullable |

## Table `pending_metric_signals`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int4` | Primary |
| `student_id` | `varchar` | FK → students.id |
| `subject` | `varchar(100)` |  |
| `session_id` | `varchar` |  Nullable |
| `signals` | `text` | (JSON) |
| `created_at` | `timestamptz` |  Nullable |

## Table `diagnostic_states`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `session_id` | `varchar` | Primary, FK → conversation_sessions.id |
| `state_json` | `text` |  |
| `updated_at` | `timestamptz` |  Nullable |

## Table `prompt_logs`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int4` | Primary |
| `session_id` | `varchar` |  Nullable |
| `student_id` | `varchar` |  Nullable |
| `prompt_payload` | `text` |  Nullable |
| `created_at` | `timestamptz` |  Nullable |

---

## Table `quiz_attempts`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `varchar` | Primary |
| `student_id` | `varchar` | FK → students.id |
| `session_id` | `varchar` | FK → conversation_sessions.id, Nullable |
| `subject` | `varchar(100)` |  |
| `topic` | `varchar(300)` |  Nullable |
| `source` | `varchar(50)` | Default: "manual" |
| `num_questions` | `int4` | Default: 7 |
| `score` | `float8` |  Nullable |
| `passed` | `bool` |  Nullable |
| `finished_at` | `timestamptz` |  Nullable |
| `created_at` | `timestamptz` |  Nullable |

## Table `quiz_questions`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `int4` | Primary |
| `attempt_id` | `varchar` | FK → quiz_attempts.id |
| `q_index` | `int4` |  |
| `q_type` | `varchar(10)` |  |
| `question` | `text` |  |
| `options` | `text` |  Nullable (JSON list) |
| `correct_index` | `int4` |  Nullable |
| `correct_answer` | `text` |  Nullable |
| `explanation` | `text` |  Nullable |
| `student_answer` | `text` |  Nullable |
| `is_correct` | `bool` |  Nullable |
| `difficulty` | `varchar(20)` |  Nullable |
| `bloom_level` | `varchar(30)` |  Nullable |
| `time_taken_ms` | `int4` |  Nullable |
| `topic_id` | `int4` | FK → topics.id, Nullable |

## Table `subject_quiz_feedback`

### Columns

| Name | Type | Constraints |
|------|------|-------------|
| `id` | `varchar` | Primary |
| `student_id` | `varchar` | FK → students.id |
| `subject` | `varchar(100)` | Unique(student_id, subject) |
| `total_attempts` | `int4` | Default: 0 |
| `total_questions` | `int4` | Default: 0 |
| `total_correct` | `int4` | Default: 0 |
| `avg_score` | `float8` | Default: 0.0 |
| `mcq_accuracy` | `float8` | Default: 0.0 |
| `theory_accuracy` | `float8` | Default: 0.0 |
| `weak_topics` | `text` |  Nullable (JSON list) |
| `strong_topics` | `text` |  Nullable (JSON list) |
| `ai_feedback` | `text` |  Nullable |
| `updated_at` | `timestamptz` |  Nullable |
