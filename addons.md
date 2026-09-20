# VishwAlpha 2.0 — Deferred Feature Backlog

Features below were designed during Phase 1 planning but explicitly deferred to keep the current build backend-focused.
Each entry has enough detail that another developer can pick it up and implement it without re-discovery.

---

## 1. Message Branching (Edit / Regenerate)

**Priority:** High — enables Claude-style conversation editing  
**Deferred because:** Frontend must be rebuilt to show branch selectors; backend schema already supports it.

### What's Already Built (Phase 2 schema)

```sql
messages.parent_message_id UUID REFERENCES messages(id)  -- tree parent
messages.is_active_branch   BOOLEAN NOT NULL DEFAULT true -- which sibling is shown
conversations.active_message_id UUID REFERENCES messages(id) -- leaf of active branch
```

### How to Implement

**Backend (already designed, just needs the API endpoints):**
1. `POST /chat` with `parent_message_id` → creates a sibling branch, sets old sibling `is_active_branch = false`, new one = `true`, updates `conversations.active_message_id`.
2. `GET /conversations/{id}/messages` already returns the full tree; frontend renders it.
3. `PATCH /conversations/{id}/messages/{id}/activate` — switches active branch pointer.

**Frontend changes needed:**
- `MessageTree` component: renders `messages` as a tree, shows left/right arrows on messages that have siblings (same `parent_message_id`).
- `BranchSelector` inline: "1 / 3 ◀ ▶" arrows to cycle siblings.
- `useConversation` hook: tracks `active_message_id`, re-fetches on branch switch.
- The `Edit` button on a student message calls `POST /chat` with the same `parent_message_id` as the original message's parent.
- The `Regenerate` button calls `POST /chat` with the same `parent_message_id` as the assistant message's parent.

**UX Reference:** Claude's branch UX — edit pencil on student messages, circle-arrow on assistant messages.

---

## 2. Study Spaces (Per-Subject Workspaces)

**Priority:** Medium — good for organisation but not critical for learning  
**Deferred from UI because:** Requires frontend changes (space selector, custom instructions panel).  
**Schema IS included in Phase 2** (backend is ready).

### What's Already Built (Phase 2 schema)

```sql
CREATE TABLE study_spaces (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  subject_id  int  NOT NULL REFERENCES subjects(id),
  title       varchar(150) NOT NULL,
  custom_instructions text,
  pinned_context jsonb DEFAULT '[]',
  is_archived bool NOT NULL DEFAULT false,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
```

### How to Implement (Frontend + New Endpoints)

```
POST   /spaces              — create a study space
GET    /spaces              — list student's spaces
PATCH  /spaces/{id}         — rename, update instructions
DELETE /spaces/{id}         — archive
```

**Prompt injection:** Inject `space.custom_instructions` into system prompt before general student preferences.

---

## 3. Attachments (Images / PDFs from Students)

**Priority:** High — students photographing homework problems is a key use case  
**Deferred because:** Needs Supabase Storage for file hosting + virus-scan hook.

### Schema (already in Phase 2)

```sql
CREATE TABLE attachments (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id       uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  user_id          uuid NOT NULL REFERENCES users(id),
  file_name        varchar(255),
  mime_type        varchar(100),
  storage_key      varchar(500),
  size_bytes       int,
  extracted_text   text,
  vision_description text,
  scan_status      varchar(20) NOT NULL DEFAULT 'pending',
  created_at       timestamptz NOT NULL DEFAULT now()
);
```

### How to Implement

1. `POST /attachments/upload` → pre-signed upload URL from Supabase Storage.
2. Background job (`attachment_process`): extract text or call GPT-4.1-mini vision API.
3. Chat pipeline Step 4: inject `extracted_text` + `vision_description` into context alongside RAG blocks.

---

## 4. Real-Time Cross-Device Sync

**Priority:** Low  
**Deferred because:** Requires WebSocket or Supabase Realtime setup.

### Design
- Use Supabase Realtime (Postgres CDC) to broadcast INSERT events on `messages`.
- Frontend subscribes to `conversations:{user_id}` channel.
- Alternative: long-poll `GET /conversations/{id}/messages?since=<last_message_id>` every 3s.

---

## 5. Conversation Full-Text + Semantic Search

**Priority:** Medium  
**Index already planned in 007_indexes migration.**

### Endpoint
`GET /conversations/search?q=<text>&limit=20`

### Implementation
```sql
-- GIN index already in 007_indexes.py
CREATE INDEX idx_msg_content_fts ON message_content_blocks 
  USING gin(to_tsvector('english', content));
```

---

## 6. Sharing (Read-Only Conversation Snapshots)

**Priority:** Low  
**Schema already in Phase 2 (`share_links` table).**

### Endpoint
`GET /share/{token}` — public, unauthenticated, returns frozen conversation snapshot.

---

## 7. Incognito / Private Chat Mode

**Priority:** Medium  
**Deferred because:** Needs frontend toggle.

### Design
- `ChatRequest.incognito: bool = false`
- When `incognito=true`: skip cognitive signals, memory extraction, mastery update
- `conversations.is_incognito bool` column — auto-deleted after session
- No `message_sources` writes

---

## 8. Parent/Teacher Roles and Dashboards

**Priority:** Low for test phase  
**Deferred because:** No stakeholder requirement yet.

### Design Notes
- Roles: `parent`, `teacher` added to `users.role`
- `guardian_links (parent_id, student_id, consent_at)` table
- Parent dashboard: read-only child cognitive profile + mastery + streaks
- Teacher dashboard: class-wide mastery heatmap

---

## 9. A/B Prompt Experiments

**Priority:** Low  
**Table skeleton in 005_platform_ops migration.**

### Design
- `ab_experiments` table: `name, variant_a_template, variant_b_template, traffic_split`
- Hash `user_id` for deterministic variant assignment
- `llm_call_logs.ab_experiment_id` FK records which experiment was active

---

*Last updated: 2026-09-20. All deferred features have schema stubs already built in Phase 2.*
