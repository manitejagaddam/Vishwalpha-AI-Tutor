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

## 10. Backend Optimisations — COMPLETED

**Status:** Completed in Phase 20
- **10a. Batch DB writes — streak + chat-turn counters**: Implemented `batch_increment_chat_counters(user_id, subject_id)` in `app/data/cognitive_repo.py`, coalescing streak calculation, user activity date, and profile chat turns into 1 transaction. Saved ~2 roundtrips per turn.
- **10b. PendingMetricSignal — fire-and-forget thread**: Queues `append_pending_signal` inside a daemon thread in `chat_orchestrator.py` without blocking streaming.
- **10c. Connection pool tuning**: Added `pool_timeout=30`, `pool_size=10, max_overflow=20, pool_pre_ping=True` in `app/data/database.py`.
- **10d. HTTP keep-alive for Azure OpenAI calls**: Passed persistent `httpx.Client(http2=True)` with connection pooling into `AzureOpenAI` in `app/infra/azure_openai_client.py`.
- **10e. Weak-topics & spaced-repetition caching**: Invalides session cache via `get_redis_cache().invalidate_session_state(user_id, subject_id)` in `finish_quiz_endpoint` in `app/api/quiz.py`.

---

### Architecture invariants (never break)
- `BookIngestionLog.status = complete` requires: all pages processed + no failed_pages + confidence >= 0.7
- Knowledge confidence != Learner-state confidence (never mix)
- Low-confidence ingestion -> NEVER directly update student cognitive profile
- RAG must not silently use content from `needs_review`/`failed` chapters (enforced in `retrieval_service.py`)
