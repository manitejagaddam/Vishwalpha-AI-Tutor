# VishwAlpha AI Tutor — Frontend API Documentation

> **Version:** 2.0.0  
> **Last updated:** 2026-10-05  
> **Interactive docs:** `/docs` (Swagger UI) · `/redoc` (ReDoc) · `/openapi.json`

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Overview](#2-overview)
3. [Authentication Guide](#3-authentication-guide)
4. [Standard Response Format & Error Codes](#4-standard-response-format--error-codes)
5. [Auth](#5-auth)
6. [Chat](#6-chat)
7. [Sessions](#7-sessions)
8. [Student](#8-student)
9. [Quiz](#9-quiz)
10. [Curriculum](#10-curriculum)
11. [Study Spaces](#11-study-spaces)
12. [Attachments](#12-attachments)
13. [RealTime Sync (WebSocket)](#13-realtime-sync-websocket)
14. [Admin](#14-admin)
15. [System](#15-system)
16. [Pagination, Filtering & Sorting](#16-pagination-filtering--sorting)

---

## 1. Getting Started

### Run the backend locally

```bash
# 1. Install dependencies
uv sync

# 2. Copy env file and fill in values
cp .env.example .env

# 3. Run database migrations
uv run alembic upgrade head

# 4. Start the server
uv run uvicorn app.main:app --reload
```

**Swagger UI:** `http://localhost:8000/docs`  
**ReDoc:** `http://localhost:8000/redoc`  
**OpenAPI JSON:** `http://localhost:8000/openapi.json`

### Required environment variables (names only)

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string (pgvector enabled) |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key |
| `AZURE_OPENAI_BASE_URL` | Azure OpenAI base URL |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | GPT deployment name (e.g. `gpt-4.1-mini`) |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Embedding deployment name |
| `REDIS_URL` | Upstash / self-hosted Redis URL |
| `JWT_SECRET_KEY` | 64-char hex secret for JWT signing |
| `ADMIN_API_KEY` | Static key for admin routes |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins |

### CORS configuration

Controlled by `ALLOWED_ORIGINS` (comma-separated) and `ALLOWED_ORIGIN_REGEX`. Credentials are allowed.

Default allowed origins:
- `http://localhost:5173` (Vite)
- `http://localhost:3000` (CRA / Next.js)
- `http://localhost:8000`, `http://localhost:8080`
- `https://vishwalpha-ai-tutor-production.up.railway.app`
- `https://vishwalpha-ai-tutor.vercel.app`

**To add your domain**, add it to `ALLOWED_ORIGINS` in `.env`.

### File uploads

| Detail | Value |
|--------|-------|
| Endpoint | `POST /attachments/upload` |
| Form field name | `file` |
| Max size | **10 MB** |
| Allowed types | Images (`image/*`) and PDFs (`application/pdf`) |

---

## 2. Overview

| | Local | Production |
|--|-------|-----------|
| **Base URL** | `http://localhost:8000` | `https://vishwalpha-ai-tutor-production.up.railway.app` |
| **Auth method** | JWT Bearer token | JWT Bearer token |
| **Admin auth** | `X-Admin-Key` header | `X-Admin-Key` header |

### Common request headers

| Header | Required? | Value |
|--------|-----------|-------|
| `Authorization` | Yes (protected routes) | `Bearer <access_token>` |
| `Content-Type` | Yes (POST/PATCH) | `application/json` (or `multipart/form-data` for uploads) |
| `X-Admin-Key` | Yes (admin routes only) | `<your-admin-api-key>` |
| `X-Request-ID` | Optional | Echoed back; aids log tracing |

---

## 3. Authentication Guide

### Flow

```
1. POST /auth/register  OR  POST /auth/login
   -> Returns: access_token + refresh_token

2. All protected API calls:
   Authorization: Bearer <access_token>

3. When access_token expires:
   POST /auth/refresh  {refresh_token: "..."}
   -> Returns: new access_token

4. On logout:
   POST /auth/logout
   -> Revokes all refresh tokens server-side
```

### Token details

| Property | Value |
|----------|-------|
| Algorithm | HS256 |
| Access token lifetime | 7 days (configurable via `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`) |
| Refresh token lifetime | 7 days |
| Header | `Authorization: Bearer <token>` |

### Authorize in Swagger UI

1. Open `http://localhost:8000/docs`
2. Click **Authorize** (top right)
3. Paste your `access_token` (no "Bearer " prefix needed in the dialog)
4. Click **Authorize** — lock icons appear on protected routes

---

## 4. Standard Response Format & Error Codes

All errors return:
```json
{ "detail": "Human-readable error message" }
```

| Code | Meaning | Common cause |
|------|---------|-------------|
| `400` | Bad Request | Validation failure, duplicate username, empty file |
| `401` | Unauthorized | Missing/expired/invalid JWT |
| `403` | Forbidden | Wrong role, invalid admin key |
| `404` | Not Found | Resource not found or belongs to another user |
| `422` | Unprocessable Entity | Pydantic validation failed (rewritten to 400 by global handler) |
| `429` | Too Many Requests | Rate limit exceeded |
| `500` | Internal Server Error | LLM or DB failure |

> **Note:** FastAPI 422 errors are rewritten to 400 with a `detail` string naming the failing field.

---

## 5. Auth

### POST /auth/register

Register a new student account.

- **Auth required:** No — **Status:** 201

**Request body:**

| Field | Type | Required | Constraints | Example |
|-------|------|----------|-------------|---------|
| `username` | string | Yes | 3–50 chars | `"priya_sharma"` |
| `email` | string | Yes | max 200 | `"priya@example.com"` |
| `password` | string | Yes | 6–128 chars | `"SecurePass123"` |
| `class_num` | integer | Yes | 6–12 | `10` |

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"priya_sharma","email":"priya@example.com","password":"SecurePass123","class_num":10}'
```

**Success (201):**
```json
{
  "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "username": "priya_sharma",
  "class_num": 10,
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "dGhpcyBpcyBhIHNhbXBsZSByZWZyZXNoIHRva2Vu",
  "token_type": "bearer",
  "message": "Registration successful",
  "role": "student"
}
```

**Errors:** `400` username/email taken

---

### POST /auth/login

- **Auth required:** No

**Request body:**

| Field | Type | Required |
|-------|------|----------|
| `username` | string | Yes |
| `password` | string | Yes |

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"priya_sharma","password":"SecurePass123"}'
```

**Success (200):** Same shape as `/auth/register`  
**Errors:** `401` invalid credentials

---

### GET /auth/me

- **Auth required:** Yes (Bearer)

```bash
curl http://localhost:8000/auth/me -H "Authorization: Bearer <token>"
```

**Success (200):**
```json
{
  "user_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "username": "priya_sharma",
  "email": "priya@example.com",
  "class_num": 10,
  "role": "student"
}
```

---

### POST /auth/refresh

- **Auth required:** No (uses refresh_token)

**Request body:** `{ "refresh_token": "..." }`

**Success (200):** `{ "access_token": "eyJ..." }`  
**Errors:** `401` token invalid/expired

---

### POST /auth/logout

- **Auth required:** Yes (Bearer)

Revokes all refresh tokens for the user.

**Success (200):** `{ "ok": true }`

---

## 6. Chat

> **Rate limit:** 30 requests per minute per IP

### POST /chat

Send a question — **blocking JSON response**.

- **Auth required:** Yes (Bearer)

**Request body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `session_id` | UUID string | No | `null` | Leave null to start a new conversation |
| `question` | string | Yes | — | Student's question (1–4000 chars) |
| `subject` | string | No | `"Science"` | Subject name |
| `subject_id` | integer | No | `null` | Numeric subject ID (preferred over name) |
| `tutor_mode` | string | No | `"standard"` | `"standard"` or `"deep"` (Socratic) |
| `parent_message_id` | UUID | No | `null` | For regeneration/branching only |
| `study_space_id` | UUID | No | `null` | Attach to a study space |
| `incognito` | boolean | No | `false` | If true, turn not saved to history |
| `attachments` | array | No | `[]` | Attachment metadata from `POST /attachments/upload` |
| `idempotency_key` | string | No | `null` | Prevent duplicate submissions |

```json
{
  "question": "Explain Newton's second law of motion with an example.",
  "subject": "Science",
  "tutor_mode": "standard"
}
```

```bash
curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"question":"Explain Newtons second law","subject":"Science"}'
```

**Success (200):**
```json
{
  "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "message_id": "7a1b2c3d-4e5f-6789-abcd-ef0123456789",
  "answer": "Newton's second law states that Force = mass x acceleration...",
  "sources": [
    { "chapter": "Laws of Motion", "topic": "Newton's Laws", "score": 0.87 }
  ],
  "routed_chapter": "Laws of Motion",
  "routed_topic": "Newton's Second Law",
  "question_type": "curriculum",
  "cognitive_skills": { "critical_thinking": 65 },
  "metrics": { "concept_master_score": 58.0 },
  "metrics_adjustments": {},
  "conversation_length": 1,
  "is_new_conversation": true,
  "quiz_suggestion": null,
  "yesterday_context": null,
  "pending_tasks": [],
  "context": "",
  "chunks": [],
  "prompt_messages": [],
  "attachments": []
}
```

> **Important:** Save `conversation_id` from the first response and send it as `session_id` in all subsequent turns.

**Errors:** `401`, `429` rate limit, `500` LLM error

---

### POST /chat/stream

Send a question — **SSE streaming response**.

- **Auth required:** Yes (Bearer)
- **Response type:** `text/event-stream`

**Request body:** Same as `POST /chat`

**SSE events** (each line is `data: <json>\n\n`):

| Type | Shape | When |
|------|-------|------|
| `meta` | `{"type":"meta","session_id":"...","is_session_start":true}` | First event |
| `token` | `{"type":"token","content":"He"}` | Per token chunk |
| `done` | `{"type":"done","sources":[...],"metrics":{...},"conversation_id":"..."}` | Final |
| `error` | `{"type":"error","detail":"..."}` | On failure only |

**JavaScript fetch example:**
```javascript
const res = await fetch('/chat/stream', {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({ question: 'Explain photosynthesis', subject: 'Science' }),
});
const reader = res.body.getReader();
const dec = new TextDecoder();
let buf = '', answer = '';
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buf += dec.decode(value, { stream: true });
  const lines = buf.split('\n\n');
  buf = lines.pop();
  for (const line of lines) {
    if (!line.startsWith('data: ')) continue;
    const ev = JSON.parse(line.slice(6));
    if (ev.type === 'token') answer += ev.content;
    if (ev.type === 'meta')  conversationId = ev.session_id;
    if (ev.type === 'done')  { /* handle sources, metrics */ }
  }
}
```

---

### POST /chat/session/end

End a session — triggers background deep sync.

- **Auth required:** Yes (Bearer) — **Rate limit:** 10 req/min
- **Call this** when the user leaves the chat page or closes the app.

**Request body:**

| Field | Type | Required |
|-------|------|----------|
| `conversation_id` | string | Yes |
| `subject_id` | integer | No |

**Success (200):** `{ "status": "success", "message": "Session deep sync queued." }`

---

### POST /chat/feedback

Rate a tutor message (thumbs up/down).

- **Auth required:** Yes (Bearer)

**Request body:**

| Field | Type | Values |
|-------|------|--------|
| `message_id` | UUID string | — |
| `rating` | integer | `1` (up), `-1` (down), `0` (reset) |
| `feedback_text` | string | Optional |

**Success (200):** `{ "status": "success", "rating": 1 }`

---

## 7. Sessions

### GET /sessions

List all past chat sessions (newest first).

- **Auth required:** Yes

**Query params:** `?subject=Science`, `?study_space_id=<uuid>`

**Success (200):**
```json
{
  "sessions": [{
    "id": "3fa85f64-...",
    "chat_title": "Newton's Laws of Motion",
    "last_topic_name": "Newton's Second Law",
    "subject": "Science",
    "subject_id": 1,
    "study_space_id": null,
    "created_at": "2026-10-04T08:30:00Z",
    "updated_at": "2026-10-04T09:15:00Z",
    "total_messages": 12,
    "is_pinned": false
  }],
  "total": 1
}
```

---

### GET /history/{session_id}

Get full message history for a session.

- **Auth required:** Yes
- **Errors:** `401`, `404`

**Success (200):**
```json
{
  "session_id": "3fa85f64-...",
  "recent_messages": [{
    "id": "msg-uuid",
    "role": "user",
    "content": "Explain Newton's second law",
    "created_at": "2026-10-04T08:31:00Z",
    "parent_message_id": null,
    "sibling_ids": ["msg-uuid"],
    "sibling_index": 0,
    "sibling_count": 1,
    "attachments": [],
    "sources": [],
    "chapter": "",
    "topic": "",
    "question_type": "conversational"
  }],
  "total_messages": 4,
  "metrics": { "concept_master_score": 62.5 },
  "cognitive_skills": {},
  "subject": "Science",
  "chat_title": "Newton's Laws",
  "last_topic_name": "Newton's Second Law",
  "study_space_id": null
}
```

---

### GET /sessions/{session_id}/remark

- **Auth required:** Yes

**Success (200):** `{ "remark": "Great progress today!" }`

---

### POST /sessions/{session_id}/metrics

Manually override cognitive metrics.

- **Auth required:** Yes

**Request body:**
```json
{ "metrics": { "concept_master_score": 75.0, "knowledge_retention": 68.0 } }
```

Accepted keys: `concept_master_score`, `error_repetition_rate`, `attempt_persistence`, `struggle_recovery_rate`, `practice_intensity`, `learning_velocity`, `knowledge_retention`, `cognitive_thinking_level`, `engagement_frequency`, `assessment_accuracy`

**Success (200):** `{ "status": "success", "message": "Metrics updated successfully" }`

---

### PATCH /sessions/{session_id}/title

Rename a session (max 120 chars).

- **Auth required:** Yes

**Request body:** `{ "title": "Newton's Laws Deep Dive" }`

**Success (200):** `{ "title": "Newton's Laws Deep Dive" }`

---

### POST /sessions/{session_id}/generate-title

AI-generate a session title from message content.

- **Auth required:** Yes — No request body needed.

**Success (200):** `{ "title": "Newton Second Law Explained" }`

---

### PATCH /conversations/{session_id}/messages/{message_id}/activate

Activate a message branch (for regeneration navigation — left/right arrows).

- **Auth required:** Yes

**Success (200):** `{ "status": "ok", "active_message_id": "7a1b2c3d-..." }`

---

### GET /conversations/search

Full-text search across sessions and messages.

- **Auth required:** Yes

**Query params:** `?q=photosynthesis&limit=20`

**Success (200):**
```json
{
  "results": [{
    "id": "3fa85f64-...",
    "chat_title": "Cell Biology Quiz",
    "last_topic_name": "Photosynthesis",
    "created_at": "2026-10-01T10:00:00Z",
    "match_snippet": "...process of photosynthesis involves...",
    "match_type": "message"
  }]
}
```

---

### POST /conversations/{session_id}/share

Create a read-only share link.

- **Auth required:** Yes

**Success (200):** `{ "token": "abc123", "share_url": "/share/abc123" }`

---

### GET /share/{token}

View a shared conversation snapshot (public, no auth).

**Success (200):** Snapshot JSON with `title`, `subject`, `messages` array.  
**Errors:** `404` token not found/revoked

---

## 8. Student

### GET /student/profile

- **Auth required:** Yes

**Query params:** `?subject=Science` (optional; also resolves numeric `subject_id`)

**Success (200):**
```json
{
  "student_id": "3fa85f64-...",
  "username": "priya_sharma",
  "class_num": 10,
  "subject": "Science",
  "subject_id": 1,
  "board_id": 1,
  "learning_style": "visual"
}
```

> **Tip:** Call on app load with `?subject=<name>` to get the numeric `subject_id`. Cache it and pass it to `POST /chat/session/end`.

---

### GET /student/memory

- **Auth required:** Yes — **Query params:** `?subject=Science`

**Success (200):**
```json
{
  "metrics": { "concept_master_score": 62.5 },
  "cognitive_skills": { "critical_thinking": 65 },
  "memory": "• Student understands Newton's 3 laws\n• Struggles with friction"
}
```

---

### POST /student/memory

Manually add a memory fact.

- **Auth required:** Yes

**Request body:** `{ "subject": "Science", "fact": "Student confuses kinetic and potential energy" }`

**Success (200):** `{ "status": "success", "inserted": true, "fact": "..." }`

---

### GET /student/cognitive/{subject}

Full per-subject cognitive profile.

- **Auth required:** Yes — **Path param:** subject name or numeric ID

**Success (200):** (see full shape in interactive docs at `/docs`)

Key fields:
- `metrics` — 10 raw cognitive metrics (0–100 each)
- `bloom_level_avg`, `frustration_index`, `confidence_index`
- `cognitive_skills` — 5 derived high-level skills (0–100 each)
- `quiz_feedback` — `avg_score`, `weak_topics`, `strong_topics`, `ai_feedback`
- `memory_facts` — AI-curated persistent facts about this student

**Errors:** `404` subject not found

---

### GET /student/cognitive

Overview of all subjects the student has a profile for.

- **Auth required:** Yes

**Success (200):** `{ "profiles": [...], "total": 2 }`

---

### GET /student/topics/{subject}

Per-topic mastery heatmap data.

- **Auth required:** Yes
- **Query params:** `?chapter_id=3` (optional filter)

Each topic entry includes: `mastery_level` (0–100), `bloom_level_reached` (1–6), `understood_concepts`, `confused_concepts`, `next_review_date`, `last_quiz_score`.

Topics never visited by the student are **not included** (appear only after first chat/quiz).

---

### GET /student/learning-path/{subject}

Chapter-by-chapter curriculum roadmap with mastery data.

- **Auth required:** Yes

Returns: chapters with their topics, per-topic `mastery_level` (null = never visited), `has_review_due`, `avg_mastery`.

---

## 9. Quiz

### POST /quiz/generate

Generate a personalised adaptive quiz.

- **Auth required:** Yes

**Request body:**

| Field | Type | Required | Default |
|-------|------|----------|---------|
| `subject` | string | No | auto-detected |
| `topic` | string | No | `""` (auto from last chat) |
| `session_id` | string | No | `""` |
| `source` | string | No | `"manual"` |
| `num_questions` | integer | No | `7` (range 3–15) |

`source` values: `"manual"`, `"mid_concept"`, `"yesterday"`

**Success (200):**
```json
{
  "attempt_id": "550e8400-e29b-41d4-a716-446655440000",
  "subject": "Science",
  "topic": "Newton's Second Law",
  "source": "manual",
  "questions": [
    { "id": 1, "q_index": 1, "q_type": "mcq",
      "question": "A 5kg object accelerates at 2 m/s^2. Force applied?",
      "options": ["5 N", "10 N", "2.5 N", "7 N"] },
    { "id": 2, "q_index": 2, "q_type": "theory",
      "question": "State Newton's Second Law.", "options": [] }
  ]
}
```

> **Save `attempt_id`** — required for `POST /quiz/answer` and `POST /quiz/finish`.  
> Correct answers are NOT returned here.

---

### POST /quiz/answer

Submit one question's answer.

- **Auth required:** Yes

**Request body:**

| Field | Type | Notes |
|-------|------|-------|
| `attempt_id` | UUID string | Required for ownership check |
| `question_id` | integer | From question list |
| `student_answer_index` | integer | For MCQ (0-based index) |
| `student_answer` | string | For theory questions |

**Success (200):**
```json
{
  "is_correct": true,
  "correct_index": 1,
  "correct_answer": "10 N",
  "explanation": "F = ma = 5 x 2 = 10 N."
}
```

**Errors:** `403` attempt not yours, `404` question not in this attempt

---

### POST /quiz/finish

Finalise quiz — computes score, generates AI feedback, updates cognitive profile.

- **Auth required:** Yes

**Request body:** `{ "attempt_id": "550e8400-...", "session_id": "" }`

**Success (200):**
```json
{
  "attempt_id": "550e8400-...",
  "score": 80.0,
  "total": 5,
  "correct": 4,
  "passed": true,
  "topic": "Newton's Second Law",
  "subject": "Science",
  "ai_feedback": "Excellent work! Review friction problems.",
  "metrics_impact": { "assessment_accuracy": "+3.2" }
}
```

> **Side effects:** Updates topic mastery, spaced-repetition schedule, streaks. Broadcasts `quiz_completed` WebSocket event.

---

### GET /quiz/yesterday

Get yesterday's session context (for session-start banner).

- **Auth required:** Yes

**Success (200):** `{ "has_context": true, "context": { "subject": "Science", "topic": "...", "session_date": "2026-10-04" } }`

---

### GET /quiz/history

Past quiz attempt summaries.

- **Auth required:** Yes — **Query params:** `?subject=Science`

**Success (200):** `{ "attempts": [...] }`

---

### GET /quiz/feedback/{subject}

Aggregated quiz feedback for a subject.

- **Auth required:** Yes — **Path param:** subject name or numeric ID

**Success (200):**
```json
{
  "total_attempts": 7,
  "avg_score": 71.4,
  "mcq_accuracy": 78.0,
  "theory_accuracy": 62.0,
  "weak_topics": ["Friction", "Magnetic Field Lines"],
  "strong_topics": ["Newton's Laws"],
  "ai_feedback": "Strong conceptual understanding. Focus on numericals."
}
```

---

## 10. Curriculum

> **Public endpoints — no authentication required.**

### GET /curriculum/subjects

`?class_num=10`

**Success (200):** `{ "subjects": [{ "id": 1, "name": "Science" }] }`

### GET /curriculum/chapters

`?class_num=10&subject=Science`

**Success (200):** `{ "chapters": [{ "id": 1, "title": "Force and Laws of Motion", "chapter_number": 1 }] }`

### GET /curriculum/topics

`?class_num=10&subject=Science&chapter=Force+and+Laws+of+Motion`

**Success (200):** `{ "topics": [{ "id": 12, "title": "Newton's Second Law" }] }`

---

## 11. Study Spaces

### GET /spaces

- **Auth required:** Yes — **Query params:** `?subject=Science`

**Success (200):** `{ "spaces": [{ "id": "abc...", "title": "Physics Deep Dive", "subject": "Science", "custom_instructions": "...", "created_at": "..." }] }`

### POST /spaces

- **Auth required:** Yes — **Status:** 201

**Request body:**
```json
{
  "title": "Physics Deep Dive",
  "subject": "Science",
  "custom_instructions": "Focus on step-by-step numericals."
}
```

### PATCH /spaces/{space_id}

- **Auth required:** Yes

**Request body (all fields optional):**
```json
{ "title": "Updated Title", "custom_instructions": "New style", "is_archived": false }
```

### DELETE /spaces/{space_id}

Soft-deletes (archives) the space. **Auth required:** Yes

**Success (200):** `{ "status": "ok", "message": "Study space deleted" }`

---

## 12. Attachments

### POST /attachments/upload

- **Auth required:** Yes
- **Content-Type:** `multipart/form-data`
- **Form field:** `file`
- **Max:** 10 MB

```bash
curl -X POST http://localhost:8000/attachments/upload \
  -H "Authorization: Bearer <token>" \
  -F "file=@homework.jpg"
```

**Success (200):**
```json
{
  "attachment_id": "att_3fa85f64",
  "filename": "homework.jpg",
  "content_type": "image/jpeg",
  "url": "/uploads/user-uuid/homework.jpg",
  "extracted_text": "Q1: A 5kg box...",
  "description": "Homework problem about Newton's second law",
  "topic_hint": "Force and Motion",
  "base64_thumbnail": "data:image/jpeg;base64,..."
}
```

**Use in chat:** Include the response dict in the `attachments` array of `POST /chat`.

**Errors:** `400` file >10MB or empty, `500` vision analysis failed

> **Warning:** Attachments are saved to the local filesystem (`/uploads/`). In the current production deployment (Railway), this filesystem is ephemeral — attachments will be lost on redeploy.

---

## 13. RealTime Sync (WebSocket)

### WS /sync/ws

**Auth:** `?token=<access_token>` query param

```javascript
const ws = new WebSocket(`wss://<host>/sync/ws?token=${accessToken}`);

ws.onmessage = (e) => {
  const event = JSON.parse(e.data);
  switch (event.event) {
    case 'connected':      console.log('Devices:', event.data.active_devices); break;
    case 'pong':           break;
    case 'quiz_completed': updateQuizUI(event.data); break;
    case 'space_updated':  refreshSpacesList(event.data); break;
  }
};

// Keep-alive
setInterval(() => ws.send(JSON.stringify({ type: 'ping' })), 30000);
```

**Server-pushed events:**

| Event | When triggered |
|-------|---------------|
| `connected` | On successful connection |
| `pong` | Response to `ping` |
| `quiz_completed` | Another device finished a quiz |
| `space_updated` | Space created / updated / deleted |

**Client-to-server event types:** `ping`, `typing`, `presence`, `space_switch`

---

### POST /sync/broadcast

- **Auth required:** Yes

**Request body:**
```json
{ "event": "space_switch", "data": { "space_id": "abc..." } }
```

**Success (200):** `{ "status": "broadcasted", "clients_notified": 2 }`

---

### GET /sync/status

- **Auth required:** Yes

**Success (200):**
```json
{ "active_devices_for_user": 2, "total_connected_system_wide": 47 }
```

---

## 14. Admin

> **Auth:** `X-Admin-Key: <your-admin-api-key>` — NOT a Bearer token.

### POST /admin/ingest

Ingest a PDF chapter. **Content-Type:** `multipart/form-data`

**Form fields:**

| Field | Type | Required | Example |
|-------|------|----------|---------|
| `file` | file | Yes | NCERT chapter PDF |
| `board_name` | string | Yes | `"NCERT"` |
| `class_num` | integer | Yes | `10` |
| `subject_name` | string | Yes | `"Science"` |
| `book_title` | string | Yes | `"Science Class 10"` |
| `book_natural_key` | string | Yes | `"NCERT_10_Science_en_2023"` |
| `chapter_title` | string | Yes | `"Force and Laws of Motion"` |
| `chapter_number` | integer | Yes | `9` |

```bash
curl -X POST http://localhost:8000/admin/ingest \
  -H "X-Admin-Key: your-admin-api-key" \
  -F "file=@chapter9.pdf" \
  -F "board_name=NCERT" -F "class_num=10" \
  -F "subject_name=Science" -F "book_title=Science Class 10" \
  -F "book_natural_key=NCERT_10_Science_en_2023" \
  -F "chapter_title=Force and Laws of Motion" -F "chapter_number=9"
```

**Success (200):**
```json
{
  "status": "success",
  "sections_ingested": 24,
  "blocks_stored": 87,
  "chapter_id": 9,
  "message": "Chapter ingested successfully",
  "warnings": [],
  "ingestion_confidence": 0.94,
  "coverage": {}
}
```

---

### GET /admin/ingestion-log

- **Auth required:** `X-Admin-Key`
- **Query params:** `?book_natural_key=NCERT_10_Science_en_2023&status=success&limit=20`

---

## 15. System

### GET /health

Public health check.

**Success (200):** `{ "status": "ok", "version": "2.0.0" }`

---

## 16. Pagination, Filtering & Sorting

| Feature | Details |
|---------|---------|
| **Pagination** | Not cursor/offset-based. Endpoints return full lists. Use `limit` param where available (ingestion-log). |
| **Filtering** | Query params: `?subject=Science`, `?chapter_id=3`, `?study_space_id=<uuid>`, `?status=success` |
| **Sorting** | Sessions, quiz history, ingestion log: always newest-first. |
| **Search** | `GET /conversations/search?q=photosynthesis&limit=20` — full-text across titles and message content. |

---

*Generated from the VishwAlpha v2.0.0 backend codebase on 2026-10-05. For live interactive API testing with sample values pre-filled, visit `/docs`.*
