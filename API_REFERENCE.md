# VishwAlpha AI Tutor — API Reference

**Base URL:** `http://localhost:8000`  
**Version:** 1.0.0  
**Auth:** No token-based auth is currently enforced. All endpoints accept `student_id` (UUID) as a query param or in the request body to identify the user.

> **Interactive Docs:** Once the server is running, visit `http://localhost:8000/docs` for the auto-generated Swagger UI, or `http://localhost:8000/redoc` for ReDoc.

---

## Table of Contents

1. [Auth](#1-auth)
   - POST /auth/register
   - POST /auth/login
2. [Chat](#2-chat)
   - POST /chat
3. [Sessions](#3-sessions)
   - GET /sessions
   - GET /history/{session_id}
   - GET /sessions/{session_id}/remark
4. [Student Profile & Metrics](#4-student-profile--metrics)
   - GET /student/profile
   - GET /student/memory
   - POST /session/{session_id}/metrics
5. [Curriculum Browser](#5-curriculum-browser)
   - GET /curriculum/subjects
   - GET /curriculum/chapters
   - GET /curriculum/topics

---

## 1. Auth

### `POST /auth/register`

Registers a new student account and initialises their cognitive profile in the database.

**Request Body** (`application/json`)

```json
{
  "username": "rahul_class10",
  "email": "rahul@example.com",
  "password": "securepassword123",
  "class_num": 10
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `username` | string | YES | Unique username |
| `email` | string | YES | Unique email address |
| `password` | string | YES | Plain-text password (hashed server-side with PBKDF2) |
| `class_num` | integer | YES | Student's class number (e.g. `10`) |

**Response `200 OK`**

```json
{
  "student_id": "187c9036-f6f9-40b5-854d-36748479ced9",
  "username": "rahul_class10",
  "class_num": 10,
  "message": "Registration successful"
}
```

**Error Responses**

| Code | Reason |
|---|---|
| `400` | Username or email already exists |

---

### `POST /auth/login`

Authenticates a student by username and password.

**Request Body** (`application/json`)

```json
{
  "username": "rahul_class10",
  "password": "securepassword123"
}
```

**Response `200 OK`**

```json
{
  "student_id": "187c9036-f6f9-40b5-854d-36748479ced9",
  "username": "rahul_class10",
  "class_num": 10,
  "message": "Login successful"
}
```

> Store `student_id` on the client. Every subsequent API call requires it. It is the student's permanent unique identifier.

**Error Responses**

| Code | Reason |
|---|---|
| `401` | Invalid username or password |

---

## 2. Chat

### `POST /chat`

The core tutoring endpoint. Sends a student's question and receives an AI-generated tutoring answer. Internally classifies the question, optionally retrieves relevant NCERT curriculum content (via pgvector), and generates a personalised response.

**Request Body** (`application/json`)

```json
{
  "student_id": "187c9036-f6f9-40b5-854d-36748479ced9",
  "session_id": "",
  "question": "What is photosynthesis?",
  "subject": "Science",
  "class_num": 10,
  "tutor_mode": "standard"
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `student_id` | string (UUID) | YES | — | The logged-in student's ID |
| `session_id` | string (UUID) | NO | `""` | Pass an existing session UUID to continue a conversation. Leave empty to start a new session. |
| `question` | string | YES | — | The student's question or message |
| `subject` | string | NO | `"Science"` | The subject being studied (e.g. `"Science"`, `"Mathematics"`, `"Social Science"`) |
| `class_num` | integer | NO | Resolved from DB | The student's class number. If omitted, resolved from their registered profile. |
| `tutor_mode` | string | NO | `"standard"` | `"standard"` = direct answer. `"deep"` = Socratic diagnostic mode. |

**Response `200 OK`**

```json
{
  "session_id": "a1b2c3d4-...",
  "answer": "**Photosynthesis** is the process by which green plants...",
  "sources": [
    {
      "chapter": "Life Processes",
      "topic": "Nutrition in Plants",
      "score": 0.847
    }
  ],
  "conversation_length": 2,
  "routed_chapter": "Life Processes",
  "routed_topic": "Nutrition in Plants",
  "question_type": "curriculum",
  "metrics": {},
  "metrics_adjustments": {},
  "cognitive_skills": {
    "concept_understanding": 65.3,
    "learning_effort": 69.0,
    "learning_adaptability": 67.5,
    "knowledge_stability": 59.0,
    "cognitive_depth": 45.0
  },
  "diagnostic_question": "",
  "is_session_start": false,
  "pending_tasks": []
}
```

| Field | Type | Description |
|---|---|---|
| `session_id` | string | The session UUID. Store this and pass it back on subsequent questions in the same conversation. |
| `answer` | string | The AI-generated tutoring answer (Markdown format) |
| `sources` | array | NCERT curriculum chunks used to generate the answer. Each has `chapter`, `topic`, `score` (0–1 cosine similarity). |
| `conversation_length` | integer | Total number of messages in this session |
| `routed_chapter` | string | Chapter matched by the semantic router |
| `routed_topic` | string | Specific topic matched by the semantic router |
| `question_type` | string | `"curriculum"` = answered from textbook, `"conversational"` = general chat, `"deep_diagnostic"` = Socratic question asked back, `"deep_explanation"` = Socratic explanation given |
| `metrics` | object | Raw cognitive tracking scores (updated every 4 turns) |
| `metrics_adjustments` | object | Delta changes to each metric after this turn batch |
| `cognitive_skills` | object | High-level derived skills (all `0–100`) |
| `diagnostic_question` | string | In deep mode Phase 1, contains the Socratic question asked back to the student |
| `pending_tasks` | array | Assigned study tasks for the student |

**Deep Mode (Socratic) Flow:**
1. First call returns `question_type: "deep_diagnostic"` + `diagnostic_question` — display this to the student.
2. Student replies. Pass `tutor_mode: "deep"` again with the same `session_id`. The tutor now evaluates their answer and explains accordingly.

**Error Responses**

| Code | Reason |
|---|---|
| `400` | Question is empty |
| `500` | Internal LLM or database error |

---

## 3. Sessions

### `GET /sessions`

Returns a list of all past conversation sessions for a student and subject, ordered most-recent first.

**Query Parameters**

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `student_id` | string (UUID) | YES | — | The student's ID |
| `subject` | string | NO | `"Science"` | Filter sessions by subject |

**Example Request**
```
GET /sessions?student_id=187c9036-...&subject=Science
```

**Response `200 OK`**

```json
{
  "sessions": [
    {
      "id": "a1b2c3d4-e5f6-...",
      "created_at": "2026-09-19T12:00:00",
      "updated_at": "2026-09-19T12:45:00",
      "message_count": 14
    }
  ]
}
```

---

### `GET /history/{session_id}`

Returns the full conversation history and metadata for a specific session.

**Path Parameter**

| Param | Type | Required | Description |
|---|---|---|---|
| `session_id` | string (UUID) | YES | The session ID to retrieve |

**Example Request**
```
GET /history/a1b2c3d4-e5f6-...
```

**Response `200 OK`**

```json
{
  "session_id": "a1b2c3d4-...",
  "memory_summary": "Student asked about photosynthesis and light reactions...",
  "recent_messages": [
    { "role": "student", "content": "What is photosynthesis?" },
    { "role": "tutor",   "content": "**Photosynthesis** is the process..." }
  ],
  "total_messages": 14,
  "metrics": {}
}
```

| Field | Type | Description |
|---|---|---|
| `memory_summary` | string | AI-compressed summary of older turns in the conversation |
| `recent_messages` | array | Last 4 messages (2 turn pairs) verbatim. Each has `role` (`"student"` or `"tutor"`) and `content`. |
| `total_messages` | integer | Total messages in the session |
| `metrics` | object | Student's raw cognitive scores at the time of the last update |

**Error Responses**

| Code | Reason |
|---|---|
| `404` | Session not found or has no messages |

---

### `GET /sessions/{session_id}/remark`

Returns the latest AI-generated teacher-style performance remark for a session. Remarks are generated automatically every 4 turns.

**Path Parameter**

| Param | Type | Required | Description |
|---|---|---|---|
| `session_id` | string (UUID) | YES | The session ID |

**Example Request**
```
GET /sessions/a1b2c3d4-.../remark
```

**Response `200 OK`**

```json
{
  "remark": "Student shows strong recall ability but struggles with application-level questions. Recommend more practice problems."
}
```

Returns `{ "remark": "" }` if no remark has been generated yet (happens after every 4 turns).

---

## 4. Student Profile & Metrics

### `GET /student/profile`

Returns the student's cognitive profile: raw tracking metrics and derived high-level cognitive skills.

> Cached for 5 seconds per `(student_id, subject)` pair to reduce DB polling load.

**Query Parameters**

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `student_id` | string (UUID) | YES | — | The student's ID |
| `subject` | string | NO | `"Science"` | Subject to get the profile for |

**Response `200 OK`**

```json
{
  "metrics": {
    "concept_master_score": 62.5,
    "error_repetition_rate": 0.15,
    "attempt_persistence": 70.0,
    "struggle_recovery_rate": 55.0,
    "practice_intensity": 65.0,
    "learning_velocity": 58.0,
    "knowledge_retention": 60.0,
    "cognitive_thinking_level": 45.0,
    "engagement_frequency": 72.0,
    "assessment_accuracy": 68.0
  },
  "cognitive_skills": {
    "concept_understanding": 65.3,
    "learning_effort": 69.0,
    "learning_adaptability": 67.5,
    "knowledge_stability": 59.0,
    "cognitive_depth": 45.0
  }
}
```

**Raw Metrics Reference**

| Metric | Range | Description |
|---|---|---|
| `concept_master_score` | 0–100 | Overall textbook concept understanding |
| `error_repetition_rate` | 0–1 | Rate of repeated mistakes (lower is better) |
| `attempt_persistence` | 0–100 | Willingness to try harder questions |
| `struggle_recovery_rate` | 0–100 | Recovery after getting something wrong |
| `practice_intensity` | 0–100 | Frequency and depth of practice questions asked |
| `learning_velocity` | 0–100 | Speed of absorbing new concepts |
| `knowledge_retention` | 0–100 | Long-term retention of discussed topics |
| `cognitive_thinking_level` | 0–100 | Bloom's Taxonomy stage (0–20=Recall, 21–40=Understand, 41–60=Apply, 61–80=Analyze, 81+=Evaluate/Create) |
| `engagement_frequency` | 0–100 | How regularly the student engages with the tutor |
| `assessment_accuracy` | 0–100 | Correctness of answers when evaluated |

**Cognitive Skills Reference** (derived, high-level)

| Skill | Description |
|---|---|
| `concept_understanding` | Derived from `concept_master_score` + `assessment_accuracy` |
| `learning_effort` | Derived from `practice_intensity`, `attempt_persistence`, `engagement_frequency` |
| `learning_adaptability` | Derived from `struggle_recovery_rate` and inverse of `error_repetition_rate` |
| `knowledge_stability` | Derived from `knowledge_retention` + `learning_velocity` |
| `cognitive_depth` | Maps directly to `cognitive_thinking_level` (Bloom's stage) |

---

### `GET /student/memory`

Returns the student's persistent learning memory — a list of AI-curated facts about the student that persist across sessions.

> Cached for 5 seconds per `(student_id, subject)` pair.

**Query Parameters**

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `student_id` | string (UUID) | YES | — | The student's ID |
| `subject` | string | NO | `"Science"` | Subject context |

**Response `200 OK`**

```json
{
  "memory": [
    "Student prefers step-by-step explanations for complex processes.",
    "Struggles with application-level problems involving pH calculations.",
    "Shows strong recall ability for definitions and terminology.",
    "Tends to ask follow-up questions, indicating high engagement."
  ]
}
```

Returns `{ "memory": [] }` if no memory entries have been built yet (built automatically after every 4 turns).

---

### `POST /session/{session_id}/metrics`

Manually override a student's cognitive metrics, either with raw values or a named preset profile. Useful for teacher intervention, testing, or resetting a student's tracked state.

**Path Parameter**

| Param | Type | Required | Description |
|---|---|---|---|
| `session_id` | string (UUID) | YES | An active session ID (resolves the student and subject) |

**Option A — Apply a preset profile**

```json
{
  "profile_name": "Fast Learner"
}
```

Available profiles:
- `"Standard"` — Neutral baseline (all metrics at ~50)
- `"Struggling but Persistent"` — Low concept mastery, high persistence
- `"Fast Learner"` — High metrics across the board
- `"Casual"` — Low engagement, average understanding

**Option B — Set specific metric values**

```json
{
  "metrics": {
    "concept_master_score": 75.0,
    "error_repetition_rate": 0.1,
    "attempt_persistence": 80.0
  }
}
```

Only provide the metrics you want to change. All others retain their current value.

**Response `200 OK`**

```json
{
  "status": "success",
  "message": "Applied profile 'Fast Learner'",
  "metrics": {
    "concept_master_score": 85.0
  }
}
```

**Error Responses**

| Code | Reason |
|---|---|
| `400` | Neither `metrics` nor `profile_name` provided |
| `404` | Session not found |
| `500` | Internal error |

---

## 5. Curriculum Browser

These endpoints let the frontend dynamically populate dropdowns for the student to choose their subject, chapter, and topic. They read from the `curriculum_routing` table which is populated during content ingestion.

### `GET /curriculum/subjects`

Returns all subjects available for a given class.

**Query Parameters**

| Param | Type | Required | Description |
|---|---|---|---|
| `class_num` | integer | YES | The class number (e.g. `10`) |

**Example:** `GET /curriculum/subjects?class_num=10`

**Response `200 OK`**
```json
{ "subjects": ["Science", "Mathematics", "Social Science"] }
```

---

### `GET /curriculum/chapters`

Returns all chapters available for a given class and subject.

**Query Parameters**

| Param | Type | Required | Description |
|---|---|---|---|
| `class_num` | integer | YES | The class number |
| `subject` | string | YES | Subject name (case-insensitive) |

**Example:** `GET /curriculum/chapters?class_num=10&subject=Science`

**Response `200 OK`**
```json
{
  "chapters": [
    "Life Processes",
    "Acids, Bases and Salts",
    "Chemical Reactions and Equations"
  ]
}
```

---

### `GET /curriculum/topics`

Returns all topics available for a given class, subject, and chapter.

**Query Parameters**

| Param | Type | Required | Description |
|---|---|---|---|
| `class_num` | integer | YES | The class number |
| `subject` | string | YES | Subject name (case-insensitive) |
| `chapter` | string | YES | Chapter name (case-insensitive) |

**Example:** `GET /curriculum/topics?class_num=10&subject=Science&chapter=Life+Processes`

**Response `200 OK`**
```json
{
  "topics": [
    "Nutrition in Plants",
    "Nutrition in Animals",
    "Respiration",
    "Transportation",
    "Excretion"
  ]
}
```

---

## Recommended Frontend Integration Flow

```
1. App Load
   └── GET /curriculum/subjects?class_num=10  →  populate subject dropdown

2. Registration
   └── POST /auth/register  →  save returned student_id locally

3. Login
   └── POST /auth/login  →  save student_id and class_num locally

4. Dashboard / Subject Change
   ├── GET /curriculum/chapters?class_num={n}&subject={s}
   ├── GET /student/profile?student_id={id}&subject={s}
   └── GET /student/memory?student_id={id}&subject={s}

5. Load Past Sessions List (sidebar)
   └── GET /sessions?student_id={id}&subject={s}

6. Resume a Past Session
   └── GET /history/{session_id}  →  render messages, load metrics

7. Send a Chat Message
   └── POST /chat
       Body: { student_id, session_id, question, subject, tutor_mode }
       └── Save returned session_id for subsequent messages

8. After Each Chat Response (refresh UI)
   ├── Display updated cognitive_skills from the /chat response directly
   ├── GET /sessions/{session_id}/remark  →  update remarks panel
   └── GET /student/profile  →  refresh metrics bars (cached, fast)

9. Teacher / Admin Override
   └── POST /session/{session_id}/metrics
       Body: { profile_name: "Fast Learner" }  OR  { metrics: { ... } }
```

---

## Data Types Quick Reference

| Type | Format | Example |
|---|---|---|
| `student_id` | UUID v4 string | `"187c9036-f6f9-40b5-854d-36748479ced9"` |
| `session_id` | UUID v4 string | `"a1b2c3d4-e5f6-7890-abcd-ef1234567890"` |
| `subject` | string (case-insensitive) | `"Science"`, `"Mathematics"` |
| `class_num` | integer | `8`, `9`, `10` |
| `tutor_mode` | enum string | `"standard"` or `"deep"` |
| Raw metrics | float | `0.0–100.0` (except `error_repetition_rate`: `0.0–1.0`) |
| Cognitive skills | float | `0.0–100.0` |
