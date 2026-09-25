"""
app/services/ingestion/structure_detector.py
──────────────────────────────────────────────
Stage 11: Hierarchical structure detection + LLM fallback.

Converts a flat list of PageBlocks into a list of IngestionSections.

Detection priority:
  1. paddlex heading blocks (block_type == "heading")
  2. Regex numbered sections  "X.Y Title" / "X.Y.Z Title"
  3. Chapter-level markers   "Chapter X" / "Unit X"
  4. Exercise / example blocks
  5. LLM fallback via _structure_chunk_cached (when ≤1 section found)

Also exposes _classify_level() used by the main pipeline when deciding
whether a topic is a subtopic (level 2) or top-level (level 0/1).
"""
from __future__ import annotations

import json
import logging
import re

from app.services.ingestion.models import (
    CHAPTER_RE, EXERCISE_RE, TOPIC_RE,
    IngestionSection, PageBlock,
)

logger = logging.getLogger(__name__)


def classify_level(heading: str) -> int:
    """
    Classifies the structural depth of a heading.
      0 → chapter / unit level
      1 → section / topic level (default)
      2 → subsection / subtopic
    """
    h = heading.lower().strip()
    if re.match(r"^chapter\s+\d+", h) or re.match(r"^unit\s+", h):
        return 0
    if re.match(r"^\d+\.\d+\.\d+", h):
        return 2
    if re.match(r"^\d+\.\d+", h):
        return 1
    return 1


def detect_structure(
    blocks: list[PageBlock],
    chapter_title: str,
    llm_fallback_fn,
) -> list[IngestionSection]:
    """
    Converts flat PageBlocks into IngestionSections using structural heuristics.

    Args:
        blocks:           Flat list of PageBlocks after stages 7-10.
        chapter_title:    Fallback heading for the root section.
        llm_fallback_fn:  Callable(full_text, chapter) → dict | None.
                          Called once if heuristics produce ≤1 section.
                          The pipeline passes its _structure_chunk_cached method.

    Returns a non-empty list of IngestionSection objects.
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
            level   = classify_level(heading)

        elif m := TOPIC_RE.match(text):
            is_hdg  = True
            maj, mn, sub, rest = m.group(1), m.group(2), m.group(3), m.group(4)
            heading = rest.strip()
            tnum    = f"{maj}.{mn}" + (f".{sub}" if sub else "")
            level   = 1 if not sub else 2

        elif CHAPTER_RE.match(text):
            is_hdg  = True
            heading = text
            level   = 0

        elif EXERCISE_RE.match(text):
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

    # ── LLM fallback when no meaningful structure was detected ────────────────
    if len(sections) <= 1 and sections and len(sections[0].blocks) > 0:
        full_text = "\n\n".join(b.text for b in sections[0].blocks)
        llm_secs  = _llm_structure_fallback(full_text, chapter_title, llm_fallback_fn)
        if len(llm_secs) > 1:
            logger.info(f"[Ingestion] LLM fallback: {len(llm_secs)} sections")
            return llm_secs

    logger.info(f"[Ingestion] Structure: {len(sections)} section(s) detected")
    return sections


def _llm_structure_fallback(
    full_text: str,
    chapter_title: str,
    llm_fallback_fn,
) -> list[IngestionSection]:
    """
    When heuristic detection fails, ask the LLM to split the raw text into sections.
    Uses the same STRUCTURE_PROMPT as the main enrichment pass.
    Returns a list of IngestionSection objects, or [] on failure.
    """
    try:
        data = llm_fallback_fn(full_text[:4000], chapter_title)
        if not data or "sections" not in data:
            return []
        secs: list[IngestionSection] = []
        for s in data["sections"]:
            heading = s.get("heading") or chapter_title
            text    = s.get("repaired_text", "")
            if not text.strip():
                continue
            blk = PageBlock("text", text, 0)
            sec = IngestionSection(
                heading=heading,
                heading_level=1,
                blocks=[blk],
                summary=s.get("summary", ""),
                keywords=s.get("keywords", []),
                prerequisites=s.get("prerequisites", []),
                confidence=0.8,
            )
            secs.append(sec)
        return secs
    except Exception as exc:
        logger.warning(f"[Ingestion] LLM structure fallback failed: {exc}")
        return []


# ── Stage 14: Quality gate ────────────────────────────────────────────────────

def score_section(sec: IngestionSection, min_section_chars: int = 80) -> float:
    """
    Computes a 0.0–1.0 confidence score for a section:
      +0.5  meaningful text (>= min_section_chars)
      +0.3  specific heading (not generic)
      +0.2  has enrichment (summary or keywords)
    """
    all_text = "\n".join(b.text for b in sec.blocks)
    h        = (sec.heading or "").strip().lower()
    score    = 0.0
    if len(all_text) >= min_section_chars:
        score += 0.5
    if h and h not in {"general", "untitled", "unknown", "section", "introduction", ""}:
        score += 0.3
    if sec.summary or sec.keywords:
        score += 0.2
    return round(score, 2)
