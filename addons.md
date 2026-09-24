# VishwAlpha 2.0 — Deferred Feature Backlog

Features below were designed during Phase 1 planning but explicitly deferred to keep the current build backend-focused.
Each entry has enough detail that another developer can pick it up and implement it without re-discovery.

---

## 1. Message Branching (Edit / Regenerate) — COMPLETED

**Status:** Completed in Phase 17
- Backend: `parent_message_id` on `ChatRequest`, branch metadata (`sibling_ids`, `sibling_index`, `sibling_count`) returned by `GET /history/{session_id}`, branch activation endpoint `PATCH /conversations/{id}/messages/{id}/activate`.
- Frontend: `BranchSelector` component ("◀ 1 / 3 ▶"), inline edit prompt with "Save & Branch", and "Regenerate" response button on assistant messages.

---

## 2. Study Spaces (Per-Subject Workspaces) — COMPLETED

**Status:** Completed in Phase 17
- Backend: CRUD endpoints (`POST /spaces`, `GET /spaces`, `PATCH /spaces/{id}`, `DELETE /spaces/{id}`). Injected `StudySpace.custom_instructions` into prompt context.
- Frontend: Workspace selector & "+ New Space" in Sidebar, `StudySpaceModal`, active space badge in chat header.

---

## 3. Attachments (Images / PDFs from Students)

**Priority:** High
**Deferred because:** Needs Supabase Storage + virus-scan hook.

### How to Implement
1. `POST /attachments/upload` → pre-signed Supabase Storage URL.
2. Background job: extract text or call GPT-4.1-mini vision API.
3. Chat pipeline: inject `extracted_text` + `vision_description` into context alongside RAG blocks.

---

## 4. Real-Time Cross-Device Sync

**Priority:** Low
**Deferred because:** Requires WebSocket or Supabase Realtime setup.

---

## 5. Conversation Full-Text + Semantic Search — COMPLETED

**Status:** Completed in Phase 17
- Backend: `GET /conversations/search?q=<text>&limit=20` across conversation titles, topics, and message content blocks.
- Frontend: Search bar with debouncing in Sidebar above Past Sessions with live snippet highlights.

---

## 6. Sharing (Read-Only Conversation Snapshots) — COMPLETED

**Status:** Completed in Phase 17
- Backend: `POST /conversations/{id}/share` creates frozen JSONB snapshot in `share_links`; `GET /share/{token}` public unauthenticated endpoint.
- Frontend: "Share" button in ChatArea, `ShareModal` with 1-click URL copy, and standalone public viewer `SharePage.jsx` at `/share/:token`.

---

## 7. Incognito / Private Chat Mode — COMPLETED

**Status:** Completed in Phase 17
- Backend: `ChatRequest.incognito: bool` skips streak updates, cognitive signal accumulation, and deep session sync memory updates.
- Frontend: Incognito toggle in ChatArea top bar with amber stealth styling and ambient privacy notice.

---

## 8. Parent/Teacher Roles and Dashboards

**Priority:** Low for test phase

### Design Notes
- Roles: `parent`, `teacher` added to `users.role`
- `guardian_links (parent_id, student_id, consent_at)` table
- Parent dashboard: read-only child cognitive profile + mastery + streaks
- Teacher dashboard: class-wide mastery heatmap

---

## 9. Ingestion — Remaining Items

### Priority 1 — Automated test suite
- `test_ingestion_pipeline.py`: fixture PDFs (text, image-only, encrypted, duplicate, injection)
- `test_ingestion_stages.py`: unit tests for MIME check, header strip, cross-page stitch, structure detect
- `test_retrieval_filtering.py`: verify board/class/subject filtering

### Priority 2 — Table and Figure extraction
- Use `pdfplumber` to preserve row/column structure for tables.
- Pass page images to GPT-4o vision for figure caption/alt-text extraction.


---

### Architecture invariants (never break)
- `BookIngestionLog.status = complete` requires: all pages processed + no failed_pages + confidence >= 0.7
- Knowledge confidence != Learner-state confidence (never mix)
- Low-confidence ingestion -> NEVER directly update student cognitive profile
- RAG must not silently use content from `needs_review`/`failed` chapters (enforced in `retrieval_service.py`)

---

*Last updated: 2026-09-23. All implemented items removed.*

---

## 10. Backend Optimisations (Not Yet Implemented)

These were identified during the retrieval + chat-pipeline audits. Each saves real latency or DB load.

### 10a. Batch DB writes — streak + chat-turn counters
**What:** `increment_chat_turns`, `increment_streak_questions`, and `update_student_streak` each open a separate DB connection and commit on every chat turn. That's 3 writes per turn just for counters.  
**Fix:** Coalesce into a single `_batch_increment_counters(user_id, subject_id)` function that does one `UPDATE` touching all three rows in one transaction.  
**File:** `app/data/cognitive_repo.py` + `app/services/chat_orchestrator.py`  
**Estimated saving:** ~2 round-trip DB calls per chat turn.

### 10b. PendingMetricSignal — fire-and-forget thread
**What:** `append_pending_signal` currently writes to the DB synchronously in the hot path (every turn).  
**Fix:** Move it to a background thread (like the title generation already does) so it never blocks the response.  
**Risk:** Must handle the case where the process dies before the signal is written — acceptable since signals are low-value (they are delta adjustments, not primary data).  
**File:** `app/services/chat_orchestrator.py`

### 10c. Connection pool tuning
**What:** FastAPI + SQLAlchemy defaults to `pool_size=5, max_overflow=10`. Under concurrent student load, the pool exhausts quickly and requests queue.  
**Fix:** Set `pool_size=10, max_overflow=20, pool_pre_ping=True` in `app/data/database.py`. Also set `pool_timeout=30` to fail fast rather than hang.  
**File:** `app/data/database.py`

### 10d. HTTP keep-alive for Azure OpenAI calls
**What:** The `openai` SDK creates a new TCP connection per call by default under some configs. Under high load this adds ~50–80ms per LLM call.  
**Fix:** Pass a shared `httpx.Client` with `http2=True` into the `AzureOpenAI` constructor.  
**File:** `app/infra/azure_openai_client.py`

### 10e. Weak-topics & spaced-repetition caching (done for session, extend to quiz)
**What:** After a quiz is completed (`update_topic_mastery_from_quiz`), the session weak-topics cache is stale.  
**Fix:** Call `_get_session_cache().invalidate_session_state(user_id, subject_id)` in `app/api/quiz.py` after quiz submission so the next chat turn pulls a refreshed list.  
**File:** `app/api/quiz.py`

---

### Architecture invariants (never break)
- `BookIngestionLog.status = complete` requires: all pages processed + no failed_pages + confidence >= 0.7
- Knowledge confidence != Learner-state confidence (never mix)
- Low-confidence ingestion -> NEVER directly update student cognitive profile
- RAG must not silently use content from `needs_review`/`failed` chapters (enforced in `retrieval_service.py`)
