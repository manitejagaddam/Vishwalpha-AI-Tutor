# PDF Ingestion Pipeline — Full Audit Report

> Auditing `app/services/ingestion_pipeline.py` against the planned architecture.

---

## 1. Pipeline Stage Coverage

| Planned Stage | Implemented? | Where | Notes |
|---|---|---|---|
| **PDF Upload** | ✅ Partial | `admin.py`, `IngestRequest` | Only path-based, no actual HTTP file upload |
| **Security Check** | ❌ Missing | — | No file-type validation, no prompt-injection scan, no malicious PDF scan |
| **File Validation** | ⚠️ Minimal | `process_pdf` L200 | Only `os.path.exists()` — no size/corruption/encryption check |
| **PDF Inspection** | ❌ Missing | — | No encrypted PDF detection, no page count guard, no corruption check |
| **Page Classification** | ❌ Missing | — | All pages treated the same; no image-heavy vs text-heavy split |
| **Text Extraction** | ✅ Done | `_extract_text()` | `PyPDF2.PdfReader` — basic, no multi-column handling |
| **OCR** | ❌ Missing | — | No OCR fallback for scanned/image pages |
| **Layout Parser** | ❌ Missing | — | No reading-order correction, no table/figure/footnote handling |
| **Structure Parser** | ⚠️ Partial | `_structure_chunk()` | LLM repairs OCR text and splits by topic — decent, but no heading-tree parsing |
| **Chapter/Topic Mapping** | ✅ Done | `_upsert_topic()` | LLM assigns headings → Topics → linked to Chapter in DB |
| **Chunking** | ⚠️ Blunt | L208, L246 | Hard-coded 4000-char → LLM → 800-char sub-chunks; no semantic boundary detection |
| **Enrichment** | ⚠️ Partial | `_structure_chunk()` | Only `heading` + `repaired_text` — no `summary`, `keywords`, `prerequisites` |
| **Quality Validation** | ❌ Missing | — | No confidence score on LLM output, no empty-section rejection beyond `strip()` |
| **Confidence Gate** | ❌ Missing | — | No high/low confidence split; everything goes to embedding regardless |
| **Embedding** | ✅ Done | `_upsert_block_and_embedding()` | Uses Azure `text-embedding-3-small`, correct |
| **Vector Index (upsert)** | ✅ Done | `_upsert_block_and_embedding()` | Upserts `ContentBlock` + `BlockEmbedding` idempotently |
| **RAG (retrieval side)** | ✅ Done | `retrieval_service.py` | 3-level cascade + 0.60 confidence gate — good |
| **Duplicate Detection** | ❌ Missing | — | No duplicate PDF guard; re-ingesting same PDF adds duplicate blocks |
| **Redis cache invalidation** | ❌ Missing | — | Pipeline does NOT invalidate cache after ingestion (described in PROJECT_DESCRIPTION but not in code) |

---

## 2. Schema / API Bugs Found

### 2a. `admin.py` calls `process_pdf()` with OLD signature
```python
# admin.py L25-30 — WRONG (old 4-param signature)
result = pipeline.process_pdf(
    pdf_path=request.pdf_path,
    class_num=request.class_num,
    subject=request.subject,        # ← wrong kwarg name
    chapter=request.chapter,        # ← wrong kwarg name
)
```
The pipeline now requires: `board_name`, `class_num`, `subject_name`, `book_title`, `book_natural_key`, `chapter_title`, `chapter_number`.  
**`/admin/ingest` will throw a `TypeError` on every call.**

### 2b. `IngestRequest` is missing the new required fields
```python
class IngestRequest(BaseModel):
    pdf_path:  str
    class_num: int          # ✅
    subject:   str          # → should be subject_name
    chapter:   str          # → should be chapter_title + chapter_number + board_name + book_title + book_key
```
`board_name`, `book_title`, `book_natural_key`, `chapter_number` are **all missing** from the API schema.  
The CLI (`scripts/ingest.py`) has the correct new args, but the HTTP API is broken.

### 2c. `IngestResponse` missing `blocks_stored` and `chapter_id`
The pipeline returns `{"status", "sections_ingested", "blocks_stored", "chapter_id"}` but `IngestResponse` only has `{"status", "sections_ingested", "message"}`.  
`IngestResponse(**result)` will silently drop `blocks_stored` and `chapter_id`.

---

## 3. Confidence / Trust Pipeline Gaps

> [!CAUTION]
> The most dangerous gap: **low-confidence ingestion flows directly into the embedding index with no gate.**

| Principle | Status |
|---|---|
| OCR confidence score | ❌ Not computed |
| LLM structuring confidence | ❌ Not computed — if LLM returns garbage JSON, it silently drops that chunk (good) but doesn't flag low-quality output |
| Confidence gate before embedding | ❌ Missing — everything that passes `strip()` gets embedded |
| High-confidence → embed, low-confidence → flag/reprocess | ❌ Not implemented |
| Knowledge confidence ≠ Learner-state confidence separation | ✅ Architecturally correct — pipeline feeds RAG only, does NOT touch cognitive profile |
| Confidence gate before cognitive update | ✅ Present — RAG → Student Interaction → Cognitive update is separate |

---

## 4. Edge Case Coverage

| Edge Case | Handled? |
|---|---|
| Corrupt PDF | ❌ No — will crash with unhandled exception |
| Encrypted/password-protected PDF | ❌ No — PyPDF2 silently returns empty text |
| Huge PDF (resource exhaustion) | ❌ No — no page limit or file size check |
| Duplicate PDF re-ingestion | ⚠️ Partial — `_upsert_block_and_embedding` replaces by `(topic_id, block_index)` but block_index is a global counter, not content-hash. Different content → same index → silently overwrites |
| Low-resolution / scanned pages | ❌ No OCR — those pages yield empty text and are silently skipped |
| Skew/rotation | ❌ No OCR |
| Math formulas | ❌ LLM tries to repair but no formula-specific parser |
| Multi-column layout | ❌ PyPDF2 reads in character order, not reading order |
| Tables | ❌ No table extractor — table text gets mangled |
| Figures | ❌ Completely ignored |
| Footnotes | ❌ Mixed into body text |
| Wrong chapter detection | ⚠️ Possible — chapter title is passed by caller, not auto-detected |
| Wrong topic mapping | ⚠️ LLM-assigned — hallucination risk if OCR is noisy |
| Chunking too small | ⚠️ 800-char sub-chunks can lose context |
| Chunking too large | ⚠️ 4000-char raw chunks can span multiple topics |
| Prompt injection in PDF | ❌ No sanitisation — malicious PDF text goes directly into LLM prompt |
| Wrong board/class/edition | ❌ Caller supplies; no validation against known curriculum |
| Redis cache invalidation after ingest | ❌ Not implemented (described in docs but missing from code) |

---

## 5. What IS Working Well

- ✅ **DB hierarchy** — Board → SchoolClass → Subject → Book → Chapter → Topic correctly built
- ✅ **Idempotent upserts** — All `_get_or_create_*` functions are safe to re-run
- ✅ **Embedding model** — Correct Azure deployment, safe 8000-char truncation
- ✅ **LLM structuring prompt** — JSON-mode, temperature 0.1, good defaults
- ✅ **scripts/ingest.py** — CLI has all correct new args and calls `process_pdf` correctly
- ✅ **Retrieval confidence gate** — 0.60 cosine threshold in `retrieval_service.py` protects the RAG layer
- ✅ **Cognitive separation** — Pipeline does NOT write to cognitive profile (correct architecture)

---

## 6. Prioritised Fix List

### 🔴 Critical (Broken functionality)
1. **Fix `admin.py`** — pass all new `process_pdf()` kwargs (`board_name`, `subject_name`, `book_title`, `book_natural_key`, `chapter_title`, `chapter_number`)
2. **Fix `IngestRequest` schema** — add missing fields
3. **Fix `IngestResponse` schema** — add `blocks_stored: int`, `chapter_id: int | None`

### 🟠 High (Safety / Trust Pipeline)
4. **Add file validation** — file size limit, PyPDF2 encryption check, page count guard
5. **Add OCR fallback** — detect image-only pages (`pdf2image` + `pytesseract` or Azure OCR)
6. **Add prompt injection sanitisation** — strip/escape LLM-injection patterns from extracted text before sending to `_structure_chunk()`
7. **Add confidence scoring on LLM output** — flag sections with very short `repaired_text` or mismatched headings
8. **Add confidence gate before embedding** — only embed sections above a quality threshold
9. **Invalidate Redis cache** after successful ingestion

### 🟡 Medium (Quality)
10. **Add duplicate detection** — hash-based check before processing (SHA256 of PDF bytes)
11. **Improve chunking** — use sentence boundaries, not hard char splits
12. **Add enrichment fields** — `summary`, `keywords`, `prerequisites` (the schema in `legacy.py` already has `ProcessedSection` with these fields — use it!)
13. **Add `IngestJob` table** — track ingestion status, progress, errors per PDF

### 🟢 Low (Nice to have)
14. Table extractor (pdfplumber)
15. Figure captioning (vision model)
16. Multi-column reading order fix
17. Edition/board validation against known curriculum tree



Pipeline Stage	Described	Current State	Gap
PDF Upload	✅	✅ file path, schema	—
Security Check (MIME)	MIME type + magic bytes	❌ Extension only	Missing MIME validation
File Validation	size, pages, encryption	✅ All three	—
Duplicate detection	SHA-256 hash	✅ Redis + BookIngestionLog	—
PDF Inspection (metadata)	permissions, metadata	❌ Not read	Missing
Page Classification	per-page digital/scanned	✅ per-page OCR fallback	—
Image preprocessing (OCR)	deskew, denoise, rotate	❌ Raw pytesseract	Missing
OCR confidence scoring	per-page confidence	❌ Binary pass/fail	Missing
Layout Analysis	multi-column, reading order	❌ Flat text join	Missing
Header/Footer stripping	remove repetitive page text	❌ Not done	Missing
Watermark/annotation removal	remove noise	❌ Not done	Missing
Structure Parser	Chapter/Topic/Subtopic tree	⚠️ LLM only, no regex	Weak
Chapter detection	robust heading detection	⚠️ LLM-assigned	Fragile
Math formula handling	detect as formula block	❌ Treated as garbled text	Missing
Table extraction	preserve row/col	❌ Flat text	Missing
Figure detection	mark as figure block	❌ Ignored	Missing
Cross-page continuity	join broken sentences	❌ Page boundaries break context	Missing
Chunking	semantic boundaries	✅ paragraph + sentence	—
Content Enrichment	summary/keywords/prereqs	✅ LLM (Redis-cached)	—
Deduplication before embed	skip repeated content	❌ Not done	Missing
Quality Validation	VALID/LOW_CONF/PARTIAL/FAILED	⚠️ Binary 0.5 threshold	Too simple
BookIngestionLog write	full coverage report	❌ Not written to DB	Missing — table exists!
Coverage report	{total, processed, ocr, failed}	❌ Not tracked	Missing
Stage-level confidence	per-stage scores	❌ Single section score	Missing
Embedding	Azure text-embedding-3-small	✅	—
Vector index	ContentBlock + BlockEmbedding	✅	—
Cache invalidation	post-ingest Redis flush	✅	—
RAG confidence gate	0.60 cosine threshold	✅ retrieval_service.py	—