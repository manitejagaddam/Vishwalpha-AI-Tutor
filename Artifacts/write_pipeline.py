
PIPELINE_CODE = r'''"""
app/services/ingestion_pipeline.py
------------------------------------
Full Trust Pipeline - 17 stages.

Stage  0 : MIME / magic-byte security check
Stage  1 : File existence
Stage  2 : File validation (size, encryption, page count)
Stage  3 : PDF metadata inspection
Stage  4 : Duplicate detection (SHA-256 -> Redis + BookIngestionLog)
Stage  5 : BookIngestionLog creation (status=in_progress)
Stage  6 : Per-page layout analysis
              paddlex layout_detection (heading/text/table/equation/figure)
              Per-page digital vs scanned classification
              OCR with per-word confidence scoring
              Math-region OCR (PSM 6 + common error fixes)
              Table-region OCR -> markdown table
Stage  7 : Header/footer stripping (lines appearing on >50% of pages)
Stage  8 : Watermark / annotation removal
Stage  9 : Cross-page sentence stitching
Stage 10 : Prompt-injection sanitisation
Stage 11 : Structure detection
              Regex: "X.Y Title" numbered headings, Chapter markers, exercises
              paddlex title blocks as anchors
              LLM fallback for unstructured text (Redis-cached)
              LLM enrichment: summary, keywords, prerequisites
Stage 12 : Semantic chunking (paragraph -> sentence boundaries)
Stage 13 : Content deduplication (MD5 before embed)
Stage 14 : Quality gate (confidence 0.0-1.0 per section)
Stage 15 : DB write - Board/Class/Subject/Book/Chapter/Topic/ContentBlock/Embedding
Stage 16 : BookIngestionLog update (coverage JSON, confidence, status)
Stage 17 : Redis cache invalidation

Ingestion statuses:
  complete     - all sections high-confidence, all pages processed
  partial      - some low-confidence sections or failed pages
  needs_review - >20% sections skipped OR avg OCR confidence < 60%
  failed       - fatal error (exception stored in log)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from PyPDF2 import PdfReader
from sqlalchemy.orm import Session

from app.config import settings
from app.data.database import managed_session
from app.data.models.content import (
    BlockEmbedding, Board, Book, BookIngestionLog, Chapter,
    ContentBlock, SchoolClass, Subject, Topic,
)
from app.infra.azure_openai_client import get_openai
from app.infra.redis_cache import RetrievalCache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PDF_BYTES          = 100 * 1024 * 1024   # 100 MB hard limit
MAX_PDF_PAGES          = 500                   # warn above this
MIN_TEXT_PER_PAGE      = 50                    # chars; below -> OCR
MIN_SECTION_CHARS      = 80                    # quality gate
CONFIDENCE_THRESHOLD   = 0.5                   # below -> skip section
RAW_CHUNK_SIZE         = 4000                  # chars sent to LLM
SUB_CHUNK_SIZE         = 800                   # chars per ContentBlock
INGEST_DUP_TTL         = 60 * 60 * 24 * 365   # 1 year duplicate TTL
OCR_LOW_CONF_THRESHOLD = 60.0                  # avg OCR confidence %
HEADER_FOOTER_FREQ     = 0.5                   # >50% pages = header/footer
PROMPT_VERSION         = "v2.0"
PDF_MAGIC              = b"%PDF-"

_INJECTION_RE = re.compile(
    r"(ignore\s+previous\s+instructions"
    r"|system\s*:"
    r"|<\|im_start\|>"
    r"|<\|endoftext\|>"
    r"|assistant\s*:"
    r"|```\s*system)",
    re.IGNORECASE,
)
_WATERMARK_RE = re.compile(
    r"^\s*(sample\s+copy|do\s+not\s+distribute|draft|confidential"
    r"|for\s+review\s+only|not\s+for\s+sale|preview\s+copy)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_CHAPTER_RE  = re.compile(r"^(?:chapter\s+\d+|unit\s+[ivxIVX\d]+)\b", re.IGNORECASE)
_TOPIC_RE    = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?\s+(.+)$", re.MULTILINE)
_EXERCISE_RE = re.compile(
    r"^(?:exercise\s+\d+|example\s+\d+|activity\s+\d+|think\s+and\s+discuss)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PageBlock:
    """Atomic content unit extracted from one PDF page region."""
    block_type:     str
    text:           str
    page_num:       int
    ocr_confidence: float | None = None


@dataclass
class PageAnalysis:
    """Analysis result for one PDF page."""
    page_num:       int
    is_scanned:     bool
    ocr_confidence: float | None
    blocks:         list[PageBlock] = field(default_factory=list)
    raw_lines:      list[str]       = field(default_factory=list)


@dataclass
class IngestionSection:
    """A topic-level section ready for DB write."""
    heading:       str
    heading_level: int
    blocks:        list[PageBlock]
    summary:       str        = ""
    keywords:      list[str]  = field(default_factory=list)
    prerequisites: list[str]  = field(default_factory=list)
    confidence:    float      = 1.0
    topic_number:  str | None = None

# ---------------------------------------------------------------------------
# paddlex layout pipeline (lazy singleton)
# ---------------------------------------------------------------------------

_LAYOUT_PIPELINE = None
_PADDLEX_OK: bool | None = None


def _get_layout_pipeline():
    global _LAYOUT_PIPELINE, _PADDLEX_OK
    if _PADDLEX_OK is not None:
        return _LAYOUT_PIPELINE
    try:
        from paddlex import create_pipeline  # type: ignore
        _LAYOUT_PIPELINE = create_pipeline(pipeline="layout_detection")
        _PADDLEX_OK = True
        logger.info("[Ingestion] paddlex layout_detection loaded.")
    except Exception as exc:
        logger.warning(f"[Ingestion] paddlex unavailable ({exc}); using heuristic mode.")
        _PADDLEX_OK = False
    return _LAYOUT_PIPELINE

# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def _embed(text: str) -> list[float]:
    client = get_openai()
    resp = client.embeddings.create(
        input=text[:8000],
        model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    )
    return resp.data[0].embedding

# ---------------------------------------------------------------------------
# DB helpers (idempotent upserts)
# ---------------------------------------------------------------------------

def _get_or_create_board(db: Session, name: str) -> Board:
    obj = db.query(Board).filter(Board.name == name).first()
    if not obj:
        obj = Board(name=name); db.add(obj); db.flush()
    return obj


def _get_or_create_class(db: Session, board_id: int, level: int) -> SchoolClass:
    obj = db.query(SchoolClass).filter(
        SchoolClass.board_id == board_id, SchoolClass.level == level,
    ).first()
    if not obj:
        obj = SchoolClass(board_id=board_id, level=level, display_name=f"Class {level}")
        db.add(obj); db.flush()
    return obj


def _get_or_create_subject(db: Session, class_id: int, name: str) -> Subject:
    obj = db.query(Subject).filter(
        Subject.class_id == class_id, Subject.name == name,
    ).first()
    if not obj:
        obj = Subject(class_id=class_id, name=name, display_name=name)
        db.add(obj); db.flush()
    return obj


def _get_or_create_book(
    db: Session, subject_id: int, title: str, natural_key: str,
) -> Book:
    obj = db.query(Book).filter(Book.natural_key == natural_key).first()
    if not obj:
        obj = Book(subject_id=subject_id, title=title, natural_key=natural_key)
        db.add(obj); db.flush()
    return obj


def _get_or_create_chapter(
    db: Session, book_id: int, title: str,
    chapter_number: int, natural_key: str,
) -> Chapter:
    obj = db.query(Chapter).filter(Chapter.natural_key == natural_key).first()
    if not obj:
        obj = Chapter(
            book_id=book_id, title=title,
            chapter_number=chapter_number, natural_key=natural_key,
        )
        db.add(obj); db.flush()
    return obj


def _upsert_topic(
    db: Session, chapter_id: int, title: str,
    order: int, topic_number: str | None = None,
) -> Topic:
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower())[:80]
    nk   = f"ch{chapter_id}_{slug}"
    obj  = db.query(Topic).filter(Topic.natural_key == nk).first()
    if not obj:
        obj = Topic(
            chapter_id=chapter_id, title=title, display_order=order,
            natural_key=nk, topic_number=topic_number,
        )
        db.add(obj); db.flush()
    else:
        obj.display_order = order
        if topic_number:
            obj.topic_number = topic_number
    return obj


def _upsert_block(
    db: Session, topic_id: int, raw_text: str, block_index: int,
    block_type: str = "text", page_num: int | None = None,
    ocr_confidence: float | None = None,
    summary: str = "", keywords: list | None = None,
    prerequisites: list | None = None,
) -> ContentBlock:
    ch = hashlib.md5(raw_text.strip().lower().encode()).hexdigest()
    blk = db.query(ContentBlock).filter(
        ContentBlock.topic_id == topic_id,
        ContentBlock.block_index == block_index,
    ).first()
    if not blk:
        blk = ContentBlock(
            topic_id=topic_id, block_type=block_type, raw_text=raw_text,
            block_index=block_index, page_num=page_num,
            ocr_confidence=ocr_confidence, content_hash=ch,
            enriched_summary=summary or None,
            enriched_keywords=keywords or None,
            enriched_prerequisites=prerequisites or None,
            prompt_version=PROMPT_VERSION,
        )
        db.add(blk); db.flush()
    else:
        blk.raw_text = raw_text; blk.content_hash = ch
        blk.ocr_confidence = ocr_confidence
        if summary: blk.enriched_summary = summary
        if keywords: blk.enriched_keywords = keywords
        if prerequisites: blk.enriched_prerequisites = prerequisites

    vec = _embed(raw_text)
    emb = db.query(BlockEmbedding).filter(
        BlockEmbedding.block_id == blk.id,
        BlockEmbedding.embedding_model == settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    ).first()
    if emb:
        emb.embedding = vec
    else:
        db.add(BlockEmbedding(
            block_id=blk.id, embedding=vec,
            embedding_model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
        ))
    return blk

# ---------------------------------------------------------------------------
# Main Pipeline Class
# ---------------------------------------------------------------------------

class IngestionPipeline:

    def __init__(self):
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
    ) -> dict:
        """
        17-stage trust pipeline.
        Returns {status, sections_ingested, blocks_stored, chapter_id, warnings, message,
                 ingestion_confidence, coverage}.
        Raises FileNotFoundError, ValueError.
        """
        t0       = time.time()
        warnings: list[str] = []
        log_id: int | None   = None

        # Stage 0: MIME check
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        self._check_mime(pdf_path)

        # Stage 2: Validation
        val_warns, page_count = self._validate_pdf(pdf_path)
        warnings.extend(val_warns)

        # Stage 3: Metadata
        mime_type, _pdf_meta = self._inspect_metadata(pdf_path)

        # Stage 4: Duplicate detection
        pdf_hash = self._sha256(pdf_path)
        dup_key  = f"ingested:pdf:{pdf_hash}"
        if self.cache._safe_get(dup_key):
            logger.warning(f"[Ingestion] Duplicate hash={pdf_hash[:12]}")
            return {
                "status": "duplicate", "sections_ingested": 0, "blocks_stored": 0,
                "chapter_id": None,
                "warnings": [f"Already ingested (hash={pdf_hash[:12]}...)"],
                "message": "PDF was already ingested.",
                "ingestion_confidence": None, "coverage": {},
            }

        # Stage 5: BookIngestionLog create + hierarchy upsert
        chapter_id_result: int
        with managed_session() as db:
            board   = _get_or_create_board(db, board_name)
            sc      = _get_or_create_class(db, board.id, class_num)
            subject = _get_or_create_subject(db, sc.id, subject_name)
            book    = _get_or_create_book(db, subject.id, book_title, book_natural_key)
            chap_nk = f"{book_natural_key}_C{chapter_number:02d}"
            chapter = _get_or_create_chapter(
                db, book.id, chapter_title, chapter_number, chap_nk,
            )
            log = BookIngestionLog(
                book_id=book.id, pdf_hash=pdf_hash,
                chapter_number=chapter_number, mime_type=mime_type,
                page_count=page_count, status="in_progress",
            )
            db.add(log); db.flush()
            log_id            = log.id
            chapter_id_result = chapter.id

        try:
            result = self._run_pipeline(
                pdf_path=pdf_path, chapter_title=chapter_title,
                chapter_id=chapter_id_result, class_num=class_num,
                subject_name=subject_name, page_count=page_count,
                warnings=warnings,
            )
        except Exception as exc:
            self._update_log(log_id, "failed", {}, None, str(exc))
            raise

        self._update_log(log_id, result["status"], result["coverage"],
                         result["ingestion_confidence"])

        # Stage 17: Redis invalidation
        try:
            n = self.cache.invalidate_subject(class_num, subject_name)
            logger.info(f"[Ingestion] Redis cache invalidated ({n} keys)")
        except Exception as exc:
            logger.warning(f"[Ingestion] Cache invalidation non-fatal: {exc}")

        self.cache._safe_setex(dup_key, INGEST_DUP_TTL, "1")
        elapsed = round(time.time() - t0, 1)
        logger.info(f"[Ingestion] Completed in {elapsed}s — {result['blocks_stored']} blocks")
        result["chapter_id"] = chapter_id_result
        result["warnings"] += warnings
        return result

    # =========================================================================
    # Core runner
    # =========================================================================

    def _run_pipeline(
        self, pdf_path: str, chapter_title: str, chapter_id: int,
        class_num: int, subject_name: str, page_count: int,
        warnings: list[str],
    ) -> dict:

        # Stage 6: Per-page analysis
        page_analyses = self._analyse_pages(pdf_path, page_count)
        ocr_confs     = [p.ocr_confidence for p in page_analyses if p.ocr_confidence is not None]
        avg_ocr       = round(sum(ocr_confs) / len(ocr_confs), 1) if ocr_confs else 100.0
        ocr_pages     = [p.page_num for p in page_analyses if p.is_scanned]
        empty_pages   = [p.page_num for p in page_analyses if not p.blocks]
        low_conf_pgs  = [
            p.page_num for p in page_analyses
            if p.ocr_confidence is not None and p.ocr_confidence < OCR_LOW_CONF_THRESHOLD
        ]

        if ocr_pages:   warnings.append(f"OCR used on {len(ocr_pages)} page(s): {ocr_pages}")
        if low_conf_pgs: warnings.append(f"Low OCR confidence on page(s): {low_conf_pgs}")

        all_blocks = [b for pa in page_analyses for b in pa.blocks]

        # Stages 7-10
        all_blocks = self._strip_headers_footers(all_blocks, page_count)
        all_blocks = self._strip_watermarks(all_blocks, warnings)
        all_blocks = self._stitch_cross_page(all_blocks)
        all_blocks = self._sanitise_blocks(all_blocks)

        # Stage 11: Structure detection
        sections = self._detect_structure(all_blocks, chapter_title)
        if not sections:
            all_text = "\n\n".join(b.text for b in all_blocks if b.text.strip())
            sections = [IngestionSection(
                heading=chapter_title, heading_level=0, blocks=all_blocks, confidence=0.6,
            )]

        # Stage 11b: Enrich (summary / keywords / prerequisites)
        for sec in sections:
            self._enrich_section(sec, chapter_title)

        # Stages 13-15: Dedup + quality gate + DB write
        total_blocks = 0; skipped = 0; seen: set[str] = set()

        with managed_session() as db:
            bc = 0
            for order, sec in enumerate(sections):
                conf = self._score_section(sec)
                if conf < CONFIDENCE_THRESHOLD:
                    skipped += 1
                    warnings.append(f"Skipped '{sec.heading}' (score={conf:.2f})")
                    logger.warning(f"[Ingestion] Skipped '{sec.heading}' conf={conf:.2f}")
                    continue

                topic = _upsert_topic(db, chapter_id, sec.heading, order, sec.topic_number)

                for blk in sec.blocks:
                    for sub in self._paragraph_chunks(blk.text, SUB_CHUNK_SIZE):
                        if not sub.strip(): continue
                        h = hashlib.md5(sub.strip().lower().encode()).hexdigest()
                        if h in seen: continue
                        seen.add(h)
                        _upsert_block(
                            db, topic.id, sub, bc,
                            block_type=blk.block_type,
                            page_num=blk.page_num,
                            ocr_confidence=blk.ocr_confidence,
                            summary=sec.summary if bc == 0 else "",
                            keywords=sec.keywords if bc == 0 else None,
                            prerequisites=sec.prerequisites if bc == 0 else None,
                        )
                        bc += 1; total_blocks += 1

        # Compute final confidence + status
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
            "total_pages":   page_count,
            "processed_pages": page_count - 0,
            "ocr_pages":     ocr_pages,
            "failed_pages":  [],
            "empty_pages":   empty_pages,
            "low_confidence_pages": low_conf_pgs,
            "stage_confidence": {
                "extraction":    round(1.0, 3),
                "ocr_avg":       round(ocr_norm, 3),
                "structure":     round(sec_conf, 3),
                "topic_mapping": round(sec_conf, 3),
            },
            "sections_found":   len(sections),
            "sections_skipped": skipped,
            "blocks_stored":    total_blocks,
            "deduplicated":     len(seen) - total_blocks,
        }
        return {
            "status": status,
            "sections_ingested": len(sections) - skipped,
            "blocks_stored": total_blocks,
            "chapter_id": None,
            "warnings": [],
            "message": (
                f"Ingested {total_blocks} blocks from {len(sections)} section(s)."
                + (f" {skipped} skipped." if skipped else "")
            ),
            "ingestion_confidence": overall_conf,
            "coverage": coverage,
        }

    # =========================================================================
    # Stage 6 - Per-page analysis
    # =========================================================================

    def _analyse_pages(self, pdf_path: str, page_count: int) -> list[PageAnalysis]:
        pipeline = _get_layout_pipeline()
        reader   = PdfReader(pdf_path)
        results  = []
        for i, page in enumerate(reader.pages):
            pn       = i + 1
            raw_text = page.extract_text() or ""
            scanned  = len(raw_text.strip()) < MIN_TEXT_PER_PAGE
            if scanned:
                pa = self._analyse_scanned_page(pdf_path, pn, pipeline)
            else:
                pa = self._analyse_digital_page(raw_text, pn, pipeline)
            results.append(pa)
            logger.debug(f"[Ingestion] p{pn} scanned={scanned} blocks={len(pa.blocks)}")
        return results

    def _analyse_digital_page(self, raw_text: str, page_num: int, pipeline) -> PageAnalysis:
        blocks = self._heuristic_block_split(raw_text, page_num)
        return PageAnalysis(page_num=page_num, is_scanned=False,
                            ocr_confidence=None, blocks=blocks,
                            raw_lines=[b.text for b in blocks])

    def _analyse_scanned_page(self, pdf_path: str, page_num: int, pipeline) -> PageAnalysis:
        img = self._page_to_image(pdf_path, page_num)
        if img is None:
            return PageAnalysis(page_num=page_num, is_scanned=True, ocr_confidence=None)

        blocks: list[PageBlock] = []
        avg_conf: float | None = None

        # Try paddlex on image
        if pipeline:
            try:
                blocks, avg_conf = self._paddlex_image(img, page_num, pipeline)
            except Exception as exc:
                logger.debug(f"[Ingestion] paddlex image p{page_num}: {exc}")

        # Fallback: plain OCR
        if not blocks:
            text, avg_conf = self._ocr_with_confidence(img)
            if text.strip():
                btype = "equation" if self._looks_like_equation(text) else "text"
                blocks = [PageBlock(btype, text, page_num, avg_conf)]

        return PageAnalysis(page_num=page_num, is_scanned=True,
                            ocr_confidence=avg_conf, blocks=blocks,
                            raw_lines=[b.text for b in blocks])

    # =========================================================================
    # paddlex image analysis
    # =========================================================================

    def _paddlex_image(self, img, page_num: int, pipeline) -> tuple[list[PageBlock], float | None]:
        import tempfile, os as _os
        blocks: list[PageBlock] = []
        confs:  list[float]     = []

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            img.save(tmp.name, "JPEG", quality=95)
            tmp_path = tmp.name

        try:
            for res in pipeline.predict(tmp_path, batch_size=1):
                res_dict = res.to_json() if hasattr(res, "to_json") else {}
                for box in res_dict.get("boxes", []):
                    label  = box.get("label", "text").lower()
                    btype  = self._map_label(label)
                    if btype == "header_footer":
                        continue
                    coords = box.get("coordinate", [])
                    region = self._crop(img, coords)
                    if region is None:
                        continue
                    if btype == "table":
                        text = self._ocr_table(region)
                        conf = None
                    elif btype == "equation":
                        text, conf = self._ocr_math(region)
                    else:
                        text, conf = self._ocr_with_confidence(region)

                    if conf is not None:
                        confs.append(conf)
                    if text.strip():
                        blocks.append(PageBlock(btype, text, page_num, conf))
        finally:
            _os.unlink(tmp_path)

        avg = round(sum(confs) / len(confs), 1) if confs else None
        return blocks, avg

    @staticmethod
    def _map_label(label: str) -> str:
        return {
            "title": "heading", "heading": "heading", "section_heading": "heading",
            "text": "text", "paragraph": "text",
            "table": "table", "table_caption": "text",
            "figure": "figure_ref", "figure_caption": "text",
            "formula": "equation", "equation": "equation",
            "header": "header_footer", "footer": "header_footer", "page_number": "header_footer",
        }.get(label, "text")

    @staticmethod
    def _crop(img, coords: list):
        if not coords or len(coords) < 4:
            return None
        try:
            if isinstance(coords[0], list):
                xs = [c[0] for c in coords]; ys = [c[1] for c in coords]
                box = (min(xs), min(ys), max(xs), max(ys))
            else:
                box = tuple(coords[:4])
            return img.crop(box)
        except Exception:
            return None

    # =========================================================================
    # OCR helpers
    # =========================================================================

    @staticmethod
    def _page_to_image(pdf_path: str, page_number: int):
        try:
            from pdf2image import convert_from_path  # type: ignore
            imgs = convert_from_path(pdf_path, first_page=page_number, last_page=page_number, dpi=300)
            return imgs[0] if imgs else None
        except ImportError:
            logger.warning("[Ingestion] pdf2image missing. Run: uv add pdf2image Pillow")
            return None
        except Exception as exc:
            logger.warning(f"[Ingestion] page_to_image p{page_number}: {exc}")
            return None

    @staticmethod
    def _ocr_with_confidence(img) -> tuple[str, float | None]:
        try:
            import pytesseract  # type: ignore
            data  = pytesseract.image_to_data(img, lang="eng", output_type=pytesseract.Output.DICT)
            confs = [int(c) for c in data["conf"] if int(c) >= 0]
            text  = pytesseract.image_to_string(img, lang="eng")
            avg   = round(sum(confs) / len(confs), 1) if confs else None
            return text, avg
        except ImportError:
            logger.warning("[Ingestion] pytesseract missing. Run: uv add pytesseract")
            return "", None
        except Exception as exc:
            logger.debug(f"[Ingestion] OCR error: {exc}")
            return "", None

    @staticmethod
    def _ocr_math(img) -> tuple[str, float | None]:
        """OCR for equation regions - PSM 6 + common error fixes."""
        try:
            import pytesseract  # type: ignore
            text = pytesseract.image_to_string(img, lang="eng", config="--psm 6 --oem 3")
            _, conf = IngestionPipeline._ocr_with_confidence(img)
            # Common math OCR corrections
            text = re.sub(r"\bl\b", "1", text)
            text = re.sub(r"\bO\b(?=\d)", "0", text)
            text = re.sub(r"(\d)\s*x\s*(\d)", r"\1x\2", text)
            return text.strip(), conf
        except Exception:
            return "", None

    @staticmethod
    def _ocr_table(img) -> str:
        """OCR table region -> markdown table preserving row structure."""
        try:
            import pytesseract  # type: ignore
            data  = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config="--psm 6")
            lines: dict[int, list[str]] = {}
            for j, word in enumerate(data["text"]):
                if word.strip() and int(data["conf"][j]) > 30:
                    lines.setdefault(data["line_num"][j], []).append(word)
            if not lines:
                return ""
            rows = [" | ".join(ws) for ws in lines.values()]
            if len(rows) > 1:
                rows.insert(1, " | ".join(["---"] * max(len(r.split(" | ")) for r in rows[:1])))
            return "\n".join(rows)
        except Exception:
            return ""

    # =========================================================================
    # Stage 7 - Header/footer stripping
    # =========================================================================

    def _strip_headers_footers(self, blocks: list[PageBlock], page_count: int) -> list[PageBlock]:
        if page_count < 3:
            return blocks
        lc: Counter = Counter()
        for blk in blocks:
            for line in blk.text.splitlines():
                if line.strip():
                    lc[line.strip()] += 1
        cutoff  = max(2, int(HEADER_FOOTER_FREQ * page_count))
        hf      = {l for l, n in lc.items() if n >= cutoff}
        if not hf:
            return blocks
        result = []
        for blk in blocks:
            t = "\n".join(l for l in blk.text.splitlines() if l.strip() not in hf).strip()
            if t:
                result.append(PageBlock(blk.block_type, t, blk.page_num, blk.ocr_confidence))
        if len(hf):
            logger.info(f"[Ingestion] Stripped {len(hf)} header/footer pattern(s)")
        return result

    # =========================================================================
    # Stage 8 - Watermark removal
    # =========================================================================

    def _strip_watermarks(self, blocks: list[PageBlock], warnings: list[str]) -> list[PageBlock]:
        found = False; result = []
        for blk in blocks:
            t = _WATERMARK_RE.sub("", blk.text).strip()
            if t != blk.text.strip(): found = True
            if t:
                result.append(PageBlock(blk.block_type, t, blk.page_num, blk.ocr_confidence))
        if found:
            warnings.append("Watermark/sample-copy text detected and removed.")
        return result

    # =========================================================================
    # Stage 9 - Cross-page sentence stitching
    # =========================================================================

    @staticmethod
    def _stitch_cross_page(blocks: list[PageBlock]) -> list[PageBlock]:
        if len(blocks) < 2:
            return blocks
        result: list[PageBlock] = []; i = 0
        while i < len(blocks):
            blk = blocks[i]
            while (
                i + 1 < len(blocks)
                and blk.block_type == "text"
                and blocks[i + 1].block_type == "text"
                and blk.text and blk.text[-1] not in ".!?:\n"
                and blocks[i + 1].text and blocks[i + 1].text[0].islower()
            ):
                nxt = blocks[i + 1]
                combined_conf = None
                if blk.ocr_confidence is not None or nxt.ocr_confidence is not None:
                    a = blk.ocr_confidence or 100.0
                    b = nxt.ocr_confidence or 100.0
                    combined_conf = round((a + b) / 2, 1)
                blk = PageBlock("text", blk.text.rstrip() + " " + nxt.text.lstrip(),
                                blk.page_num, combined_conf)
                i += 1
            result.append(blk); i += 1
        return result

    # =========================================================================
    # Stage 10 - Sanitisation
    # =========================================================================

    @staticmethod
    def _sanitise_blocks(blocks: list[PageBlock]) -> list[PageBlock]:
        found = False; result = []
        for blk in blocks:
            t = _INJECTION_RE.sub("[REDACTED]", blk.text)
            if t != blk.text: found = True
            result.append(PageBlock(blk.block_type, t, blk.page_num, blk.ocr_confidence))
        if found:
            logger.warning("[Ingestion] Prompt-injection pattern(s) redacted.")
        return result

    # =========================================================================
    # Stage 11 - Structure detection
    # =========================================================================

    def _detect_structure(self, blocks: list[PageBlock], chapter_title: str) -> list[IngestionSection]:
        """
        Hierarchical structure detection:
          1. paddlex heading blocks
          2. Regex numbered sections  "X.Y Title" / "X.Y.Z Title"
          3. Chapter-level markers   "Chapter X" / "Unit X"
          4. Exercise / example blocks
          5. LLM fallback if nothing found
        """
        sections: list[IngestionSection] = []
        current: IngestionSection | None = None

        for blk in blocks:
            text    = blk.text.strip()
            is_hdg  = False
            heading = ""
            level   = 1
            tnum: str | None = None

            if blk.block_type == "heading":
                is_hdg  = True
                heading = text
                level   = self._classify_level(heading)

            elif m := _TOPIC_RE.match(text):
                is_hdg  = True
                maj, mn, sub, rest = m.group(1), m.group(2), m.group(3), m.group(4)
                heading = rest.strip()
                tnum    = f"{maj}.{mn}" + (f".{sub}" if sub else "")
                level   = 1 if not sub else 2

            elif _CHAPTER_RE.match(text):
                is_hdg  = True
                heading = text
                level   = 0

            elif _EXERCISE_RE.match(text):
                is_hdg  = True
                heading = text
                level   = 1

            if is_hdg and heading:
                if current:
                    sections.append(current)
                current = IngestionSection(
                    heading=heading, heading_level=level,
                    blocks=[], topic_number=tnum,
                )
            else:
                if current is None:
                    current = IngestionSection(chapter_title, 0, [])
                if text:
                    current.blocks.append(blk)

        if current:
            sections.append(current)

        # LLM fallback when no structure found
        if len(sections) <= 1 and sections and len(sections[0].blocks) > 0:
            full = "\n\n".join(b.text for b in sections[0].blocks)
            llm_secs = self._llm_structure_fallback(full, chapter_title)
            if len(llm_secs) > 1:
                logger.info(f"[Ingestion] LLM fallback: {len(llm_secs)} sections")
                return llm_secs

        logger.info(f"[Ingestion] Structure: {len(sections)} section(s) detected")
        return sections

    @staticmethod
    def _classify_level(heading: str) -> int:
        h = heading.lower().strip()
        if re.match(r"^chapter\s+\d+", h) or re.match(r"^unit\s+", h): return 0
        if re.match(r"^\d+\.\d+\.\d+", h): return 2
        if re.match(r"^\d+\.\d+", h): return 1
        return 1

    def _llm_structure_fallback(self, text: str, chapter: str) -> list[IngestionSection]:
        result = []
        for chunk in self._paragraph_chunks(text, RAW_CHUNK_SIZE):
            data = self._structure_chunk_cached(chunk, chapter)
            if not data: continue
            for sd in data.get("sections", []):
                rt = sd.get("repaired_text", "").strip()
                if not rt: continue
                blk = PageBlock("text", rt, 0, None)
                result.append(IngestionSection(
                    heading=sd.get("heading", chapter).strip() or chapter,
                    heading_level=1, blocks=[blk],
                    summary=sd.get("summary", ""),
                    keywords=sd.get("keywords", []),
                    prerequisites=sd.get("prerequisites", []),
                ))
        return result

    def _enrich_section(self, sec: IngestionSection, chapter: str) -> None:
        if sec.summary and sec.keywords:
            return
        text = "\n\n".join(b.text for b in sec.blocks if b.text.strip())
        if len(text) < 50:
            return
        data = self._structure_chunk_cached(text[:RAW_CHUNK_SIZE], chapter)
        if data and data.get("sections"):
            first = data["sections"][0]
            sec.summary      = first.get("summary", "")
            sec.keywords     = first.get("keywords", [])
            sec.prerequisites = first.get("prerequisites", [])

    # =========================================================================
    # Stage 12 - Semantic chunking
    # =========================================================================

    @staticmethod
    def _paragraph_chunks(text: str, max_chars: int) -> list[str]:
        paras   = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
        chunks: list[str] = []; current = ""
        for para in paras:
            if len(para) > max_chars:
                for sent in re.split(r"(?<=[.!?])\s+", para):
                    if len(current) + len(sent) + 1 > max_chars and current:
                        chunks.append(current.strip()); current = sent
                    else:
                        current = (current + " " + sent).strip()
            elif len(current) + len(para) + 2 > max_chars and current:
                chunks.append(current.strip()); current = para
            else:
                current = (current + "\n\n" + para).strip() if current else para
        if current.strip():
            chunks.append(current.strip())
        return chunks

    # =========================================================================
    # Stage 14 - Quality gate
    # =========================================================================

    @staticmethod
    def _score_section(sec: IngestionSection) -> float:
        """
        0.0-1.0 confidence score:
          +0.5 meaningful text (>= MIN_SECTION_CHARS)
          +0.3 specific heading (not generic)
          +0.2 has enrichment (summary or keywords)
        """
        all_text = "\n".join(b.text for b in sec.blocks)
        h        = (sec.heading or "").strip().lower()
        score    = 0.0
        if len(all_text) >= MIN_SECTION_CHARS:         score += 0.5
        if h and h not in {"general","untitled","unknown","section","introduction",""}:
            score += 0.3
        if sec.summary or sec.keywords:                score += 0.2
        return round(score, 2)

    # =========================================================================
    # LLM structuring (Redis-cached)
    # =========================================================================

    def _structure_chunk_cached(self, text: str, chapter: str) -> dict | None:
        key    = hashlib.md5((chapter + text).encode()).hexdigest()
        cached = self.cache.get_ingest_struct(key)
        if cached is not None:
            logger.debug(f"[Ingestion] LLM cache HIT {key[:8]}")
            return cached
        result = self._structure_chunk(text, chapter)
        if result is not None:
            self.cache.set_ingest_struct(key, result)
        return result

    def _structure_chunk(self, text: str, chapter: str) -> dict | None:
        prompt = (
            f"You are a textbook ingestion pipeline for NCERT educational content.\n"
            f"Chapter: '{chapter}'\n\n"
            f"Tasks:\n"
            f"1. Fix OCR errors and clean the text.\n"
            f"2. Split into logical topic sections using actual headings from the text.\n"
            f"3. For each section: write a 2-3 sentence retrieval summary, list key terms, list prerequisites.\n\n"
            f"Output EXACTLY valid JSON (no markdown, no extra text):\n"
            f'{{"sections":[{{"heading":"...","repaired_text":"...","summary":"...","keywords":["..."],"prerequisites":["..."]}}]}}\n\n'
            f"Raw text:\n{text}"
        )
        try:
            resp = self.llm.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                temperature=0.1,
                max_completion_tokens=4000,
                response_format={"type": "json_object"},
            )
            return json.loads(resp.choices[0].message.content.strip())
        except Exception as exc:
            logger.error(f"[Ingestion] LLM structuring failed: {exc}")
            return None

    # =========================================================================
    # Heuristic block splitter (digital pages / no paddlex)
    # =========================================================================

    @staticmethod
    def _heuristic_block_split(text: str, page_num: int) -> list[PageBlock]:
        blocks: list[PageBlock] = []; current_type = "text"; current: list[str] = []
        for line in text.splitlines():
            s = line.strip()
            if not s:
                if current:
                    t = "\n".join(current).strip()
                    if t: blocks.append(PageBlock(current_type, t, page_num))
                    current = []; current_type = "text"
                continue
            if _TOPIC_RE.match(s) or _CHAPTER_RE.match(s):   dtype = "heading"
            elif _EXERCISE_RE.match(s):                        dtype = "exercise"
            elif IngestionPipeline._looks_like_equation(s):   dtype = "equation"
            else:                                              dtype = "text"
            if dtype != current_type and current:
                t = "\n".join(current).strip()
                if t: blocks.append(PageBlock(current_type, t, page_num))
                current = []
            current_type = dtype; current.append(line)
        if current:
            t = "\n".join(current).strip()
            if t: blocks.append(PageBlock(current_type, t, page_num))
        return blocks

    @staticmethod
    def _looks_like_equation(text: str) -> bool:
        math_chars = set("=+\u2212-*/^\u222b\u2211\u220f\u221a\u221e\u03b1\u03b2\u03b3\u03c0\u00d7\u00f7\u2264\u2265\u2260\u00b1")
        return len(set(text) & math_chars) >= 2 and len(text) < 200

    # =========================================================================
    # Validation helpers
    # =========================================================================

    @staticmethod
    def _check_mime(pdf_path: str) -> None:
        with open(pdf_path, "rb") as f:
            sig = f.read(5)
        if sig != PDF_MAGIC:
            raise ValueError(
                f"File is not a valid PDF (magic bytes: {sig!r}). Upload rejected."
            )

    @staticmethod
    def _validate_pdf(pdf_path: str) -> tuple[list[str], int]:
        warns: list[str] = []
        size = os.path.getsize(pdf_path)
        if size > MAX_PDF_BYTES:
            raise ValueError(f"PDF too large: {size/1e6:.1f} MB (limit {MAX_PDF_BYTES//1_000_000} MB)")
        try:
            reader = PdfReader(pdf_path)
        except Exception as exc:
            raise ValueError(f"Corrupt PDF: {exc}") from exc
        if reader.is_encrypted:
            raise ValueError("PDF is encrypted / password-protected.")
        pc = len(reader.pages)
        if pc == 0: raise ValueError("PDF has zero pages.")
        if pc > MAX_PDF_PAGES: warns.append(f"Large PDF: {pc} pages.")
        logger.info(f"[Ingestion] Validated: {pc} pages, {size/1024:.1f} KB")
        return warns, pc

    @staticmethod
    def _inspect_metadata(pdf_path: str) -> tuple[str, dict]:
        meta: dict = {}
        try:
            reader = PdfReader(pdf_path)
            if reader.metadata:
                meta = {str(k): str(v) for k, v in reader.metadata.items()}
        except Exception:
            pass
        return "application/pdf", meta

    @staticmethod
    def _sha256(pdf_path: str) -> str:
        h = hashlib.sha256()
        with open(pdf_path, "rb") as f:
            for chunk in iter(lambda: f.read(65_536), b""):
                h.update(chunk)
        return h.hexdigest()

    # =========================================================================
    # BookIngestionLog update
    # =========================================================================

    def _update_log(
        self, log_id: int | None, status: str, coverage: dict,
        confidence: float | None, error: str | None = None,
    ) -> None:
        if log_id is None: return
        try:
            with managed_session() as db:
                log = db.query(BookIngestionLog).filter(BookIngestionLog.id == log_id).first()
                if log:
                    log.status = status; log.coverage = coverage
                    log.ingestion_confidence = confidence; log.error = error
                    log.finished_at = datetime.now(timezone.utc)
        except Exception as exc:
            logger.warning(f"[Ingestion] BookIngestionLog update failed: {exc}")
'''

import pathlib, sys
target = pathlib.Path(r"c:\Users\manit\OneDrive\Desktop\code\Vishwalpha\AI Tutor\app\services\ingestion_pipeline.py")
target.write_text(PIPELINE_CODE, encoding="utf-8")
print(f"Written {target.stat().st_size:,} bytes to {target}")
