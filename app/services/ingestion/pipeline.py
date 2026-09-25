"""
app/services/ingestion/pipeline.py
────────────────────────────────────
IngestionPipeline orchestrator — 17 stages.

This module is intentionally thin: it orchestrates calls to the focused
sub-modules (pdf_extractor, text_processor, structure_detector, db_writer)
and handles the cross-cutting concerns:
  - Redis duplicate detection (stage 4)
  - LLM structuring cache (stage 11b)
  - Debug JSON dump
  - BookIngestionLog lifecycle
  - Redis cache invalidation (stage 17)

Stage map
─────────
  0  MIME / magic-byte security check         → pdf_extractor.check_mime
  1  File existence                            → caller
  2  File validation (size, enc, pages)        → pdf_extractor.validate_pdf
  3  PDF metadata inspection                   → pdf_extractor.inspect_metadata
  4  Duplicate detection (SHA-256 → Redis)     → this module
  5  BookIngestionLog create + hierarchy upsert → db_writer.*
  6  Per-page layout analysis                  → pdf_extractor.analyse_pages
  7  Header/footer stripping                   → text_processor.strip_headers_footers
  8  Watermark / annotation removal            → text_processor.strip_watermarks
  9  Cross-page sentence stitching             → text_processor.stitch_cross_page
 10  Prompt-injection sanitisation             → text_processor.sanitise_blocks
 11  Structure detection                       → structure_detector.detect_structure
 11b LLM enrichment (per section, cached)     → this module (_structure_chunk_cached)
 12  Semantic chunking                         → REMOVED (one block per section)
 13  Content deduplication (MD5)              → db_writer.write_structured_topics
 14  Quality gate                             → structure_detector.score_section
 15  DB write                                 → db_writer.write_structured_topics
 16  BookIngestionLog update                  → db_writer.update_ingestion_log
 17  Redis cache invalidation                 → this module
"""
from __future__ import annotations

import json
import logging
import os
import time

from sqlalchemy.orm import Session

from app.config import settings
from app.data.database import managed_session
from app.data.models.content import BookIngestionLog
from app.infra.azure_openai_client import get_openai
from app.infra.redis_cache import RetrievalCache
from app.prompts import STRUCTURE_PROMPT

from app.services.ingestion.db_writer import (
    get_or_create_board, get_or_create_class, get_or_create_subject,
    get_or_create_book, get_or_create_chapter,
    write_structured_topics, write_chapter_summary, update_ingestion_log,
    PROMPT_VERSION,
)
from app.services.ingestion.models import (
    CONFIDENCE_THRESHOLD, INGEST_DUP_TTL, OCR_LOW_CONF_THRESHOLD, RAW_CHUNK_SIZE,
    IngestionSection,
)
from app.services.ingestion.pdf_extractor import (
    analyse_pages, check_mime, inspect_metadata, sha256_file, validate_pdf,
)
from app.services.ingestion.structure_detector import (
    detect_structure, score_section, classify_level,
)
from app.services.ingestion.text_processor import (
    sanitise_blocks, stitch_cross_page, strip_headers_footers, strip_watermarks,
)

logger = logging.getLogger(__name__)


def _embed(text: str) -> list[float]:
    """Thin wrapper around the Azure OpenAI embedding endpoint."""
    client = get_openai()
    resp   = client.embeddings.create(
        input=text[:8000],
        model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    )
    return resp.data[0].embedding


class IngestionPipeline:
    """
    17-stage PDF ingestion orchestrator.
    Stateless after construction — safe to reuse across runs.
    """

    def __init__(self) -> None:
        self.llm   = get_openai()
        self.cache = RetrievalCache()

    # =========================================================================
    # Public entry point
    # =========================================================================

    def process_pdf(
        self,
        pdf_path:         str,
        board_name:       str,
        class_num:        int,
        subject_name:     str,
        book_title:       str,
        book_natural_key: str,
        chapter_title:    str,
        chapter_number:   int,
        json_only:        bool = False,
    ) -> dict:
        """
        Runs all 17 stages and returns a result dict:
          {status, sections_ingested, blocks_stored, chapter_id,
           warnings, message, ingestion_confidence, coverage}

        Raises:
          FileNotFoundError — PDF path does not exist.
          ValueError        — PDF is invalid (too large, encrypted, etc.).
        """
        t0       = time.time()
        warnings: list[str] = []
        log_id: int | None  = None

        pdf_path = os.path.abspath(pdf_path)

        # ── Stages 0-4 ───────────────────────────────────────────────────────
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        check_mime(pdf_path)

        val_warns, page_count = validate_pdf(pdf_path)
        warnings.extend(val_warns)

        mime_type, _pdf_meta = inspect_metadata(pdf_path)
        pdf_hash  = sha256_file(pdf_path)

        # ── Stage 5: BookIngestionLog + hierarchy upsert ──────────────────────
        chapter_id_result: int
        with managed_session() as db:
            board   = get_or_create_board(db, board_name)
            sc      = get_or_create_class(db, board.id, class_num)
            subject = get_or_create_subject(db, sc.id, subject_name)
            book    = get_or_create_book(db, subject.id, book_title, book_natural_key)
            chap_nk = f"{book_natural_key}_ch{chapter_number}"
            chapter = get_or_create_chapter(db, book.id, chapter_title, chapter_number, chap_nk)
            log = BookIngestionLog(
                book_id=book.id, pdf_hash=pdf_hash,
                chapter_number=chapter_number, mime_type=mime_type,
                page_count=page_count, status="in_progress",
            )
            db.add(log)
            db.flush()
            log_id            = log.id
            chapter_id_result = chapter.id

        try:
            result = self._run_pipeline(
                pdf_path=pdf_path, chapter_title=chapter_title,
                chapter_id=chapter_id_result, chap_nk=chap_nk,
                class_num=class_num, subject_name=subject_name,
                page_count=page_count, warnings=warnings, json_only=json_only,
            )
        except Exception as exc:
            with managed_session() as db:
                update_ingestion_log(db, log_id, "failed", {}, None, str(exc))
            raise

        # ── Stage 16: update log ──────────────────────────────────────────────
        with managed_session() as db:
            update_ingestion_log(
                db, log_id, result["status"],
                result["coverage"], result["ingestion_confidence"],
            )

        # ── Stage 17: Redis invalidation ──────────────────────────────────────
        try:
            n = self.cache.invalidate_subject(class_num, subject_name)
            logger.info(f"[Ingestion] Redis cache invalidated ({n} keys)")
        except Exception as exc:
            logger.warning(f"[Ingestion] Cache invalidation non-fatal: {exc}")

        self.cache._safe_setex(f"ingested:pdf:{pdf_hash}", INGEST_DUP_TTL, "1")
        elapsed = round(time.time() - t0, 1)
        logger.info(f"[Ingestion] Completed in {elapsed}s — {result['blocks_stored']} blocks")
        result["chapter_id"] = chapter_id_result
        result["warnings"] += warnings
        return result

    # =========================================================================
    # Core runner (_run_pipeline)
    # =========================================================================

    def _run_pipeline(
        self,
        pdf_path:      str,
        chapter_title: str,
        chapter_id:    int,
        chap_nk:       str,
        class_num:     int,
        subject_name:  str,
        page_count:    int,
        warnings:      list[str],
        json_only:     bool = False,
    ) -> dict:

        # ── Stage 6: Per-page analysis ────────────────────────────────────────
        page_analyses = analyse_pages(pdf_path, page_count)
        ocr_confs     = [p.ocr_confidence for p in page_analyses if p.ocr_confidence is not None]
        avg_ocr       = round(sum(ocr_confs) / len(ocr_confs), 1) if ocr_confs else 100.0
        ocr_pages     = [p.page_num for p in page_analyses if p.is_scanned]
        empty_pages   = [p.page_num for p in page_analyses if not p.blocks]
        low_conf_pgs  = [
            p.page_num for p in page_analyses
            if p.ocr_confidence is not None and p.ocr_confidence < OCR_LOW_CONF_THRESHOLD
        ]

        if ocr_pages:    warnings.append(f"OCR used on {len(ocr_pages)} page(s): {ocr_pages}")
        if low_conf_pgs: warnings.append(f"Low OCR confidence on page(s): {low_conf_pgs}")

        all_blocks = [b for pa in page_analyses for b in pa.blocks]

        # ── Stages 7-10 ───────────────────────────────────────────────────────
        all_blocks = strip_headers_footers(all_blocks, page_count)
        all_blocks = strip_watermarks(all_blocks, warnings)
        all_blocks = stitch_cross_page(all_blocks)
        all_blocks = sanitise_blocks(all_blocks)

        # ── Stage 11: Structure detection ─────────────────────────────────────
        sections = detect_structure(all_blocks, chapter_title, self._structure_chunk_cached)
        if not sections:
            sections = [IngestionSection(
                heading=chapter_title, heading_level=0, blocks=all_blocks, confidence=0.6,
            )]

        # ── Stage 11b: LLM enrichment (per section, Redis-cached) ─────────────
        llm_output_data: dict[str, dict] = {}
        for sec_idx, sec in enumerate(sections):
            conf = score_section(sec)
            if conf < CONFIDENCE_THRESHOLD:
                continue
            text    = "\n\n".join(b.text for b in sec.blocks if b.text.strip())
            sec_key = f"{sec_idx}:{sec.heading}"
            data    = self._structure_chunk_cached(text[:RAW_CHUNK_SIZE], chapter_title)
            if data:
                llm_output_data[sec_key] = {
                    "raw_blocks": [b.text for b in sec.blocks],
                    "llm_data":   data,
                }
            else:
                # Retry once (cache miss or first failure)
                logger.warning(f"[Ingestion] LLM data missing for '{sec.heading}', retrying once...")
                retry_data = self._structure_chunk_cached(text[:RAW_CHUNK_SIZE], chapter_title)
                if retry_data:
                    logger.info(f"[Ingestion] Retry succeeded for '{sec.heading}'")
                    llm_output_data[sec_key] = {
                        "raw_blocks": [b.text for b in sec.blocks],
                        "llm_data":   retry_data,
                    }
                else:
                    logger.warning(
                        f"[Ingestion] Retry also failed for '{sec.heading}' — "
                        "section will be skipped to preserve RAG quality."
                    )
                    warnings.append(
                        f"LLM structuring failed (2 attempts) for '{sec.heading}' — skipped."
                    )

        # ── Debug JSON dump ───────────────────────────────────────────────────
        debug_path = self._write_debug_json(pdf_path, llm_output_data)

        if json_only:
            logger.info("[Ingestion] Stopping before DB insertion (json_only=True).")
            return {
                "status": "json_only",
                "sections_ingested": 0,
                "blocks_stored": 0,
                "chapter_id": chapter_id,
                "warnings": warnings,
                "message": f"Wrote JSON to {debug_path}. Stopping before DB write.",
                "ingestion_confidence": avg_ocr / 100.0,
                "coverage": {},
            }

        # ── Build structured_topics list ──────────────────────────────────────
        skipped = 0
        structured_topics: list[tuple[str, dict]] = []
        for sec_idx, sec in enumerate(sections):
            conf = score_section(sec)
            if conf < CONFIDENCE_THRESHOLD:
                skipped += 1
                warnings.append(f"Skipped '{sec.heading}' (score={conf:.2f})")
                logger.warning(f"[Ingestion] Skipped '{sec.heading}' conf={conf:.2f}")
                continue

            sec_key = f"{sec_idx}:{sec.heading}"
            data    = llm_output_data.get(sec_key)
            if data and "sections" in data["llm_data"]:
                for llm_sec in data["llm_data"]["sections"]:
                    structured_topics.append((sec.heading, llm_sec))
            else:
                skipped += 1
                logger.warning(
                    f"[Ingestion] '{sec.heading}' has no LLM data after retries — excluded from DB."
                )

        # Deduplicate by topic title before DB write to prevent UNIQUE constraint
        # violations on (topic_id, block_index=0).
        seen_titles: set[str] = set()
        deduped: list[tuple[str, dict]] = []
        for heading, td in structured_topics:
            title = (td.get("heading") or chapter_title).strip()
            if title not in seen_titles:
                seen_titles.add(title)
                deduped.append((heading, td))
            else:
                logger.warning(
                    f"[Ingestion] Duplicate topic title '{title}' — "
                    "skipping second occurrence to prevent UNIQUE constraint violation."
                )
        structured_topics = deduped

        # ── Stages 13-15: Dedup + quality gate + DB write ─────────────────────
        with managed_session() as db:
            total_blocks, write_skipped, seen_hashes = write_structured_topics(
                db=db,
                structured_topics=structured_topics,
                chapter_id=chapter_id,
                chap_nk=chap_nk,
                chapter_title=chapter_title,
                llm_output_data=llm_output_data,
                embed_fn=_embed,
            )
            skipped += write_skipped

            # Chapter-level summarization (non-fatal)
            write_chapter_summary(
                db=db,
                chapter_id=chapter_id,
                chapter_title=chapter_title,
                structured_topics=structured_topics,
                llm_client=self.llm,
                model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            )

        # ── Compute final status + coverage ───────────────────────────────────
        sec_conf     = 1.0 - skipped / max(len(sections), 1)
        ocr_norm     = avg_ocr / 100.0
        overall_conf = round(sec_conf * 0.6 + ocr_norm * 0.4, 3)
        skip_pct     = skipped / max(len(sections), 1)

        if skip_pct > 0.2 or avg_ocr < OCR_LOW_CONF_THRESHOLD:
            status = "needs_review"
        elif skipped or empty_pages or low_conf_pgs:
            status = "partial"
        else:
            status = "complete"

        coverage = {
            "total_pages":          page_count,
            "processed_pages":      page_count,
            "ocr_pages":            ocr_pages,
            "failed_pages":         [],
            "empty_pages":          empty_pages,
            "low_confidence_pages": low_conf_pgs,
            "stage_confidence": {
                "extraction":    1.0,
                "ocr_avg":       round(ocr_norm, 3),
                "structure":     round(sec_conf, 3),
                "topic_mapping": round(sec_conf, 3),
            },
            "sections_found":   len(sections),
            "sections_skipped": skipped,
            "blocks_stored":    total_blocks,
            "deduplicated":     len(seen_hashes) - total_blocks,
        }
        return {
            "status":              status,
            "sections_ingested":   len(sections) - skipped,
            "blocks_stored":       total_blocks,
            "chapter_id":          None,          # filled by process_pdf
            "warnings":            [],             # filled by process_pdf
            "message": (
                f"Ingested {total_blocks} blocks from {len(sections)} section(s)."
                + (f" {skipped} skipped." if skipped else "")
            ),
            "ingestion_confidence": overall_conf,
            "coverage":            coverage,
        }

    # =========================================================================
    # LLM structuring (Redis-cached)
    # =========================================================================

    def _structure_chunk_cached(self, text: str, chapter: str) -> dict | None:
        """
        Calls the LLM to structure a raw chunk of OCR text.
        Results are cached in Redis (TTL = CACHE_CHUNK_TTL) keyed on MD5(text).
        """
        import hashlib
        cache_key = f"struct:{hashlib.md5(text.encode()).hexdigest()}"
        cached    = self.cache._safe_get(cache_key)
        if cached:
            try:
                return json.loads(cached)
            except Exception:
                pass

        prompt = STRUCTURE_PROMPT.format(chapter=chapter, text=text)
        try:
            resp = self.llm.chat.completions.create(
                model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": "You are an expert curriculum parser."},
                    {"role": "user",   "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            raw  = resp.choices[0].message.content
            data = json.loads(raw)
            self.cache._safe_setex(cache_key, settings.CACHE_CHUNK_TTL, json.dumps(data))
            return data
        except Exception as exc:
            logger.warning(f"[Ingestion] LLM structuring failed: {exc}")
            return None

    # =========================================================================
    # Debug helpers
    # =========================================================================

    @staticmethod
    def _write_debug_json(pdf_path: str, data: dict) -> str:
        """Writes the LLM output data dict to a debug JSON file next to the PDF."""
        json_dir   = os.path.join(os.path.dirname(pdf_path), "json_files")
        os.makedirs(json_dir, exist_ok=True)
        debug_path = os.path.join(json_dir, f"ingest_debug_{os.path.basename(pdf_path)}.json")
        try:
            with open(debug_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.info(f"[Ingestion] Wrote debug JSON to {debug_path}")
        except Exception as exc:
            logger.warning(f"[Ingestion] Failed to write debug JSON: {exc}")
        return debug_path
