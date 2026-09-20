# VishwAlpha AI Tutor — Complete Project Description

**Version:** 2.0 | **Stack:** FastAPI + React + Azure OpenAI + PostgreSQL (pgvector) + Redis
**Audience:** Developers, Technical Leads, CTOs

---

## 1. Product Vision

VishwAlpha is a **personalised AI tutoring platform** built exclusively for the Indian NCERT curriculum (Class 6–12). It goes far beyond a simple chatbot:

- Every answer is grounded in actual NCERT textbook content (RAG)
- The AI builds a **cognitive profile** of each student across 10 learning dimensions
- Teaching style, difficulty, and tone adapt in real time
- A **quiz system** measures mastery and schedules revision using spaced repetition
- **Persistent memory** survives across sessions so the AI "knows" each student

---

## 2. Architecture

### 2.1 High-Level Overview

```
┌─────────────────────────────────────────────────────────┐
│  React + Vite Frontend (TypeScript, TailwindCSS v4)     │
│  Glassmorphism dark theme, responsive, markdown render  │
│  Auth (JWT localStorage) → Chat → Sidebar → Quiz UI    │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTPS / SSE (streaming)
                       │ Bearer JWT token on every request
┌──────────────────────▼──────────────────────────────────┐
│  FastAPI Backend (Python 3.10+)                         │
│  JWT auth (HS256) • CORS (env-based) • Rate Limiting    │
│  Request Tracing • Security Headers                     │
│                                                          │
│  7 Routers: /auth /chat /chat/stream /sessions          │
│             /student /quiz /curriculum /admin           │
│                                                          │
│  Chat Pipeline (8 steps):                               │
│    Session → History → Memory → Classify →              │
│    Route → Retrieve → Generate → Persist                │
└──────────┬──────────────────────────┬───────────────────┘
           │                          │
┌──────────▼──────────┐   ┌───────────▼──────────────────┐
│ PostgreSQL (Supabase)│   │ Azure OpenAI (East US 2)      │
│ + pgvector extension│   │ GPT-4.1-mini (chat)           │
│                     │   │ text-embedding-3-small (1536d) │
│ 22+ tables covering:│   └───────────────────────────────┘
│  • Curriculum (RAG) │
│  • Sessions/Messages│   ┌───────────────────────────────┐
│  • Cognitive Profile│   │ Redis (Upstash)               │
│  • Quiz Attempts    │   │ embedding cache (7d TTL)       │
│  • Topic Mastery    │   │ retrieval cache (30d TTL)      │
│  • Student Memory   │   │ prerequisite cache (30d TTL)  │
└─────────────────────┘   └───────────────────────────────┘
```

### 2.2 Chat Pipeline — Detailed (8 Steps)

Every message through `POST /chat` or `POST /chat/stream` executes:

| Step | Action | Key Files |
|------|--------|-----------|
| 1 | Load/create session, resolve student from JWT | `session_repo.py`, `auth_repo.py` |
| 1b | New session only: fetch yesterday's context, get spaced-review topics, update streak | `quiz_repo.py`, `cognitive_repo.py` |
| 2 | Load persistent memory + learning preferences | `session_repo.py`, `cognitive_repo.py` |
| 2b | Load weak topics (mastery < threshold) | `cognitive_repo.py` |
| 3 | Classify question: regex heuristic → LLM fallback | `question_classifier.py`, `tutor_llm.py` |
| 3b | Detect sentiment + Bloom's level + question mark | `cognitive_repo.py` |
| 4 | If curriculum: route via pgvector cosine → 3-level cascading retrieval | `vector_router.py`, `retrieval_service.py` |
| 5 | Generate answer (3 modes: curriculum/open_curriculum/conversational) | `tutor_llm.py` / `chat_orchestrator.py` |
| 5b | Background: generate chat title for new sessions | `tutor_llm.py` (threading) |
| 5c | Detect concept completion → maybe suggest quiz | `quiz_service.py` |
| 6 | Persist student + tutor messages with analytics | `session_repo.py` |
| 6b | Update session mood if frustrated/confused | `session_repo.py` |
| 7 | Collect cognitive signals → append to pending batch | `cognitive_repo.py` |
| 7b | Update topic mastery from this chat turn | `cognitive_repo.py` |
| 7c | Every 4 turns: batch-update cognitive profile + generate remark + update memory | `cognitive_repo.py`, `tutor_llm.py` |
| 8 | Return `ChatResponse` (or stream SSE tokens) | `chat.py` |

---

## 3. Backend Files Reference (Every File Explained)

### 3.1 Entry Points

**`app/main.py`** — FastAPI app factory
- Creates the FastAPI instance with lifespan (startup/shutdown)
- Adds middlewares: CORS (from `ALLOWED_ORIGINS` env), SecurityHeaders, RequestTracing, RateLimiting
- Registers 7 routers
- Runs DB init + log cleanup in background asyncio task on startup
- CORS origins are env-driven (no hardcoded `*`)

**`app/config.py`** — Configuration singleton
- Pydantic-settings `BaseSettings` class — all fields type-validated at startup
- Sources: `DATABASE_URL`, `AZURE_OPENAI_*`, `REDIS_URL`, `JWT_SECRET_KEY`, `ALLOWED_ORIGINS`, `ADMIN_API_KEY`, rate limits
- Single import: `from app.config import settings`

**`app/schemas.py`** — All Pydantic request/response contracts
- `RegisterRequest` / `LoginRequest` / `AuthResponse` (includes `access_token`)
- `ChatRequest` — validated (max 4000 chars, non-blank, valid tutor_mode, no student_id field)
- `ChatResponse` — includes sources, metrics, quiz_suggestion, yesterday_context, SSE metadata
- `GenerateQuizRequest` / `FinishQuizResponse` / `SubjectQuizFeedbackOut` (no student_id field)
- `IngestRequest` / `IngestResponse` — admin PDF ingestion

**`app/middleware.py`** — Two Starlette middlewares
- `RequestTracingMiddleware` — stamps every request with `X-Request-ID` UUID
- `SecurityHeadersMiddleware` — injects `X-Content-Type-Options`, `X-Frame-Options`

### 3.2 API Layer (`app/api/`)

**`app/api/deps.py`** ← NEW — JWT dependency hub
- `create_access_token(student)` — creates HS256 JWT (7-day default TTL)
- `get_current_student` — FastAPI Depends → validates Bearer token → returns Student ORM row
- `verify_admin_key` — validates `X-Admin-Key` header for admin routes
- Used by all protected routers via `Depends(get_current_student)`

**`app/api/auth.py`** — `POST /auth/register`, `POST /auth/login`
- Calls `auth_repo.register_student()` / `login_student()` for PBKDF2 hashing
- Returns `AuthResponse` with `access_token` (JWT)
- No authentication required (these are the auth endpoints)

**`app/api/chat.py`** — `POST /chat`, `POST /chat/stream`
- Both require JWT Bearer token
- `/chat`: runs orchestrator in `asyncio.to_thread()` (non-blocking), returns `ChatResponse` JSON
- `/chat/stream`: returns `StreamingResponse` (`text/event-stream`) — SSE tokens as they're generated
- SSE format: `data: {"type": "meta"|"token"|"done"|"error", ...}\n\n`

**`app/api/sessions.py`** — `GET /sessions`, `GET /history/{id}`, `GET /sessions/{id}/remark`
- JWT protected; session ownership verified
- `/history/{id}` now returns **all messages** (uses `get_full_history()`), not just the last 4
- `/sessions` uses single GROUP BY query (no N+1 anymore)

**`app/api/student.py`** — `GET /student/profile`, `GET /student/memory`, `POST /student/session/{id}/metrics`
- JWT protected; student_id from token (not query param)
- Thread-safe TTL cache (5s) with explicit `threading.RLock` for both profile and memory
- Cache invalidated on manual metrics override

**`app/api/quiz.py`** — Full quiz lifecycle (6 endpoints)
- All JWT protected; `student_id` always from token
- `generate`: fetches metrics, memory, weak topics → calls quiz_service → persists attempt
- `answer`: verifies answer, returns correct answer + explanation
- `finish`: scores, generates AI feedback, updates subject feedback record, cognitive signals, topic mastery, streak
- `yesterday`, `history`, `feedback/{subject}`: read-only, student-scoped

**`app/api/curriculum.py`** — `GET /curriculum/subjects`, `/chapters`, `/topics`
- Curriculum tree navigation for frontend dropdowns
- Queries `CurriculumRouting` table (pgvector routing table)

**`app/api/admin.py`** — `POST /admin/ingest`
- Protected by `X-Admin-Key` header via `verify_admin_key` from `deps.py`
- Triggers PDF ingestion pipeline for new curriculum content

### 3.3 Services Layer (`app/services/`)

**`app/services/chat_orchestrator.py`** — Main pipeline controller
- `_build_pipeline_context(request, student)` — gathers all data before LLM call
- `_post_generation_pipeline(...)` — persists + updates metrics after LLM response
- `chat(request, student)` — blocking mode (runs in asyncio.to_thread from endpoint)
- `chat_stream(request, student)` — async generator yielding SSE chunks
- Single metrics DB query per request (was two separate calls)
- Title generation in daemon background thread

**`app/services/tutor_llm.py`** — LLM generation + prompting
- 3 system prompt templates: `_CURRICULUM_PROMPT`, `_OPEN_CURRICULUM_PROMPT`, `_CONVERSATIONAL_PROMPT`
- `_build_teaching_style(prefs)` — injects learning preferences as natural language instructions
- `_build_weak_topics_section(str)` — formats weak topics for prompt
- `_build_review_section(list)` — formats spaced-rep review topics for prompt
- `TutorLLM.generate(mode, question, history, ...)` — builds messages list, calls Azure OpenAI
- `classify_question(q, history)` — LLM-based fallback classifier (zero-shot)
- `generate_chat_title(q)` — short 3-5 word title
- `generate_remark(ctx)` — teacher-style session insight

**`app/services/retrieval_service.py`** — RAG retrieval
- `upsert_chunk(metadata, text)` — embeds + upserts with **deterministic UUID** (sha256-based) ← fixed
- `retrieve_with_confidence(question, routing_metadata)` — 3-level cascade: topic → chapter → subject scope
- Confidence gate at 0.60 cosine similarity
- Redis embedding + chunk cache (3-layer)
- Compresses to 1500 tokens max

**`app/services/quiz_service.py`** — Quiz generation + feedback
- `generate_quiz(subject, topic, class_num, metrics, ...)` — LLM-generated MCQ + theory
- Difficulty calibrated from cognitive metrics (concept_master_score, assessment_accuracy)
- Bloom's taxonomy level assigned per question
- `detect_concept_completion(answer, topic)` — checks if topic is fully explained → suggest quiz
- `generate_quiz_ai_feedback(...)` — personalised feedback paragraph after quiz finish
- `compute_quiz_cognitive_signals(score, ...)` — translates quiz performance to metric signals

**`app/services/question_classifier.py`** — Zero-LLM heuristics
- `is_conversational(q)` — regex + keyword matching (no API call needed)
- `detect_understanding(response, keywords)` — 0.0-1.0 score (40% keyword, 20% length, 20% no-confusion, 20% coherence)
- `detect_give_up(response)` — triggers adaptive skip in Socratic mode

**`app/services/ingestion_pipeline.py`** — PDF → pgvector
- `IngestionPipeline.process_pdf(pdf_path, class_num, subject, chapter)`
- Chunks PDF text into 4000-char blocks
- LLM structures each chunk: heading + repaired text + summary
- Calls `router.upsert_topic()` (routing) and `upsert_chunk()` (retrieval) per section
- Invalidates Redis cache for the affected class/subject after ingestion

### 3.4 Data Layer (`app/data/`)

**`app/data/models.py`** — 22+ SQLAlchemy ORM models
- **Curriculum**: `CurriculumRouting` (pgvector, topic summaries), `CurriculumContent` (pgvector, full text)
- **Hierarchy**: `Board`, `Class_`, `Subject`, `Chapter`, `Topic`
- **Students**: `Student` (PBKDF2 password), `StudentSubjectProfile` (10 metrics), `OverallCognitiveProfile`, `StudentLearningPreference`, `StudentStreak`, `StudentGoal`, `StudentTopicMastery`, `StudentMemory`
- **Sessions**: `ConversationSession` (mood, bloom analytics, chat_title), `ConversationMessage` (sentiment, bloom, response_time_ms, topic_id)
- **Quiz**: `QuizAttempt`, `QuizQuestion` (difficulty, bloom, time_taken), `SubjectQuizFeedback`
- **System**: `PendingMetricSignal`, `DiagnosticState`, `PromptLog`, `StudentTask`, `SessionInsight`

**`app/data/database.py`** — SQLAlchemy engine
- `engine`: pool_size=10, max_overflow=20, pool_pre_ping=True, pool_recycle=1800s
- `managed_session()` — context manager (auto commit + close)
- `get_db()` — FastAPI dependency (session per request)
- `init_db()` — creates all tables from models

**`app/data/auth_repo.py`** — Authentication
- PBKDF2-HMAC-SHA256 (100k iterations, 16-byte random salt)
- `register_student()` — creates student + initialises cognitive profile + streak
- `login_student()` — verifies password hash
- `get_student(student_id)` — lookup by UUID

**`app/data/session_repo.py`** — Session + message management
- `get_or_create_session()` — idempotent session creation
- `get_history(session_id)` — **last 4 messages only** (LLM context window) ← API for LLM
- `get_full_history(session_id)` — **ALL messages** (for display in frontend) ← NEW
- `get_student_sessions()` — single GROUP BY+COUNT query (was N+1) ← fixed
- `save_turn()` — persists student + tutor messages with analytics
- `cleanup_old_prompt_logs()` — deletes logs > 5 days (uses `datetime.now(timezone.utc)`) ← fixed
- `update_student_memory()` — LLM merges new facts into JSON array
- `get_student_memory()` — returns memory facts for prompt injection

**`app/data/cognitive_repo.py`** — Cognitive profiling engine (786 lines)
- 10 core metrics per student per subject (concept_master, error_repetition, etc.)
- `collect_turn_signals()` — regex-based signal extraction per chat turn
- `append_pending_signal()` — queues signals for batch processing
- `batch_update_cognitive_profile()` — fires every 4 turns, updates DB, returns deltas
- `compute_cognitive_skills()` — maps 10 metrics → 5 Bloom's-aligned skills
- `update_student_streak()` — daily streak tracking
- `update_topic_mastery_from_chat()` / `update_topic_mastery_from_quiz()` — mastery updates
- `get_topics_due_for_review()` — spaced repetition scheduling
- `get_learning_preferences()` — returns learning style dict for prompt injection
- `get_student_weak_topics()` — topics with mastery < threshold

**`app/data/quiz_repo.py`** — Quiz data access
- `create_quiz_attempt()` / `save_quiz_questions()` / `get_quiz_questions()`
- `submit_quiz_answer()` — validates answer, marks correct/incorrect
- `finish_quiz_attempt()` — scores the attempt
- `get_attempt_details()` — full question list for feedback generation
- `update_subject_quiz_feedback()` — upserts cumulative subject record
- `get_yesterday_session_context()` — finds yesterday's most active topic

**`app/data/curriculum_repo.py`** — Curriculum browsing
- `get_subjects(db, class_num)` — distinct subjects from CurriculumRouting
- `get_chapters(db, class_num, subject)` — distinct chapters
- `get_topics(db, class_num, subject, chapter)` — distinct topics

### 3.5 Infrastructure Layer (`app/infra/`)

**`app/infra/azure_openai_client.py`** — Azure OpenAI singleton
- `@lru_cache get_openai()` — returns single `AzureOpenAI` client
- endpoint = `viswalpha-foundry-50bd`, model = `gpt-4.1-mini`
- timeout=30s, max_retries=2

**`app/infra/embedder.py`** — Text embedding
- Wraps Azure embedding API (`text-embedding-3-small`, 1536 dims)
- `embed_query(text)` / `embed_document(text)` — returns `list[float]`
- Checks Redis embedding cache before calling API

**`app/infra/redis_cache.py`** — 3-layer Redis cache
- Layer 1: embedding vectors (TTL 7 days)
- Layer 2: retrieval chunks (TTL 30 days)
- Layer 3: prerequisite mappings (TTL 30 days)
- Fail-safe: any Redis error is caught silently — system degrades gracefully

**`app/infra/vector_router.py`** — Semantic topic routing
- `route_query(question, class_num, subject)` — embeds query → cosine similarity on `CurriculumRouting`
- Scoped by class + subject → falls back to global if no match
- Returns `{chapter, topic, score}` for retrieval scoping
- `upsert_topic(class_num, subject, chapter, topic, summary)` — ingestion-time routing update

---

## 4. Frontend Files Reference

**`frontend/src/App.jsx`** — Root component
- Shows `AuthPage` if no student in auth context, else `ChatPage`

**`frontend/src/pages/AuthPage.jsx`** — Login/Register
- Tab-switched form (Login / Register)
- On success: stores JWT + student in `AuthContext` (localStorage)
- Error display from API response

**`frontend/src/pages/ChatPage.jsx`** — 3-panel layout
- `react-resizable-panels`: Sidebar | ChatArea | ContextPanel
- Lifts quiz state (activeQuiz) between Sidebar trigger and ChatArea display

**`frontend/src/components/Chat/ChatArea.jsx`** — Main chat UI
- Sends messages to `/chat` or `/chat/stream`
- Optimistic message append (student message appears instantly)
- Markdown rendering via `react-markdown` + `remark-gfm`
- Source citations after tutor messages
- Quiz suggestion cards (accepts/skips)
- Yesterday context banner
- Thinking indicator (bouncing dots)
- Auto-scrolls to bottom on new messages

**`frontend/src/components/Sidebar/Sidebar.jsx`** — Controls + history
- Subject dropdown, tutor mode dropdown, "Take a Quiz" button
- Session list (smart title: topic name or date-based)
- Long-term memory display
- Session insights/remark display

**`frontend/src/context/AuthContext.jsx`** — Auth state
- `student` (from login response), `login()`, `logout()`
- Persisted in localStorage

**`frontend/src/context/SessionContext.jsx`** — Session state
- `sessionId`, `messages`, `subject`, `tutorMode`, `sessions`, `memory`, `metrics`
- `refreshProfile()`, `refreshSessions()`, `refreshMemory()`, `loadSession(sid)`
- `metricsAdjustments` — batch update deltas for the ContextPanel

**`frontend/src/api/client.js`** — Axios client
- Base URL: `VITE_API_BASE` env var (should be set in `.env`)
- Sends `Authorization: Bearer <token>` header on all protected calls
- `authApi`, `chatApi`, `studentApi`, `quizApi`

**`frontend/src/index.css`** — Design tokens
- Animated gradient mesh background (15s cycle)
- `.glass-panel` / `.glass-card` — glassmorphism utilities
- Inter font, custom scrollbars

---

## 5. Security Model

| Layer | Protection |
|-------|-----------|
| Auth | HS256 JWT (7-day TTL), `python-jose` |
| Routes | All student routes: `Depends(get_current_student)` |
| Admin | `X-Admin-Key` header |
| CORS | Env-driven `ALLOWED_ORIGINS` (no wildcard `*`) |
| Passwords | PBKDF2-HMAC-SHA256, 100k iterations, 16-byte salt |
| Rate Limits | `slowapi`: 30/min chat, 120/min read, 10/min auth |
| Input | Pydantic validators on all request fields |
| Headers | `X-Content-Type-Options`, `X-Frame-Options`, request trace ID |

---

## 6. Cognitive Profiling System (10 Metrics)

| Metric | Scale | What It Measures |
|--------|-------|-----------------|
| `concept_master_score` | 0–100 | Overall conceptual understanding |
| `error_repetition_rate` | 0–1 | Rate of repeating the same mistakes |
| `attempt_persistence` | 0–100 | Willingness to retry after failure |
| `struggle_recovery_rate` | 0–100 | Speed of recovering from confusion |
| `practice_intensity` | 0–100 | Volume and regularity of practice |
| `learning_velocity` | 0–100 | Speed of mastering new concepts |
| `knowledge_retention` | 0–100 | Recall of previously learned material |
| `cognitive_thinking_level` | 0–100 | Higher-order thinking (Bloom's taxonomy) |
| `engagement_frequency` | 0–100 | How actively the student participates |
| `assessment_accuracy` | 0–100 | Quiz/test performance |

These 10 metrics are derived into 5 high-level **cognitive skills**:
- **Concept Understanding** = f(concept_master_score, assessment_accuracy)
- **Learning Effort** = f(practice_intensity, attempt_persistence, engagement_frequency)
- **Learning Adaptability** = f(struggle_recovery_rate, error_repetition_rate)
- **Knowledge Stability** = f(knowledge_retention, learning_velocity)
- **Cognitive Depth** = f(cognitive_thinking_level)

Updates fire in **batches every 4 turns** (not every message) for efficiency.

---

## 7. Dependencies

### Backend (`pyproject.toml`)
| Package | Purpose |
|---------|---------|
| `fastapi` | Web framework |
| `uvicorn` | ASGI server |
| `openai` | Azure OpenAI SDK |
| `sqlalchemy` | ORM |
| `pgvector` | pgvector SQLAlchemy type |
| `psycopg2-binary` | PostgreSQL driver |
| `pydantic` / `pydantic-settings` | Data validation + config |
| `python-jose[cryptography]` | JWT tokens ← added |
| `redis` | Cache client |
| `slowapi` | Rate limiting |
| `cachetools` | In-process TTL cache |
| `sse-starlette` | SSE streaming support ← added |
| `PyPDF2` | PDF text extraction |
| `python-dotenv` | .env loading |

### Frontend (`package.json`)
| Package | Purpose |
|---------|---------|
| `react` | UI framework |
| `vite` | Build tool |
| `tailwindcss` v4 | Styling |
| `axios` | HTTP client |
| `react-markdown` + `remark-gfm` | Markdown rendering |
| `react-resizable-panels` | 3-panel layout |
| `lucide-react` | Icon library |
| `react-router` | Routing |

---

## 8. Running Locally

### Backend
```bash
# 1. Copy and fill env
cp .env.example .env

# 2. Install dependencies
uv sync

# 3. Start server
uv run uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend

# Create .env.local
echo "VITE_API_BASE=http://localhost:8000" > .env.local

npm install
npm run dev
```

### Admin: Ingest a PDF
```bash
curl -X POST http://localhost:8000/admin/ingest \
  -H "X-Admin-Key: your-admin-key" \
  -H "Content-Type: application/json" \
  -d '{"pdf_path": "DataSet/class10_science.pdf", "class_num": 10, "subject": "Science", "chapter": "Chemical Reactions"}'
```

---

## 9. API Quick Reference

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/auth/register` | None | Register student, get JWT |
| POST | `/auth/login` | None | Login, get JWT |
| POST | `/chat` | JWT | Send message, get full JSON response |
| POST | `/chat/stream` | JWT | Send message, get SSE stream |
| GET | `/sessions` | JWT | List student's sessions |
| GET | `/history/{id}` | JWT | Full message history for a session |
| GET | `/sessions/{id}/remark` | JWT | AI-generated session insight |
| GET | `/student/profile` | JWT | Cognitive metrics + skills |
| GET | `/student/memory` | JWT | Persistent learning memory |
| POST | `/student/session/{id}/metrics` | JWT | Override metrics (teacher) |
| POST | `/quiz/generate` | JWT | Generate adaptive quiz |
| POST | `/quiz/answer` | JWT | Submit one answer |
| POST | `/quiz/finish` | JWT | Score + get AI feedback |
| GET | `/quiz/yesterday` | JWT | Yesterday's session context |
| GET | `/quiz/history` | JWT | Past quiz attempts |
| GET | `/quiz/feedback/{subject}` | JWT | Subject-level quiz stats |
| GET | `/curriculum/subjects` | None | Subjects for a class |
| GET | `/curriculum/chapters` | None | Chapters for class+subject |
| GET | `/curriculum/topics` | None | Topics for class+subject+chapter |
| POST | `/admin/ingest` | Admin Key | Ingest PDF into curriculum |
| GET | `/health` | None | Health check |

---

## 10. Known Limitations (Next Phase)

- No streaming on the frontend yet (team to implement SSE consumer in ChatArea)
- ContextPanel is a placeholder — analytics dashboard not built
- No email notifications for spaced-rep reminders
- Board hierarchy FK routing not yet wired (planned)
- No onboarding flow (flag in DB but UI not built)
- No global message search
