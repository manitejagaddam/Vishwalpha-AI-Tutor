"""
scripts/extract_json.py
────────────────────────
Stage 1 of the two-step ingestion pipeline: PDF → LLM → JSON.

Runs OCR + PaddleX layout analysis + LLM structuring on a PDF chapter
and dumps the result to a JSON file.

NO database interaction of any kind.
NO embeddings.
NO Board/Class/Subject hierarchy.

The JSON output is the input format for scripts/json_to_db.py.
Use this script to:
  - Cross-check LLM output before committing to DB.
  - Re-run structuring after changing the STRUCTURE_PROMPT.
  - Inspect raw sections for quality review.

Usage:
  uv run python -m scripts.extract_json path/to/chapter.pdf \
      --chapter "Chemical Reactions and Equations" \
      [--out path/to/output.json]

  If --out is omitted the JSON is saved next to the PDF as:
    <pdf_dir>/json_files/ingest_debug_<pdf_basename>.json
"""
import argparse
import hashlib
import json
import logging
import os
import re
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

RAW_CHUNK_SIZE       = 4000
CONFIDENCE_THRESHOLD = 0.5
MIN_SECTION_CHARS    = 80

STRUCTURE_PROMPT = """\
You are an expert curriculum parser working on NCERT textbook content for chapter '{chapter}'.
You will receive raw OCR text that may contain extraction artifacts.

Your job has three parts: CLEAN, SEGMENT, and STRUCTURE.

STEP 1 - CLEAN (repair, do not paraphrase):
- Collapse OCR duplication artifacts into the single correct reading.
- Fix broken words, spacing, and punctuation.
- EXCEPTION: chemical equations, formulas, and math expressions — preserve EXACTLY.
- Do not paraphrase, simplify, or rewrite sentences.

STEP 2 - SEGMENT:
- Group text into logical sections by topic, not by page boundary.
- Merge fragments that are too short to stand alone.
- Classify each section's content_type as one of: concept, activity, example, question, equation_block, table.

STEP 3 - STRUCTURE each section as JSON:
- heading: descriptive title from the content itself, never a bare label like "Activity 1.5" or "Questions".
- content_type: one of the types above.
- repaired_text: full cleaned text.
- summary: 2-4 declarative sentences stating what the section says (no meta-descriptions).
- keywords: 3-8 specific terms present in this section.
- prerequisites: only concepts directly implied by this section's content.
- difficulty_level: foundational | intermediate | advanced.

OUTPUT RULES:
- Output ONLY valid JSON. No markdown, no commentary.
- If input is pure noise, return {{"sections": []}}.

SCHEMA:
{{
  "sections": [
    {{
      "heading": "String",
      "content_type": "concept | activity | example | question | equation_block | table",
      "repaired_text": "String",
      "summary": "String",
      "keywords": ["String"],
      "prerequisites": ["String"],
      "difficulty_level": "foundational | intermediate | advanced"
    }}
  ]
}}

Text to structure:
{text}
"""

_TOPIC_RE    = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?\s+(.+)$", re.MULTILINE)
_CHAPTER_RE  = re.compile(r"^(?:chapter\s+\d+|unit\s+[ivxIVX\d]+)\b", re.IGNORECASE)
_EXERCISE_RE = re.compile(r"^(?:exercise\s+\d+|example\s+\d+|activity\s+\d+|think\s+and\s+discuss)", re.IGNORECASE)
_INJECTION_RE = re.compile(r"(ignore\s+previous\s+instructions|system\s*:|\<\|im_start\|\>|\<\|endoftext\|\>|assistant\s*:|`\s*system)", re.IGNORECASE)
_WATERMARK_RE = re.compile(r"^\s*(sample\s+copy|do\s+not\s+distribute|draft|confidential|for\s+review\s+only|not\s+for\s+sale|preview\s+copy)\s*$", re.IGNORECASE | re.MULTILINE)


def _get_openai():
    from app.infra.azure_openai_client import get_openai as _g
    from app.config import settings as s
    return _g(), s


def _extract_text_heuristic(pdf_path):
    from PyPDF2 import PdfReader
    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        pages.append({"page_num": i + 1, "text": text})
    return pages


def _extract_text_paddlex(pipeline, pdf_path):
    try:
        results = list(pipeline(pdf_path))
        pages = []
        for result in results:
            page_num = result.get("page_num", 0) + 1
            texts = []
            for block in result.get("layout_result", {}).get("boxes", []):
                label = block.get("label", "")
                text  = block.get("text", "").strip()
                if text and label in ("text", "title", "table", "equation"):
                    texts.append(text)
            pages.append({"page_num": page_num, "text": "\n\n".join(texts)})
        return pages
    except Exception as exc:
        logger.warning(f"PaddleX extraction failed ({exc}); falling back to heuristic.")
        return _extract_text_heuristic(pdf_path)


def _detect_sections(pages):
    sections = []
    current_heading = "Introduction"
    current_blocks  = []
    sec_idx = 0
    for page in pages:
        for line in page["text"].split("\n"):
            line = line.strip()
            if not line:
                continue
            if _TOPIC_RE.match(line) or _CHAPTER_RE.match(line) or _EXERCISE_RE.match(line):
                if current_blocks:
                    sections.append({"heading": current_heading, "blocks": current_blocks, "sec_idx": sec_idx})
                    sec_idx += 1
                current_heading = line
                current_blocks  = []
            else:
                current_blocks.append(line)
    if current_blocks:
        sections.append({"heading": current_heading, "blocks": current_blocks, "sec_idx": sec_idx})
    return sections


def _score_section(heading, text):
    h = (heading or "").strip().lower()
    score = 0.0
    if len(text) >= MIN_SECTION_CHARS: score += 0.5
    if h and h not in {"general","untitled","unknown","section","introduction",""}: score += 0.3
    return round(score, 2)


def _call_llm(client, settings, text, chapter):
    prompt = STRUCTURE_PROMPT.format(chapter=chapter, text=text)
    try:
        resp = client.chat.completions.create(
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "You are an expert curriculum parser."},
                {"role": "user",   "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as exc:
        logger.warning(f"LLM call failed: {exc}")
        return None


def extract(pdf_path, chapter, out_path=None):
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if out_path is None:
        pdf_dir  = os.path.dirname(os.path.abspath(pdf_path))
        json_dir = os.path.join(pdf_dir, "json_files")
        os.makedirs(json_dir, exist_ok=True)
        out_path = os.path.join(json_dir, f"ingest_debug_{os.path.basename(pdf_path)}.json")

    client, settings = _get_openai()

    logger.info(f"Extracting text from: {pdf_path}")
    try:
        from paddlex import create_pipeline  # type: ignore
        pipeline = create_pipeline(pipeline="layout_parsing")
        pages = _extract_text_paddlex(pipeline, pdf_path)
    except Exception:
        pages = _extract_text_heuristic(pdf_path)
    logger.info(f"Extracted {len(pages)} pages.")

    sections = _detect_sections(pages)
    logger.info(f"Detected {len(sections)} sections.")

    llm_output_data = {}
    for sec in sections:
        raw_text = "\n\n".join(sec["blocks"])
        raw_text = _INJECTION_RE.sub("[REMOVED]", raw_text)
        raw_text = _WATERMARK_RE.sub("", raw_text)
        score = _score_section(sec["heading"], raw_text)
        if score < CONFIDENCE_THRESHOLD:
            logger.warning(f"Skipping '{sec['heading']}' (score={score:.2f})")
            continue
        sec_key = f"{sec['sec_idx']}:{sec['heading']}"
        logger.info(f"Structuring: '{sec['heading']}'")
        data = _call_llm(client, settings, raw_text[:RAW_CHUNK_SIZE], chapter)
        if not data:
            logger.warning(f"Retrying LLM for '{sec['heading']}'...")
            data = _call_llm(client, settings, raw_text[:RAW_CHUNK_SIZE], chapter)
        if data:
            llm_output_data[sec_key] = {"raw_blocks": sec["blocks"], "llm_data": data}
        else:
            logger.warning(f"LLM failed twice for '{sec['heading']}' — section excluded.")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(llm_output_data, f, indent=2, ensure_ascii=False)
    logger.info(f"JSON written to: {out_path}  ({len(llm_output_data)} sections)")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Extract LLM-structured JSON from a PDF chapter. No DB interaction.")
    parser.add_argument("pdf_path",  help="Path to the PDF file.")
    parser.add_argument("--chapter", required=True, help="Chapter title for the LLM prompt.")
    parser.add_argument("--out",     default=None,  help="Output JSON path (optional).")
    parser.add_argument("--log-file", action="store_true", help="Write logs to logs/ instead of terminal.")
    args = parser.parse_args()

    if args.log_file:
        from datetime import datetime
        os.makedirs("logs", exist_ok=True)
        log_fn = os.path.join("logs", f"extract_json_{datetime.now().strftime('%Y%m%d')}.log")
        root = logging.getLogger()
        for h in root.handlers[:]: root.removeHandler(h)
        fh = logging.FileHandler(log_fn, mode="a", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        root.addHandler(fh)
        print(f"Logging redirected to {log_fn}")

    try:
        out_path = extract(args.pdf_path, args.chapter, args.out)
        print(f"\n[SUCCESS] Extraction complete!")
        print(f"   JSON saved to : {out_path}")
        print(f"\n   Review the JSON, then insert into DB with:")
        print(f"     uv run python -m scripts.json_to_db \"{out_path}\" \\")
        print(f"       --board NCERT --class <N> --subject <SUBJ> \\")
        print(f"       --book-title \"...\" --book-key \"...\" \\")
        print(f"       --chapter \"{args.chapter}\" --chapter-num <N>")
    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}", file=sys.stderr); sys.exit(1)
    except Exception as e:
        import traceback
        print(f"\n[ERROR] {e}", file=sys.stderr); traceback.print_exc(); sys.exit(1)


if __name__ == "__main__":
    main()
