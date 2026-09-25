"""
app/services/ingestion/pdf_extractor.py
─────────────────────────────────────────
Stages 0-6: PDF validation, metadata, hashing, and per-page analysis.

Stages:
  0 - MIME / magic-byte security check
  1 - File existence (caller's responsibility)
  2 - File validation (size, encryption, page count)
  3 - PDF metadata inspection
  4 - SHA-256 hash for duplicate detection
  6 - Per-page layout analysis (digital + scanned paths)

None of these functions touch the database.
"""
from __future__ import annotations

import hashlib
import logging

from app.services.ingestion.models import (
    MAX_PDF_BYTES, MAX_PDF_PAGES, MIN_TEXT_PER_PAGE,
    PageAnalysis, PageBlock,
    TOPIC_RE, CHAPTER_RE, EXERCISE_RE,
    PDF_MAGIC,
)
from app.services.ingestion.ocr_helpers import (
    get_layout_pipeline,
    page_to_image,
    ocr_with_confidence,
    ocr_table,
    ocr_math,
    looks_like_equation,
    paddlex_analyse_image,
)

logger = logging.getLogger(__name__)

try:
    import fitz  # type: ignore
except ImportError:
    fitz = None

from PyPDF2 import PdfReader


# ── Stage 0: MIME check ───────────────────────────────────────────────────────

def check_mime(pdf_path: str) -> None:
    """Raises ValueError if the file does not start with the PDF magic bytes."""
    with open(pdf_path, "rb") as f:
        sig = f.read(5)
    if sig != PDF_MAGIC:
        raise ValueError(
            f"File is not a valid PDF (magic bytes: {sig!r}). Upload rejected."
        )


# ── Stage 2: Validation ───────────────────────────────────────────────────────

def validate_pdf(pdf_path: str) -> tuple[list[str], int]:
    """
    Validates PDF size, encryption, and page count.
    Returns (warnings, page_count).
    Raises ValueError for fatal issues (too large, encrypted, corrupt, zero pages).
    """
    import os
    warns: list[str] = []
    size = os.path.getsize(pdf_path)
    if size > MAX_PDF_BYTES:
        raise ValueError(
            f"PDF too large: {size/1e6:.1f} MB (limit {MAX_PDF_BYTES//1_000_000} MB)"
        )
    pc = 0
    if fitz is not None:
        try:
            doc = fitz.open(pdf_path)
            if doc.is_encrypted:
                raise ValueError("PDF is encrypted / password-protected.")
            pc = len(doc)
        except Exception as exc:
            if "encrypted" in str(exc).lower():
                raise
            logger.warning(f"[Ingestion] PyMuPDF validation failed: {exc}")

    if pc == 0:
        try:
            reader = PdfReader(pdf_path)
        except Exception as exc:
            raise ValueError(f"Corrupt PDF: {exc}") from exc
        if reader.is_encrypted:
            raise ValueError("PDF is encrypted / password-protected.")
        pc = len(reader.pages)

    if pc == 0:
        raise ValueError("PDF has zero pages.")
    if pc > MAX_PDF_PAGES:
        warns.append(f"Large PDF: {pc} pages.")
    import os as _os
    logger.info(f"[Ingestion] Validated: {pc} pages, {size/1024:.1f} KB")
    return warns, pc


# ── Stage 3: Metadata ─────────────────────────────────────────────────────────

def inspect_metadata(pdf_path: str) -> tuple[str, dict]:
    """
    Extracts PDF metadata (author, title, creator, etc.).
    Returns ("application/pdf", metadata_dict).
    """
    meta: dict = {}
    if fitz is not None:
        try:
            doc = fitz.open(pdf_path)
            if doc.metadata:
                meta = {str(k): str(v) for k, v in doc.metadata.items()}
        except Exception:
            pass
    if not meta:
        try:
            reader = PdfReader(pdf_path)
            if reader.metadata:
                meta = {str(k): str(v) for k, v in reader.metadata.items()}
        except Exception:
            pass
    return "application/pdf", meta


# ── Stage 4: SHA-256 hash ─────────────────────────────────────────────────────

def sha256_file(pdf_path: str) -> str:
    """Returns the SHA-256 hex digest of the file (streamed, 64 KB chunks)."""
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(65_536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Stage 6: Per-page analysis ────────────────────────────────────────────────

def analyse_pages(pdf_path: str, page_count: int) -> list[PageAnalysis]:
    """
    Extracts all pages from the PDF and analyses each one:
    - Digital pages → heuristic block split.
    - Scanned pages → paddlex layout detection + Tesseract OCR fallback.
    Returns a list of PageAnalysis objects (one per page).
    """
    pipeline = get_layout_pipeline()
    pages_text: list[str] = []

    # Prefer PyMuPDF for text extraction (faster, better quality)
    if fitz is not None:
        try:
            doc = fitz.open(pdf_path)
            pages_text = [page.get_text() or "" for page in doc]
        except Exception as exc:
            logger.warning(
                f"[Ingestion] PyMuPDF extract failed: {exc}, falling back to PyPDF2"
            )
            pages_text = []

    if not pages_text:
        try:
            reader = PdfReader(pdf_path)
            for page in reader.pages:
                try:
                    pages_text.append(page.extract_text() or "")
                except Exception as exc:
                    logger.warning(
                        f"[Ingestion] PyPDF2 page extract failed ({exc}), "
                        "treating as empty/scanned"
                    )
                    pages_text.append("")
        except Exception as exc:
            logger.warning(f"[Ingestion] PyPDF2 failed: {exc}")
            pages_text = [""] * page_count

    results = []
    for i, raw_text in enumerate(pages_text):
        pn      = i + 1
        scanned = len(raw_text.strip()) < MIN_TEXT_PER_PAGE
        if scanned:
            pa = _analyse_scanned_page(pdf_path, pn, pipeline)
        else:
            pa = _analyse_digital_page(raw_text, pn, pipeline)
        results.append(pa)
        logger.debug(f"[Ingestion] p{pn} scanned={scanned} blocks={len(pa.blocks)}")
    return results


def _analyse_digital_page(raw_text: str, page_num: int, pipeline) -> PageAnalysis:
    blocks = heuristic_block_split(raw_text, page_num)
    return PageAnalysis(
        page_num=page_num, is_scanned=False,
        ocr_confidence=None, blocks=blocks,
        raw_lines=[b.text for b in blocks],
    )


def _analyse_scanned_page(pdf_path: str, page_num: int, pipeline) -> PageAnalysis:
    img = page_to_image(pdf_path, page_num)
    if img is None:
        return PageAnalysis(page_num=page_num, is_scanned=True, ocr_confidence=None)

    blocks: list[PageBlock] = []
    avg_conf: float | None  = None

    if pipeline:
        try:
            blocks, avg_conf = paddlex_analyse_image(img, page_num, pipeline)
        except Exception as exc:
            logger.debug(f"[Ingestion] paddlex image p{page_num}: {exc}")

    if not blocks:
        text, avg_conf = ocr_with_confidence(img)
        if text.strip():
            btype = "equation" if looks_like_equation(text) else "text"
            blocks = [PageBlock(btype, text, page_num, avg_conf)]

    return PageAnalysis(
        page_num=page_num, is_scanned=True,
        ocr_confidence=avg_conf, blocks=blocks,
        raw_lines=[b.text for b in blocks],
    )


# ── Stage 6 helpers: heuristic block split (digital pages) ───────────────────

def heuristic_block_split(text: str, page_num: int) -> list[PageBlock]:
    """
    Splits digital-page text into typed PageBlocks using regex heuristics.
    No ML / OCR used here — purely text-pattern based.
    """
    blocks: list[PageBlock] = []
    current_type = "text"
    current: list[str] = []

    for line in text.splitlines():
        s = line.strip()
        if not s:
            if current:
                t = "\n".join(current).strip()
                if t:
                    blocks.append(PageBlock(current_type, t, page_num))
                current = []
                current_type = "text"
            continue

        if   TOPIC_RE.match(s) or CHAPTER_RE.match(s):   dtype = "heading"
        elif EXERCISE_RE.match(s):                         dtype = "exercise"
        elif looks_like_equation(s):                       dtype = "equation"
        else:                                              dtype = "text"

        if dtype != current_type and current:
            t = "\n".join(current).strip()
            if t:
                blocks.append(PageBlock(current_type, t, page_num))
            current = []
        current_type = dtype
        current.append(line)

    if current:
        t = "\n".join(current).strip()
        if t:
            blocks.append(PageBlock(current_type, t, page_num))
    return blocks
