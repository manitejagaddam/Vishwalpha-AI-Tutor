# Ingestion Pipeline Fixes: Descriptive Headings & Consolidated Blocks

## Open Questions
- Since we are no longer breaking a topic's text into smaller chunks (`SUB_CHUNK_SIZE`), each `ContentBlock` will hold the entire text of that topic section. Because we only embed the 1-2 sentence *summary*, this won't impact vector search limits, and it guarantees the Tutor LLM receives the full context when a section is retrieved. Are you comfortable with this change?

## Proposed Changes

---

### Schema Restructuring (Migrations)

#### [NEW] `EnrichedSection`, `RawBlockLink`, and updated `ContentBlock`
Following your feedback, we will separate the LLM-generated sections from the raw OCR blocks.
1. **`ContentBlock` (Raw Archive)**: We will strip all `enriched_*` columns from `ContentBlock`. It will serve strictly as the untouched source archive (raw_text, page_num, paddlex block_type). 
2. **`EnrichedSection` (LLM Output)**: A new table representing exactly one `sections[]` entry from the LLM.
   - `topic_id` (FK to Topic)
   - `heading` (Descriptive title)
   - `content_type` (concept, activity, etc.)
   - `repaired_text` (Full cleaned text)
   - `summary` (Embedded)
   - `keywords`, `prerequisites`, `difficulty_level`
3. **`SectionRawLink`**: A many-to-many join table linking an `EnrichedSection.id` to an array of contributing `ContentBlock.id`s for perfect traceability.
4. **`BlockEmbedding`**: Will be updated to point to `EnrichedSection.id` instead of `ContentBlock.id`.

*An Alembic migration (`011_schema_restructure.py`) will be generated to apply these DB changes.*

### Ingestion Pipeline Refactoring

#### [MODIFY] [app/services/ingestion_pipeline.py](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/app/services/ingestion_pipeline.py)
1. **Descriptive Headings**: Update `STRUCTURE_PROMPT` to explicitly instruct the LLM: 
   > "heading: a specific, descriptive title generated from what this section is actually about — never a bare label like 'Activity 1.5', 'Step III', 'Questions', or 'Figures', even when the section is short or the source text is led by such a label. For a question section, name what the questions are about. For a figure section, name what the figures depict collectively, not just 'Figures'."
2. **Pipeline Storage Logic**: 
   - Store all Paddlex `PageBlock`s as `ContentBlock` (raw archive).
   - Pass the combined text to the LLM.
   - For each returned `sections[]` entry, insert one `EnrichedSection` row.
   - Link the `EnrichedSection` to its contributing `ContentBlock`s via the join table.
   - Generate and store the embedding for the `EnrichedSection`'s summary.

### Retrieval Refactoring

#### [MODIFY] [app/services/retrieval_service.py](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/app/services/retrieval_service.py)
- Update `_run_query` to join `EnrichedSection` instead of `ContentBlock`.
- RAG will now cleanly retrieve the `EnrichedSection.repaired_text` instead of raw text, giving the Tutor LLM perfectly clean, unchunked context.

---

## Verification Plan

### Automated Tests
- Run `tests/test_ingestion_pipeline.py` to ensure the mock pipeline still passes without the chunking logic.

### Manual Verification
1. I will provide you with a SQL script to wipe the database so you can re-ingest fresh.
2. Run the ingest script on Chapter 1.
3. Check your database UI to verify:
   - `ContentBlock` rows have descriptive titles (no more just "Activity 1.1").
   - `enriched_summary` is populated for EVERY row (no more NULLs).
