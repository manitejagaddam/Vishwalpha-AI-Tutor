"""
app/services/ingestion/text_processor.py
──────────────────────────────────────────
Stages 7-10: Post-extraction text cleaning passes.

Stage 7 - Header/footer stripping (lines appearing on >50% of pages)
Stage 8 - Watermark / annotation removal
Stage 9 - Cross-page sentence stitching
Stage 10 - Prompt-injection sanitisation

All functions are pure transforms on lists of PageBlock — no I/O, no DB.
"""
from __future__ import annotations

import logging
from collections import Counter

from app.services.ingestion.models import (
    HEADER_FOOTER_FREQ,
    INJECTION_RE,
    WATERMARK_RE,
    PageBlock,
)

logger = logging.getLogger(__name__)


# ── Stage 7: Header/footer stripping ─────────────────────────────────────────

def strip_headers_footers(
    blocks: list[PageBlock], page_count: int
) -> list[PageBlock]:
    """
    Removes text lines that appear on more than HEADER_FOOTER_FREQ of pages
    (likely running headers / page numbers / footers).
    Skips processing for very short documents (< 3 pages).
    """
    if page_count < 3:
        return blocks

    line_counts: Counter = Counter()
    for blk in blocks:
        for line in blk.text.splitlines():
            if line.strip():
                line_counts[line.strip()] += 1

    cutoff   = max(2, int(HEADER_FOOTER_FREQ * page_count))
    hf_lines = {line for line, n in line_counts.items() if n >= cutoff}

    if not hf_lines:
        return blocks

    result = []
    for blk in blocks:
        cleaned = "\n".join(
            line for line in blk.text.splitlines()
            if line.strip() not in hf_lines
        ).strip()
        if cleaned:
            result.append(PageBlock(blk.block_type, cleaned, blk.page_num, blk.ocr_confidence))

    logger.info(f"[Ingestion] Stripped {len(hf_lines)} header/footer pattern(s)")
    return result


# ── Stage 8: Watermark removal ────────────────────────────────────────────────

def strip_watermarks(
    blocks: list[PageBlock], warnings: list[str]
) -> list[PageBlock]:
    """
    Removes common watermark / sample-copy annotations (see WATERMARK_RE).
    Appends a warning if any watermarks were found.
    """
    found  = False
    result = []
    for blk in blocks:
        cleaned = WATERMARK_RE.sub("", blk.text).strip()
        if cleaned != blk.text.strip():
            found = True
        if cleaned:
            result.append(PageBlock(blk.block_type, cleaned, blk.page_num, blk.ocr_confidence))
    if found:
        warnings.append("Watermark/sample-copy text detected and removed.")
    return result


# ── Stage 9: Cross-page sentence stitching ────────────────────────────────────

def stitch_cross_page(blocks: list[PageBlock]) -> list[PageBlock]:
    """
    Merges consecutive text blocks where the first block's last character is not
    sentence-terminal and the second block starts with a lowercase letter.
    This reconnects sentences that span page breaks.
    """
    if len(blocks) < 2:
        return blocks

    result: list[PageBlock] = []
    i = 0
    while i < len(blocks):
        blk = blocks[i]
        while (
            i + 1 < len(blocks)
            and blk.block_type == "text"
            and blocks[i + 1].block_type == "text"
            and blk.text
            and blk.text[-1] not in ".!?:\n"
            and blocks[i + 1].text
            and blocks[i + 1].text[0].islower()
        ):
            nxt = blocks[i + 1]
            # Combine OCR confidence as average of the two blocks
            combined_conf = None
            if blk.ocr_confidence is not None or nxt.ocr_confidence is not None:
                a = blk.ocr_confidence or 100.0
                b = nxt.ocr_confidence or 100.0
                combined_conf = round((a + b) / 2, 1)
            blk = PageBlock(
                "text",
                blk.text.rstrip() + " " + nxt.text.lstrip(),
                blk.page_num,
                combined_conf,
            )
            i += 1
        result.append(blk)
        i += 1
    return result


# ── Stage 10: Prompt-injection sanitisation ───────────────────────────────────

def sanitise_blocks(blocks: list[PageBlock]) -> list[PageBlock]:
    """
    Replaces any prompt-injection patterns in block text with "[REDACTED]".
    Logs a warning if any were found.
    """
    found  = False
    result = []
    for blk in blocks:
        cleaned = INJECTION_RE.sub("[REDACTED]", blk.text)
        if cleaned != blk.text:
            found = True
        result.append(PageBlock(blk.block_type, cleaned, blk.page_num, blk.ocr_confidence))
    if found:
        logger.warning("[Ingestion] Prompt-injection pattern(s) redacted.")
    return result
