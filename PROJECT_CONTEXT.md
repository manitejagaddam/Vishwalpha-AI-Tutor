# VishwAlpha AI Tutor - Project Context

## Project Overview
VishwAlpha is a premium, AI-powered personalised tutoring system for the Indian NCERT curriculum (Class 6-12). Full architecture and file-by-file documentation is in `PROJECT_DESCRIPTION.md`.

## Tech Stack
- **LLM**: GPT-4.1-mini via Azure OpenAI (`viswalpha-foundry-50bd`)
- **Embeddings**: text-embedding-3-small via Azure OpenAI (1536 dims)
- **Backend**: FastAPI (Python 3.10+) + SQLAlchemy + pgvector
- **DB**: PostgreSQL (Supabase)
- **Cache**: Redis (Upstash) — 3-layer (embedding / retrieval / prereq)
- **Frontend**: React 19 + Vite + TailwindCSS v4

## Status (2026-09-20) — DB Audit Complete

### CORS Fix Applied
- ✅ `ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173` added to `.env`
  - Root cause: `ALLOWED_ORIGINS` was missing → parsed as empty list → all CORS blocked

### DB Schema Audit & Migration Fix
- ⚠️ PostgreSQL does not support `ADD CONSTRAINT IF NOT EXISTS` syntax (error 42601).
- ⚠️ Discovered duplicate rows in `student_subject_profiles` for student `8fbe50c6-4359-404f-bc4f-2c9d31637310` which would have failed unique constraint creation.
- ✅ Corrected SQL script created & tested against PostgreSQL 17.6 using a PL/pgSQL `DO $$` block and CTE deduplication (see `db_schema_audit.md`).
- Exact next step: User runs the tested script in Supabase SQL editor.


### All Backend Fixes Applied

**Critical Bug Fixes:**
- ✅ JWT authentication — `app/api/deps.py` (new), all routes protected
- ✅ `student_id` now from JWT token, never from request body/query params
- ✅ Chat endpoint is non-blocking (`asyncio.to_thread`)
- ✅ `upsert_chunk` uses deterministic UUID (sha256-based, prevents duplicate ingestion)
- ✅ `datetime.utcnow()` replaced with `datetime.now(timezone.utc)` in session_repo
- ✅ CORS now driven by `ALLOWED_ORIGINS` env var (was hardcoded `*`)
- ✅ Question input validated (max 4000 chars, non-blank, valid tutor_mode)
- ✅ Stale "Groq" docstring fixed in main.py description

**Performance Fixes:**
- ✅ N+1 query in `get_student_sessions` fixed (single GROUP BY+COUNT query)
- ✅ Single metrics DB query per request (was two separate calls)
- ✅ `get_full_history()` added for session detail (returns all messages vs 4 for LLM)
- ✅ Thread-safe `RLock`-protected TTL cache in student.py (was non-thread-safe `@cached`)

**New Features:**
- ✅ SSE streaming endpoint: `POST /chat/stream` with token-by-token delivery
- ✅ Session detail now returns full conversation history for frontend display
- ✅ `.env.example` created with all required variables documented
- ✅ `PROJECT_DESCRIPTION.md` created — full CTO-level documentation

**Packages Added:**
- `python-jose[cryptography]` — JWT tokens
- `sse-starlette` — SSE streaming support

## Files Touched (This Session)
- `app/api/deps.py` — NEW JWT dependency module
- `app/api/auth.py` — returns JWT token on login/register
- `app/api/chat.py` — async + SSE streaming endpoint
- `app/api/quiz.py` — fully JWT protected
- `app/api/sessions.py` — JWT + full history + ownership verification
- `app/api/student.py` — JWT + thread-safe cache
- `app/api/admin.py` — uses centralised verify_admin_key
- `app/schemas.py` — AuthResponse has access_token, ChatRequest validated
- `app/config.py` — JWT_SECRET_KEY, JWT_ACCESS_TOKEN_EXPIRE_MINUTES, ALLOWED_ORIGINS fields
- `app/main.py` — CORS from env, description fixed
- `app/services/chat_orchestrator.py` — async pipeline, SSE generator, single metrics query
- `app/services/retrieval_service.py` — deterministic chunk UUID
- `app/data/session_repo.py` — N+1 fix, datetime fix, get_full_history() added
- `.env.example` — NEW
- `PROJECT_DESCRIPTION.md` — NEW full documentation

### Frontend Optimisation & Integration COMPLETE
- ✅ Created `frontend/.env.local` to point to the backend.
- ✅ Added JWT auth interceptor in `frontend/src/api/client.js` to automatically attach `Authorization: Bearer <token>`.
- ✅ Implemented `sendMessageStream` using native `fetch` to read the SSE stream.
- ✅ Updated `ChatArea.jsx` to consume the SSE stream and progressively render tokens.
- ✅ Removed `student_id` from all API payloads across `client.js`, `SessionContext.jsx`, and `ChatArea.jsx`.
- ✅ Fixed `package.json` build script.


## What Frontend Team Needs To Do
- *(All critical integration steps for JWT, SSE streaming, and payload cleanup are now completed.)*
- Further UI refinements (ContextPanel, search, etc.) can be picked up in Phase 2.


## Next Phase (Not Started)
- **CRITICAL PRIORITY:** Vector Dimension Migration (384 -> 1536). A script has been created in `scratch/migrate_vectors.py` to handle the data migration from the old model to Azure OpenAI's `text-embedding-3-small`. This must be the absolute first priority to run when setting up or implementing the project to prevent `psycopg2.errors.DataException`.
- Board hierarchy FK routing (planned, DB supports it)
- ContextPanel analytics dashboard
- Onboarding flow (flag in DB exists)
- Global message search
