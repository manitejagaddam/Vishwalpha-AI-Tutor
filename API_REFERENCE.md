# VishwAlpha Backend API — Frontend Integration Reference

> **Base URL (production):** `https://<railway-domain>.up.railway.app`  
> **Base URL (local dev):** `http://localhost:8000`  
> **Docs (auto-generated):** `GET /docs` (Swagger UI) | `GET /redoc`

---

## Authentication

All endpoints except `/auth/register`, `/auth/login`, `/auth/refresh`, and `/health`
require a JWT **Bearer token** in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

Access tokens expire in **30 minutes**. Use `/auth/refresh` with the stored
`refresh_token` to silently get a new one (valid 7 days).

---

## 1. Auth (`/auth`)

### `POST /auth/register`
Creates a new student account. No token required.

**Request body (JSON)**
| Field | Type | Rules |
|---|---|---|
| `username` | `string` | 3–50 chars, unique |
| `email` | `string` | max 200, unique |
| `password` | `string` | 6–128 chars |
| `class_num` | `integer` | 6–12 |

**Response `200`**
```jsonc
{
  "user_id":       "uuid-string",       // store this; used as student identity
  "username":      "riya_class10",
  "class_num":     10,
  "access_token":  "eyJ...",            // JWT, 30-min TTL
  "refresh_token": "eyJ...",            // 7-day TTL, store securely
  "role":          "student",
  "message":       "Registration successful"
}
```

**Errors:** `400` username/email already taken | `422` validation

---

### `POST /auth/login`
Authenticates an existing student.

**Request body** — same shape as Register but only `username` + `password`.

**Response** — same shape as `/auth/register`.

---

### `POST /auth/refresh`
Silently rotates the access token without re-login.

**Request body**
```jsonc
{ "refresh_token": "eyJ..." }
```

**Response**
```jsonc
{ "access_token": "eyJ..." }
```

**Errors:** `401` expired or revoked token.

---

### `POST /auth/logout`
Revokes all active sessions for this user.  **Requires Bearer token.**

**Response:** `{ "ok": true }`

---

### `GET /auth/me`
Returns the current user summary. **Requires Bearer token.**

**Response**
```jsonc
{
  "user_id":   "uuid",
  "username":  "riya_class10",
  "email":     "riya@example.com",
  "class_num": 10,
  "role":      "student"
}
```

---

## 2. Chat (`/chat`)

> **The two most important endpoints.** The frontend should always prefer
> `/chat/stream` (SSE) for real-time rendering.

---

### `POST /chat/stream` ⭐ PRIMARY
Streams the AI tutor response as **Server-Sent Events** (SSE).

**Request body**
```jsonc
{
  "session_id": "",           // "" or omit → creates new session; pass UUID for existing
  "question":   "What is photosynthesis?",
  "subject":    "Science",   // any subject name matching DB (case-insensitive)
  "class_num":  null,        // optional; resolved from JWT if null
  "tutor_mode": "standard"   // "standard" (direct answer) | "deep" (Socratic)
}
```

**Response** — `text/event-stream`, each line is `data: <JSON>\n\n`

```jsonc
// Event 1 — always first
data: {"type":"meta","session_id":"<uuid>","is_session_start":true}

// Event 2…N — one per streamed token chunk
data: {"type":"token","content":"Photo"}
data: {"type":"token","content":"synthesis"}
data: {"type":"token","content":" is the process..."}

// Final event — signals end, carries full result metadata
data: {"type":"done",
       "sources":[{"chapter":"Light","topic":"Photosynthesis","score":0.92}],
       "metrics":{},
       "metrics_adjustments":{},
       "cognitive_skills":{},
       "routed_chapter":"Light",
       "routed_topic":"Photosynthesis",
       "question_type":"curriculum",
       "quiz_suggestion":null,
       "yesterday_context":null,
       "pending_tasks":[]}

// Only sent on hard error
data: {"type":"error","detail":"..."}
```

**Frontend integration checklist:**
1. Store `session_id` from the `meta` event — pass it back on the next turn.
2. Accumulate `token` contents to show progressive text.
3. On `done`, show source citations, check `quiz_suggestion` to prompt a quiz.
4. If `is_session_start: true`, check `yesterday_context` for session-start banner.
5. **Call `POST /chat/session/end`** when user leaves the chat page.

---

### `POST /chat` (blocking)
Same as `/chat/stream` but returns the full response in one JSON block.
Use only for fallback / non-streaming clients.

**Response**
```jsonc
{
  "session_id":          "uuid",
  "answer":              "Photosynthesis is...",
  "sources":             [{"chapter":"...", "topic":"...", "score": 0.92}],
  "conversation_length": 3,
  "routed_chapter":      "Light",
  "routed_topic":        "Photosynthesis",
  "question_type":       "curriculum",
  "metrics":             {},
  "metrics_adjustments": {},
  "cognitive_skills":    {},
  "diagnostic_question": "",
  "is_session_start":    false,
  "quiz_suggestion":     null,
  "yesterday_context":   null,
  "pending_tasks":       []
}
```

---

### `POST /chat/session/end` ⭐ CRITICAL
**MUST be called** when the user leaves a chat page or closes the app.
Triggers Deep Session Sync (memory extraction, weak topics recalculation,
learning preferences update) in the background — non-blocking.

> **Why this matters:** Without calling this, student memory and cognitive
> profiles are NOT updated after the session.

**Request body**
```jsonc
{
  "conversation_id": "uuid",     // the session_id returned from /chat/stream
  "subject_id": 3                // numeric ID from GET /student/profile; null is OK
}
```

**Response**
```jsonc
{ "status": "success", "message": "Session deep sync queued." }
// or if session_id was "new"/empty:
{ "status": "skipped", "detail": "Empty or new conversation_id" }
```

---

### `POST /chat/feedback`
Saves a thumbs-up / thumbs-down rating on a single tutor message.

**Request body**
```jsonc
{
  "message_id":    "uuid",   // from GET /history/{session_id} → messages[].id
  "rating":        1,        // 1 = thumbs up | -1 = thumbs down | 0 = reset
  "feedback_text": "Great explanation!"  // optional
}
```

**Response:** `{ "status": "success", "rating": 1 }`

---

## 3. Sessions (`/sessions`)

### `GET /sessions`
Lists all past conversations for the authenticated student, newest first.

**Query params** (all optional)
| Param | Type | Description |
|---|---|---|
| `subject` | `string` | Filter by subject name |
| `study_space_id` | `string` | Filter by study space UUID |

**Response**
```jsonc
{
  "sessions": [
    {
      "id":              "uuid",
      "chat_title":      "Photosynthesis in Plants",
      "last_topic_name": "Photosynthesis",
      "created_at":      "2026-09-24T14:30:00Z",
      "subject":         "Science",
      "study_space_id":  null
    }
  ]
}
```

---

### `GET /history/{session_id}`
Returns the full message history for a session, with branching (edited messages).

**Response**
```jsonc
{
  "session_id": "uuid",
  "subject":    "Science",
  "title":      "Photosynthesis in Plants",
  "messages": [
    {
      "id":              "uuid",
      "role":            "user",       // "user" | "assistant"
      "content":         "What is photosynthesis?",
      "created_at":      "2026-09-24T14:30:00Z",
      "parent_id":       null,
      "has_siblings":    false,
      "sibling_ids":     [],
      "sources":         [],
      "content_blocks":  []
    }
  ]
}
```

---

### `DELETE /sessions/{session_id}`
Soft-deletes a session (sets `is_deleted = true`). Returns `{ "ok": true }`.

---

### `PATCH /sessions/{session_id}/title`
Updates the chat title manually.

**Request body:** `{ "title": "New title" }`  
**Response:** `{ "ok": true, "title": "New title" }`

---

### `POST /sessions/{session_id}/branch`
Creates an edited branch from a parent message (Claude-style regeneration).

**Request body**
```jsonc
{
  "parent_message_id": "uuid",  // the message to branch from
  "new_content":       "Can you explain it more simply?"
}
```

**Response:** `{ "branch_message_id": "uuid" }`

---

### `POST /sessions/{session_id}/metrics`
**Override** metric adjustments for a session (manual admin override).

**Request body:** `{ "metrics": { "concept_master_score": 5.0 } }`  
**Response:** `{ "status": "success" }`

---

## 4. Student (`/student`)

### `GET /student/profile`
Returns the student's basic identity and resolves a subject's numeric ID.

> **Frontend tip:** Call this on login, then cache `subject_id` in state
> and pass it as `subject_id` when calling `/chat/session/end`.

**Query params** (optional): `subject=Science`

**Response**
```jsonc
{
  "student_id":  "uuid",
  "username":    "riya_class10",
  "class_num":   10,
  "subject":     "Science",
  "subject_id":  3          // numeric — cache this; pass to /chat/session/end
}
```

---

### `GET /student/memory`
Returns cognitive metrics, computed skills, and persistent student memory.

**Query params** (optional): `subject=Science`

**Response**
```jsonc
{
  "metrics": {
    "concept_master_score":     72.5,
    "error_repetition_rate":    0.12,
    "attempt_persistence":      65.0,
    "struggle_recovery_rate":   58.0,
    "practice_intensity":       70.0,
    "learning_velocity":        55.0,
    "knowledge_retention":      68.0,
    "cognitive_thinking_level": 60.0,
    "engagement_frequency":     75.0,
    "assessment_accuracy":      63.0
  },
  "cognitive_skills": {
    "Concept Understanding":  74,
    "Learning Effort":        70,
    "Learning Adaptability":  60,
    "Knowledge Stability":    62,
    "Cognitive Depth":        60
  },
  "memory": "• Targeting 90% in board exams\n• Struggles with balancing equations"
}
```

---

### `POST /student/memory`
Manually add a persistent memory fact about the student.

**Request body**
```jsonc
{
  "subject": "Science",           // optional; associates fact with subject
  "fact":    "Student has exam on Monday"
}
```

**Response:** `{ "status": "success", "inserted": true, "fact": "..." }`

---

## 5. Quiz (`/quiz`)

### `POST /quiz/generate`
Generates a personalised MCQ + theory quiz adapted to the student's cognitive profile.

**Request body**
```jsonc
{
  "subject":       "Science",   // or leave null for auto-detect from last session
  "topic":         "Photosynthesis",  // or leave "" to auto-pick
  "session_id":    "uuid",      // optional; helps auto-detect subject/topic
  "source":        "manual",    // "manual" | "mid_concept" | "yesterday" | "spaced_review"
  "num_questions": 7            // 3–15
}
```

**Response**
```jsonc
{
  "attempt_id": "uuid",         // store this; required for /quiz/answer and /quiz/finish
  "subject":    "Science",
  "topic":      "Photosynthesis",
  "source":     "manual",
  "questions": [
    {
      "id":       42,           // question DB id; pass to /quiz/answer
      "q_index":  0,            // 0-based order
      "q_type":   "mcq",        // "mcq" | "theory"
      "question": "Which pigment is primarily responsible for photosynthesis?",
      "options":  ["Chlorophyll", "Melanin", "Carotene", "Xanthophyll"]
                                // empty array for theory questions
    }
  ]
}
```

---

### `POST /quiz/answer`
Submits the student's answer for a single question and gets instant feedback.

**Request body**
```jsonc
{
  "attempt_id":           "uuid",  // required — ownership verification
  "question_id":          42,      // from questions[].id above
  "student_answer":       "",      // theory: the text answer
  "student_answer_index": 0        // MCQ: 0-based option index (null for theory)
}
```

**Response**
```jsonc
{
  "is_correct":     true,
  "correct_index":  0,             // MCQ only; null for theory
  "correct_answer": null,          // theory only; null for MCQ
  "explanation":    "Chlorophyll absorbs red and blue light..."
}
```

---

### `POST /quiz/finish`
Finalises the attempt, computes score, updates cognitive profile and topic mastery.
Call this after all questions have been answered.

**Request body**
```jsonc
{
  "attempt_id": "uuid",
  "session_id": "uuid"   // optional; links quiz to the chat session
}
```

**Response**
```jsonc
{
  "attempt_id":     "uuid",
  "score":          85.7,
  "total":          7,
  "correct":        6,
  "passed":         true,           // score >= 60
  "topic":          "Photosynthesis",
  "subject":        "Science",
  "ai_feedback":    "Great work! You showed strong understanding of...",
  "metrics_impact": { "assessment_accuracy": 3.2, "concept_master_score": 2.1 }
}
```

---

### `GET /quiz/yesterday`
Returns the topic from yesterday's session for the session-start assignment banner.

**Response**
```jsonc
// If yesterday's context exists:
{ "has_context": true,  "context": { "subject": "Science", "topic": "Photosynthesis", "session_date": "2026-09-24" } }
// Otherwise:
{ "has_context": false, "context": null }
```

---

### `GET /quiz/history`
Returns past quiz attempt summaries.

**Query params** (optional): `subject=Science`

**Response**
```jsonc
{
  "attempts": [
    {
      "id":            "uuid",
      "subject":       "Science",
      "topic":         "Photosynthesis",
      "source":        "manual",
      "score":         85.7,
      "passed":        true,
      "num_questions": 7,
      "finished_at":   "2026-09-24T15:00:00Z",
      "created_at":    "2026-09-24T14:55:00Z"
    }
  ]
}
```

---

### `GET /quiz/feedback/{subject}`
Returns aggregated quiz stats and AI feedback for a subject.

**Path param:** `subject` = subject name, e.g. `Science`

**Response**
```jsonc
{
  "total_attempts":  5,
  "total_questions": 35,
  "total_correct":   28,
  "avg_score":       80.0,
  "mcq_accuracy":    85.7,
  "theory_accuracy": 72.5,
  "weak_topics":     ["Balancing Equations", "Ionic Bonding"],
  "strong_topics":   ["Photosynthesis", "Newton's Laws"],
  "ai_feedback":     "You have a strong grasp of biology but need more work on chemistry..."
}
```

---

## 6. Curriculum (`/curriculum`)

### `GET /curriculum/subjects`
Lists all available subjects for the student's class.

**Response**
```jsonc
{
  "subjects": [
    { "id": 3, "name": "Science", "display_name": "Science (Physics + Chemistry + Biology)" },
    { "id": 4, "name": "Mathematics", "display_name": "Mathematics" }
  ]
}
```

---

## 7. Study Spaces (`/spaces`)

Study Spaces group related conversations under a shared subject workspace.

### `GET /spaces`
Lists all study spaces for the user.

### `POST /spaces`
**Request body:** `{ "subject_id": 3, "title": "Exam Prep - Science", "custom_instructions": "Focus on NCERT examples only." }`

### `GET /spaces/{space_id}`
Returns a single space with its conversations.

### `PATCH /spaces/{space_id}`
Updates title or custom_instructions.

### `DELETE /spaces/{space_id}`
Archives the space (soft delete).

---

## 8. Attachments (`/attachments`)

### `POST /attachments/upload`
Uploads a file attachment (image, PDF) linked to a message.

**Content-Type:** `multipart/form-data`

**Form fields:**
| Field | Type |
|---|---|
| `file` | File binary |
| `message_id` | string (optional) |

**Response:** `{ "attachment_id": "uuid", "filename": "...", "url": "/uploads/..." }`

---

## 9. Real-Time Sync (`/sync`)

### `GET /sync/events`
SSE stream for real-time cross-device sync events (quiz completed on another device, etc.).

**Response** — `text/event-stream`
```jsonc
data: {"event": "quiz_completed", "data": { "score": 85.7, "topic": "Photosynthesis" }}
data: {"event": "memory_updated", "data": { "fact": "..." }}
```

---

## 10. Admin (`/admin`) — Server-Side Only

All admin endpoints require the `X-Admin-Key: <ADMIN_API_KEY>` header.
**Never expose this key in the frontend.**

### `POST /admin/ingest`
Ingests a PDF chapter into the curriculum database.

**Content-Type:** `multipart/form-data`

| Form field | Type | Example |
|---|---|---|
| `file` | File | `chapter1.pdf` |
| `board_name` | string | `NCERT` |
| `class_num` | int | `10` |
| `subject_name` | string | `Science` |
| `book_title` | string | `Science for Class 10` |
| `book_natural_key` | string | `NCERT_10_Science_en_2023` |
| `chapter_title` | string | `Chemical Reactions and Equations` |
| `chapter_number` | int | `1` |

**Response**
```jsonc
{
  "status":               "complete",   // complete | partial | needs_review | failed
  "sections_ingested":    12,
  "blocks_stored":        48,
  "chapter_id":           7,
  "message":              "Ingested 48 blocks from 12 section(s).",
  "warnings":             [],
  "ingestion_confidence": 0.94,
  "coverage":             { "total_pages": 22, "ocr_pages": [] }
}
```

### `GET /admin/ingestion-log`
Query ingestion history.

**Query params:** `book_natural_key`, `status`, `limit` (default 50)

---

## 11. Health Check

### `GET /health`
No auth required.

**Response:** `{ "status": "ok", "version": "2.0.0" }`

---

## Error Codes

| HTTP Code | Meaning |
|---|---|
| `400` | Bad request / validation error |
| `401` | Missing, expired, or invalid JWT |
| `403` | Access denied (resource belongs to another user) |
| `404` | Resource not found |
| `422` | Request body validation failed (FastAPI) |
| `429` | Rate limit exceeded (30 req/min for chat, 10 for session/end) |
| `500` | Internal server error |

All error responses follow this schema:
```jsonc
{ "detail": "Human-readable error message" }
```

---

## Frontend Integration Checklist

### On Login / Register
- [ ] Store `access_token` (in-memory or short-lived storage)
- [ ] Store `refresh_token` (secure, httpOnly cookie preferred)
- [ ] Call `GET /student/profile?subject=<subject>` → cache `subject_id`
- [ ] Call `GET /quiz/yesterday` → show assignment banner if `has_context: true`

### In Chat
- [ ] Connect to `POST /chat/stream` with EventSource or `fetch + ReadableStream`
- [ ] Capture `session_id` from the `meta` event; store it for this chat tab
- [ ] Accumulate `token` events to render streamed text
- [ ] On `done`: show source chips, check `quiz_suggestion`, update topic breadcrumb
- [ ] Silently refresh token when 401 is received (use `/auth/refresh`)

### On Leaving Chat
- [ ] Call `POST /chat/session/end` with `conversation_id` + cached `subject_id`
- [ ] This MUST fire even if the user closes the tab (use `navigator.sendBeacon` or `visibilitychange`)

### For Quiz
- [ ] `/quiz/generate` → store `attempt_id`
- [ ] `/quiz/answer` for each question
- [ ] `/quiz/finish` after last question → show score + AI feedback

### Token Refresh Strategy
```javascript
// Pseudo-code
async function apiCall(url, options) {
  let res = await fetch(url, { ...options, headers: { Authorization: `Bearer ${accessToken}` } });
  if (res.status === 401) {
    const { access_token } = await fetch('/auth/refresh', {
      method: 'POST', body: JSON.stringify({ refresh_token: storedRefreshToken })
    }).then(r => r.json());
    accessToken = access_token;
    res = await fetch(url, { ...options, headers: { Authorization: `Bearer ${accessToken}` } });
  }
  return res;
}
```

---

## Key Data Types

| Field | DB Type | API Type | Notes |
|---|---|---|---|
| `user_id` / `student_id` | `UUID` | `string` | Always a UUID string |
| `subject_id` | `Integer` | `number` | Numeric FK; resolve via `/student/profile` |
| `session_id` / `conversation_id` | `UUID` | `string` | Chat session UUID |
| `attempt_id` | `UUID` | `string` | Quiz attempt UUID |
| `question_id` | `Integer` | `number` | Sequential int within attempt |
| `class_num` | `Integer` | `number` | 6–12 |
| `score` | `Float` | `number` | 0.0–100.0 |
| `rating` | `Integer` | `number` | -1 | 0 | 1 |
| `is_correct` | `Boolean` | `boolean` | |
| Metric values | `Float` | `number` | 0–100 (except `error_repetition_rate` = 0.0–1.0) |

---

## CORS

Origins allowed are configured via `ALLOWED_ORIGINS` env var.
Requests from `http://localhost:3000` and `http://localhost:5173` are allowed in development.
Always include `credentials: 'include'` if using cookies for refresh token.

---

*Generated 2026-09-25 by Antigravity | VishwAlpha v2.0*
