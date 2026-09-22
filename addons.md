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


*Last updated: 2026-09-22. All deferred features have schema stubs already built in Phase 2.*

---

## 10. Ingestion Pipeline — Phase 9 Status (Updated 2026-09-22)

> **Pipeline is now a full 17-stage Trust Pipeline.**
> Files touched: `app/services/ingestion_pipeline.py`, `app/api/admin.py`, `app/schemas/legacy.py`, `app/infra/redis_cache.py`, `app/data/models/content.py`, `app/data/migrations/versions/008_ingestion_enhancements.py`

---

### ✅ DONE — All implemented and import-verified

| # | Item | File | Status |
|---|------|------|--------|
| 1 | `admin.py` process_pdf() call signature fix | `app/api/admin.py` | ✅ Done |
| 2 | `IngestRequest` 8-field schema | `app/schemas/legacy.py` | ✅ Done |
| 3 | `IngestResponse` with blocks_stored, chapter_id, warnings | `app/schemas/legacy.py` | ✅ Done |
| 4 | MIME / magic-byte security check (`%PDF-`) | `ingestion_pipeline.py` Stage 0 | ✅ Done |
| 5 | File validation (size, encryption, pages) | `ingestion_pipeline.py` Stage 2 | ✅ Done |
| 6 | PDF metadata inspection | `ingestion_pipeline.py` Stage 3 | ✅ Done |
| 7 | SHA-256 duplicate detection → Redis | `ingestion_pipeline.py` Stage 4 | ✅ Done |
| 8 | BookIngestionLog create (in_progress) | `ingestion_pipeline.py` Stage 5 | ✅ Done |
| 9 | Per-page layout analysis (paddlex) | `ingestion_pipeline.py` Stage 6 | ✅ Done |
| 10 | OCR with per-word confidence scoring | `ingestion_pipeline.py` Stage 6 | ✅ Done |
| 11 | Math-region OCR (PSM 6 + error fixes) | `ingestion_pipeline.py` Stage 6 | ✅ Done |
| 12 | Table-region OCR → markdown table | `ingestion_pipeline.py` Stage 6 | ✅ Done |
| 13 | Header/footer stripping (frequency-based) | `ingestion_pipeline.py` Stage 7 | ✅ Done |
| 14 | Watermark removal | `ingestion_pipeline.py` Stage 8 | ✅ Done |
| 15 | Cross-page sentence stitching | `ingestion_pipeline.py` Stage 9 | ✅ Done |
| 16 | Prompt-injection sanitisation | `ingestion_pipeline.py` Stage 10 | ✅ Done |
| 17 | Structure detection (Chapter/Topic/Subtopic regex) | `ingestion_pipeline.py` Stage 11 | ✅ Done |
| 18 | LLM fallback for unstructured text | `ingestion_pipeline.py` Stage 11 | ✅ Done |
| 19 | LLM enrichment (summary/keywords/prerequisites) | `ingestion_pipeline.py` Stage 11b | ✅ Done |
| 20 | Redis-cached LLM structuring (MD5, 30-day TTL) | `app/infra/redis_cache.py` | ✅ Done |
| 21 | Content deduplication (MD5 per sub-chunk) | `ingestion_pipeline.py` Stage 13 | ✅ Done |
| 22 | Quality gate 0.0–1.0 per section | `ingestion_pipeline.py` Stage 14 | ✅ Done |
| 23 | DB write with block_type, ocr_confidence, content_hash | `ingestion_pipeline.py` Stage 15 | ✅ Done |
| 24 | BookIngestionLog update (coverage JSON, confidence, status) | `ingestion_pipeline.py` Stage 16 | ✅ Done |
| 25 | Redis cache invalidation post-ingest | `ingestion_pipeline.py` Stage 17 | ✅ Done |
| 26 | Migration 008 (new columns) applied to DB | `008_ingestion_enhancements.py` | ✅ Done |
| 27 | ORM updated (enriched_prerequisites, ocr_confidence, content_hash) | `app/data/models/content.py` | ✅ Done |
| 28 | `invalidate_subject()` on RetrievalCache | `app/infra/redis_cache.py` | ✅ Done |

---

### ❌ NOT STARTED — Do next session (in priority order)

#### Priority 1 — Complete the admin API surface
**File:** `app/api/admin.py`
Add `GET /admin/ingestion-log` endpoint:
```python
@router.get("/ingestion-log", response_model=list[IngestLogResponse])
def get_ingestion_log(book_natural_key: str, _=Depends(verify_admin_key)):
    with managed_session() as db:
        book = db.query(Book).filter(Book.natural_key == book_natural_key).first()
        if not book: raise HTTPException(404)
        logs = db.query(BookIngestionLog).filter(
            BookIngestionLog.book_id == book.id
        ).order_by(BookIngestionLog.ingested_at.desc()).limit(20).all()
        return logs
```

**File:** `app/schemas/legacy.py`
Add `IngestLogResponse` schema:
```python
class IngestLogResponse(BaseModel):
    id: int
    book_id: int
    chapter_number: int | None = None
    pdf_hash: str
    status: str
    ingestion_confidence: float | None = None
    coverage: dict | None = None
    error: str | None = None
    ingested_at: datetime
    finished_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)
```

#### Priority 2 — Update CLI script
**File:** `scripts/ingest.py`
Currently prints old 5-field dict. Update to print:
- `status`, `ingestion_confidence`, `blocks_stored`, `sections_ingested`
- Full `coverage` dict (total/processed/ocr/failed pages)
- `warnings` list
- Log the `BookIngestionLog` ID for tracking

#### Priority 3 — Retrieval metadata filtering (curriculum mismatch prevention)
**File:** `app/services/retrieval_service.py`
Current: retrieval uses only cosine similarity (can leak wrong board/class content).
Required: filter vector search by `book.subject.class.board_id + class_level + subject_id`.
Implementation: add WHERE clause to the pgvector query joining through the hierarchy.

#### Priority 4 — Automated test suite
**Directory:** `tests/`
- `test_ingestion_pipeline.py`: fixture PDFs for text, image-only, encrypted, duplicate, injection, multi-column
- `test_ingestion_stages.py`: unit tests for MIME check, header strip, cross-page stitch, structure detect, equation detect
- `test_schema_integrity.py`: ORM column existence checks
- `test_retrieval_filtering.py`: verify board/class filtering

#### Priority 5 — RAG confidence gate for ingestion status
**File:** `app/services/retrieval_service.py`
Before using a ContentBlock in retrieval, check its chapter's `BookIngestionLog.status`.
If status is `needs_review` or `failed`, surface a warning in the RAG response.
This prevents a bad scan from teaching students incorrect information.

---

### Architecture invariants (never break)
- `BookIngestionLog.status = complete` requires: all pages processed + no failed_pages + confidence ≥ 0.7
- Knowledge confidence ≠ Learner-state confidence (never mix)
- Low-confidence ingestion → NEVER directly update student cognitive profile
- RAG must not use content from `needs_review` / `failed` chapters silently

```python
# NEW call in admin.py
result = pipeline.process_pdf(
    pdf_path=request.pdf_path,
    board_name=request.board_name,
    class_num=request.class_num,
    subject_name=request.subject_name,
    book_title=request.book_title,
    book_natural_key=request.book_natural_key,
    chapter_title=request.chapter_title,
    chapter_number=request.chapter_number,
)
```

#### Fix 2: `IngestRequest` schema — add missing fields
**File:** `app/schemas/legacy.py`
```python
class IngestRequest(BaseModel):
    pdf_path:         str = Field(description="Path to PDF relative to DataSet/")
    board_name:       str = Field(default="NCERT")
    class_num:        int = Field(ge=6, le=12)
    subject_name:     str
    book_title:       str
    book_natural_key: str = Field(description="Unique key e.g. NCERT_10_Science_en_2023")
    chapter_title:    str
    chapter_number:   int = Field(ge=1)
```

#### Fix 3: `IngestResponse` schema — add missing fields
**File:** `app/schemas/legacy.py`
```python
class IngestResponse(BaseModel):
    status:            str
    sections_ingested: int = 0
    blocks_stored:     int = 0
    chapter_id:        int | None = None
    message:           str = ""
    warnings:          list[str] = []
```

---

### 🟠 High — Safety / Trust Pipeline

#### Fix 4: File validation before extraction
**File:** `app/services/ingestion_pipeline.py` — add to `process_pdf()` before `_extract_text()`
```python
MAX_PDF_BYTES = 100 * 1024 * 1024  # 100 MB

def _validate_pdf(self, pdf_path: str) -> list[str]:
    """Returns list of warning strings. Raises on fatal errors."""
    warnings = []
    size = os.path.getsize(pdf_path)
    if size > MAX_PDF_BYTES:
        raise ValueError(f"PDF too large: {size / 1e6:.1f} MB (max 100 MB)")
    
    reader = PdfReader(pdf_path)
    if reader.is_encrypted:
        raise ValueError("PDF is encrypted/password-protected")
    if len(reader.pages) == 0:
        raise ValueError("PDF has no pages")
    if len(reader.pages) > 500:
        warnings.append(f"Large PDF: {len(reader.pages)} pages — may be slow")
    return warnings
```

#### Fix 5: Duplicate PDF detection (hash-based)
**File:** `app/services/ingestion_pipeline.py`
```python
import hashlib

def _pdf_sha256(pdf_path: str) -> str:
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

# In process_pdf(), before extraction:
# Store/check hash in a DB table or Redis key:
#   key = f"ingested:pdf:{sha256_hash}"
# If exists → return {"status": "duplicate", ...}
```

#### Fix 6: Prompt-injection sanitisation
**File:** `app/services/ingestion_pipeline.py` — run on every page before LLM call
```python
import re

_INJECTION_PATTERNS = re.compile(
    r"(ignore previous instructions|system:|<\|im_start\|>|<\|endoftext\|>)",
    re.IGNORECASE,
)

def _sanitise(self, text: str) -> str:
    """Strip known LLM injection patterns from extracted text."""
    return _INJECTION_PATTERNS.sub("[REDACTED]", text)
```
Apply: `raw_text = self._sanitise(raw_text)` after extraction, before chunking.

#### Fix 7: OCR fallback for image-only pages (`pytesseract`)
**File:** `app/services/ingestion_pipeline.py`  
**Dependency to add:** `pytesseract`, `pdf2image`, `Pillow`
```python
# pip install pytesseract pdf2image Pillow
# Also needs: apt install tesseract-ocr poppler-utils (or Windows equivalents)
from pdf2image import convert_from_path
import pytesseract

def _extract_text(self, pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        # If page yields < 50 chars of text, assume image — run OCR
        if len(text.strip()) < 50:
            logger.info(f"[Ingestion] Page {i+1} is image-only — running OCR")
            images = convert_from_path(pdf_path, first_page=i+1, last_page=i+1, dpi=300)
            for img in images:
                text = pytesseract.image_to_string(img, lang="eng")
        pages.append(text)
    return "\n\n".join(pages)
```

#### Fix 8: Confidence gate before embedding
**File:** `app/services/ingestion_pipeline.py`  
After `_structure_chunk()`, score each section before committing to DB.
```python
MIN_SECTION_CHARS = 100  # sections shorter than this are low-confidence
MIN_SECTIONS_PER_CHUNK = 1

def _score_section(self, section: dict) -> float:
    """Returns 0.0–1.0 quality score for a section."""
    text = section.get("repaired_text", "")
    heading = section.get("heading", "")
    score = 1.0
    if len(text) < MIN_SECTION_CHARS:
        score -= 0.5
    if not heading or heading.lower() in ("general", "untitled", ""):
        score -= 0.3
    return max(0.0, score)

# In process_pdf() loop:
for section in all_sections:
    conf = self._score_section(section)
    if conf < 0.5:
        logger.warning(f"[Ingestion] Low-confidence section '{section.get('heading')}' — skipping")
        result["warnings"].append(f"Skipped low-confidence section: {section.get('heading')}")
        continue
    # ... proceed to upsert
```

#### Fix 9: Redis cache invalidation after ingestion
**File:** `app/services/ingestion_pipeline.py` — add to the end of `process_pdf()`
```python
from app.infra.redis_cache import RetrievalCache

# After DB writes succeed:
try:
    cache = RetrievalCache()
    cache.invalidate_subject(class_num=class_num, subject=subject_name)
    logger.info("[Ingestion] Redis retrieval cache invalidated")
except Exception as e:
    logger.warning(f"[Ingestion] Cache invalidation failed (non-fatal): {e}")
```
Also add `invalidate_subject(class_num, subject)` method to `RetrievalCache` that deletes keys matching `retrieval:{class_num}:{subject}:*`.

---

### 🟡 Medium — Quality Improvements

#### Fix 10: Redis-cached LLM structuring prompt
**File:** `app/services/ingestion_pipeline.py`  
The `_structure_chunk()` LLM call is expensive. Cache by content hash.
```python
import hashlib, json
from app.infra.redis_cache import RetrievalCache

def _structure_chunk(self, text: str, chapter: str) -> dict | None:
    cache_key = f"ingest:struct:{hashlib.md5((chapter + text).encode()).hexdigest()}"
    cache = RetrievalCache()
    cached = cache._r.get(cache_key)        # raw redis get
    if cached:
        return json.loads(cached)
    
    # ... LLM call as before ...
    result = json.loads(resp.choices[0].message.content.strip())
    cache._r.setex(cache_key, 60 * 60 * 24 * 30, json.dumps(result))  # 30-day TTL
    return result
```

#### Fix 11: Rich enrichment (summary + keywords + prerequisites)
**File:** `app/services/ingestion_pipeline.py`  
Extend `_structure_chunk()` prompt to return enrichment data. The `ProcessedSection` schema already exists in `legacy.py`.
```json
{
  "sections": [{
    "heading": "...",
    "repaired_text": "...",
    "summary": "2-3 sentence summary for retrieval",
    "keywords": ["osmosis", "concentration gradient"],
    "prerequisites": ["Cell structure", "Diffusion"]
  }]
}
```
Store `summary` in `ContentBlock.summary` (add column), `keywords` + `prerequisites` in `ContentBlock.metadata` JSONB.

#### Fix 12: Semantic chunking (replace hard char splits)
**File:** `app/services/ingestion_pipeline.py`  
Replace `raw_text[i:i+4000]` and `repaired[j:j+800]` with sentence-boundary splits using `nltk.sent_tokenize` or splitting on `\n\n` (paragraph boundaries).
```python
import nltk

def _sentence_chunks(self, text: str, max_chars: int = 800) -> list[str]:
    sentences = nltk.sent_tokenize(text)
    chunks, current = [], ""
    for s in sentences:
        if len(current) + len(s) > max_chars and current:
            chunks.append(current.strip())
            current = s
        else:
            current += " " + s
    if current.strip():
        chunks.append(current.strip())
    return chunks
```

#### Fix 13: Add `IngestJob` tracking table (future)
Track per-ingestion status so admin can poll progress.
```sql
CREATE TABLE ingest_jobs (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pdf_path     text NOT NULL,
  status       varchar(20) NOT NULL DEFAULT 'pending',  -- pending/running/done/failed
  chapter_id   int REFERENCES chapters(id),
  blocks_stored int DEFAULT 0,
  warnings     jsonb DEFAULT '[]',
  error        text,
  started_at   timestamptz DEFAULT now(),
  finished_at  timestamptz
);
```

---

### 🟢 Low — Future Nice-to-Haves

- **Table extraction** using `pdfplumber` — preserve row/column structure
- **Figure captioning** — pass page images to GPT-4o vision for alt-text
- **Multi-column reading order** — `pdfplumber` `extract_words(x_tolerance=...)` can reconstruct reading order
- **Edition/board validation** — check caller-supplied board/class against known curriculum tree
- **Automated test suite** — `test_ingestion_pipeline.py` with fixture PDFs

---

*Ingestion backlog added: 2026-09-22.*
