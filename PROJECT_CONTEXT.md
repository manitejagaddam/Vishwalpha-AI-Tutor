# VishwAlpha AI Tutor - Project Context

## Project Overview
VishwAlpha is a premium, AI-powered personalised tutoring system for the Indian NCERT curriculum (Class 6-12). Full architecture and file-by-file documentation is in `PROJECT_DESCRIPTION.md`.

*Note: All architecture and Phase 1-2 work was previously designed using Claude Sonnet. From Phase 3 onwards, all implementation is written by Gemini 3.1 Pro.*

## Tech Stack
- **LLM**: GPT-4.1-mini via Azure OpenAI (`viswalpha-foundry-50bd`)
- **Embeddings**: text-embedding-3-small via Azure OpenAI (1536 dims)
- **Backend**: FastAPI (Python 3.10+) + SQLAlchemy + pgvector
- **DB**: PostgreSQL (Supabase)
- **Cache**: Redis (Upstash) — 3-layer (embedding / retrieval / prereq)
- **Frontend**: React 19 + Vite + TailwindCSS v4

## Status (2026-09-20) — PHASE 2 SCHEMA MIGRATION COMPLETE

### VishwAlpha 2.0 Full Rebuild Initiated
- User confirmed DB is EMPTY; all old tables dropped. Building fresh.
- Reference files read: `Reference/vishwalpha_supbase_sql.sql`, `Reference/viswalpha-api.md`
- Stack confirmed: FastAPI + React 19 + Vite + Azure OpenAI (GPT-4.1-mini + text-embedding-3-small 1536d) + PostgreSQL 17.6 (Supabase, NEW account) + Redis (Upstash)
- Phase 1 spec written to `implementation_plan.md` (brain artifact).
- Key decisions: subject IDs not text strings; message-content-block tree; RLS on all student tables; separate `llm_call_logs` partitioned table; `student_memory_items` table (not text JSON); multilingual from day 1.

### Phase 2 Completed
- Set up Alembic (`uv add alembic`)
- Rewrote all ORM models into domain-specific files (`platform`, `content`, `chat`, `learning`, `platform_ops`).
- Created 7 migration files (up + down) for the new schema, including `006_rls` (Row-Level Security) and `007_indexes` (pgvector HNSW, GIN, Btree).
- Successfully verified all models import cleanly and the offline Alembic migration chain generates correctly.
- Created `addons.md` to document deferred features (Message Branching, Study Spaces, Attachments, etc.).

### Phase 3 Completed (Auth & Routing)
- Successfully applied all Alembic migrations (`alembic upgrade head`) to Supabase.
- Decided to stick with synchronous SQLAlchemy (psycopg2) for DB sessions to remain compatible with the synchronous 10-step orchestrator pipeline.
- Rewrote `app/schemas/auth.py` and `app/data/repos/auth_repo.py` to match the new `User` schema (Platform models) and `StudentProfile`/`OverallCognitiveProfile` (Learning models).
- Implemented robust Auth endpoints (`/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/me`) using JWT Bearer access tokens and secure refresh tokens.
- Rewrote FastAPI dependencies (`get_current_user`, `require_admin`) in `app/api/deps.py`.
- Built basic user routing in `app/api/student.py` (`/student/profile`, `/student/cognitive`).
- Updated `app/main.py` to mount the completed routers (auth, student, curriculum) while commenting out pending ones (chat, quiz).

### Phase 4 Completed (Chat & Quiz Domain Core)
- Built `app/data/repos/conversation_repo.py` to handle the new Tree-based Message architecture (`parent_message_id`, `idempotency_key`).
- Updated `app/schemas/chat.py` with `ChatRequest`/`ChatResponse` taking `conversation_id`, `parent_message_id` and `subject_id` instead of raw strings.
- Upgraded `app/api/chat.py` (sync `/chat` and SSE `/chat/stream`) to authenticate via the `User` dependency.
- Refactored `app/services/chat_orchestrator.py`: completely rewrote the execution pipeline to save student messages immediately, pull history up to the parent node, and pass `message_id` back down to the client.
- Adapted `app/data/quiz_repo.py` and `app/data/session_repo.py` (which now just acts as an adapter for legacy memory storage until Phase 5).

### Phase 5 Completed (Cognitive Domain Core & Schema Alignment)
- Completely rewrote `app/data/cognitive_repo.py` to support `user_id`, `subject_id` (integer) and `conversation_id`.
- Implemented `_update_overall_profile` to aggregate metrics across all subjects into `OverallCognitiveProfile`.
- Refactored `get_student_weak_topics` and `get_student_strong_topics` to correctly traverse `Topic -> Chapter -> Subject` foreign keys for filtering.
- Replaced the deprecated `CurriculumContent` / `CurriculumRouting` models in `app/services/retrieval_service.py`, `app/infra/vector_router.py`, and `app/data/curriculum_repo.py` with the new Phase 2 models (`ContentBlock`, `BlockEmbedding`, `Topic`, `Chapter`, `Subject`).
- Verified standard startup (all routers properly load/disable without errors).

### Phase 6 Completed (API Transition & Compatibility Layer)
- Re-enabled `student`, `sessions`, `chat`, and `quiz` routers in `app/main.py`.
- Updated schema mappings to align with Phase 2 (e.g. `Student` -> `User`, `ConversationSession` -> `Conversation`).
- Added backward compatibility layers for legacy frontend requests:
  - Added Pydantic validator in `ChatRequest` to cast `""` session IDs to `None` to fix 422 validation errors.
  - Resolved `subject_id` (integer) from the legacy `subject` (string) in endpoints like `/quiz/generate` and `/student/profile`.
  - Added subject fallback in the chat orchestrator to infer `subject_id` from existing `Conversation` records if the frontend omits it.
- Fixed `AttributeError` caused by schema changes (e.g., `class_num` moving from `StudentProfile` to `User`, `preferred_explanation_length` -> `preferred_length`, `student_id` -> `user_id`).
- Seeded base curriculum (`NCERT` board, `Class 10`, `Science/Math` subjects) to ensure strict foreign key constraints in `student_subject_profiles` are satisfied during metric updates.

### Phase 7 Completed (Schema Audit & Deep Fix)
- Performed a full cross-check of all ORM models vs all repo and API files.
- **`app/data/quiz_repo.py`**: Fixed all `student_id` references → `user_id` (column on `QuizAttempt` and `SubjectQuizFeedback` is `user_id`). Fixed `update_subject_quiz_feedback` to accept `subject_id: int` instead of `subject: str`. Fixed JSONB `weak_topics`/`strong_topics` handling (no more `json.dumps`/`json.loads` wrappers — JSONB returns native Python lists).
- **`app/api/quiz.py`**: Fixed `finish_quiz_endpoint`, `/history`, `/feedback/{subject}`. Fixed legacy import `from app.data.models import User, Topic` → correct Phase 2 packages.
- **`app/data/cognitive_repo.py`**: Fixed `TopicMastery` column names. Fixed weak/strong topics joins via `Topic → Chapter → Book → Subject`.
- **`app/infra/vector_router.py`**: Fixed `Chapter.subject_id`/`class_num` → full `Chapter → Book → Subject → SchoolClass` join chain.
- **`app/services/retrieval_service.py`**: Same Chapter→Book→Subject→SchoolClass join fix throughout.
- **`app/data/curriculum_repo.py`**: Rewritten — was using `Chapter.subject_id`/`class_num` (both nonexistent). Now uses `Book → Subject → SchoolClass`.
- **`app/services/ingestion_pipeline.py`**: Fully rewritten for Phase 2 schema. Creates `Board → SchoolClass → Subject → Book → Chapter → Topic → ContentBlock → BlockEmbedding` rows correctly.
- **`scripts/ingest.py`**: Updated CLI with new `--board`, `--book-title`, `--book-key`, `--chapter-num` args.
- **`app/api/sessions.py`**: Added `PATCH /sessions/{id}/title` and `POST /sessions/{id}/generate-title` (Claude-style smart heading).
- **`app/services/tutor_llm.py`**: Improved `generate_chat_title` prompt for Claude-style headings.

### Schema Rule (Golden)
`Chapter` has: `book_id`, `title`, `chapter_number`, `natural_key` — **NO `subject_id`, NO `class_num`**.
Always traverse: `Chapter → Book → Subject → SchoolClass` for subject/class lookups.

### All imports verified clean (2026-09-21):
`app.main`, `app.api.*`, `app.data.*`, `app.services.*`, `app.infra.*` — all import without errors.

### Next Step: Phase 8 (End-to-End Testing)
- Validate full UI workflows: chat streaming, quiz generation/finish, sessions list.
- Ingest a sample PDF using `python -m scripts.ingest` to test the new ingestion pipeline.
- Verify cognitive metrics update correctly after quiz completion.
