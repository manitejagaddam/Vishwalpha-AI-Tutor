"""
app/services/ingestion/models.py
─────────────────────────────────
Shared dataclasses and constants for the ingestion pipeline.
Kept in one place so all sub-modules import from here instead of re-defining.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Pipeline constants ────────────────────────────────────────────────────────

MAX_PDF_BYTES          = 100 * 1024 * 1024   # 100 MB hard limit
MAX_PDF_PAGES          = 500                   # warn above this
MIN_TEXT_PER_PAGE      = 50                    # chars; below → OCR
MIN_SECTION_CHARS      = 80                    # quality gate
CONFIDENCE_THRESHOLD   = 0.5                   # below → skip section
RAW_CHUNK_SIZE         = 4000                  # chars sent to LLM for structuring
INGEST_DUP_TTL         = 60 * 60 * 24 * 365   # 1 year duplicate TTL
OCR_LOW_CONF_THRESHOLD = 60.0                  # avg OCR confidence %
HEADER_FOOTER_FREQ     = 0.5                   # >50% pages = header/footer
PDF_MAGIC              = b"%PDF-"

# ── Compiled regexes ─────────────────────────────────────────────────────────

INJECTION_RE = re.compile(
    r"(ignore\s+previous\s+instructions"
    r"|system\s*:"
    r"|<\|im_start\|>"
    r"|<\|endoftext\|>"
    r"|assistant\s*:"
    r"|```\s*system)",
    re.IGNORECASE,
)
WATERMARK_RE = re.compile(
    r"^\s*(sample\s+copy|do\s+not\s+distribute|draft|confidential"
    r"|for\s+review\s+only|not\s+for\s+sale|preview\s+copy)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
CHAPTER_RE  = re.compile(r"^(?:chapter\s+\d+|unit\s+[ivxIVX\d]+)\b", re.IGNORECASE)
TOPIC_RE    = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?\s+(.+)$", re.MULTILINE)
EXERCISE_RE = re.compile(
    r"^(?:exercise\s+\d+|example\s+\d+|activity\s+\d+|think\s+and\s+discuss)",
    re.IGNORECASE,
)

# ── Dataclasses ───────────────────────────────────────────────────────────────

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
