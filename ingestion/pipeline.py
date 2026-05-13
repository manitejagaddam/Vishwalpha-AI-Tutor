"""
ingestion/pipeline.py
─────────────────────
Orchestrates the complete PDF ingestion pipeline.

Flow:
  PDF → Parse → TextStructurer (raw sections)
      → LLMStructureRepair.repair_section() per section
          → heading + repaired_text + summary + keywords
      → Qdrant curriculum_routing  (summary embedding, for semantic routing)
      → Qdrant curriculum_content  (repaired text embedding, for RAG retrieval)
      → PostgreSQL                 (structured hierarchy storage)
      → canonical JSON export      (snapshot of everything ingested)
"""

import os
import logging
from schemas import ProcessedSection, CanonicalCurriculum
from ingestion.parser import PDFParser
from ingestion.structurer import TextStructurer
from ingestion.llm_repair import LLMStructureRepair, RepairedSection
from routing.router import SemanticRouter
from retrieval.engine import RetrievalEngine
from db.writer import save_to_postgres

logger = logging.getLogger(__name__)


def ingest_pdf(pdf_path: str, class_num: int, subject: str, chapter: str) -> None:
    """
    Entry point for the ingestion pipeline.

    Args:
        pdf_path  : Absolute or relative path to the PDF file.
        class_num : Class number, e.g. 10.
        subject   : Subject name, e.g. "Science".
        chapter   : Chapter title, e.g. "Chemical Reactions and Equations".
    """
    logger.info("=" * 60)
    logger.info(f"INGESTING: {pdf_path}")
    logger.info(f"Class: {class_num} | Subject: {subject} | Chapter: {chapter}")
    logger.info("=" * 60)

    # ── STEP 1: Parse ─────────────────────────────────────────────────────────
    raw_sections = _parse_and_structure(pdf_path)
    if not raw_sections:
        logger.error("No sections detected. Aborting ingestion.")
        return

    # ── STEP 2: LLM Repair + Qdrant Storage ──────────────────────────────────
    processed_sections = _repair_and_store(
        raw_sections=raw_sections,
        class_num=class_num,
        subject=subject,
        chapter=chapter,
    )
    if not processed_sections:
        logger.error("No sections were successfully processed. Aborting.")
        return

    # ── STEP 3: PostgreSQL ────────────────────────────────────────────────────
    logger.info("STEP 3: Saving to PostgreSQL...")
    save_to_postgres(class_num, subject, chapter, processed_sections)

    # ── STEP 4: Canonical JSON export ────────────────────────────────────────
    logger.info("STEP 4: Exporting canonical JSON...")
    _export_json(pdf_path, class_num, subject, chapter, processed_sections)

    logger.info("=" * 60)
    logger.info(
        f"INGESTION COMPLETE: {len(processed_sections)} sections "
        f"saved to PostgreSQL + Qdrant"
    )
    logger.info("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_and_structure(pdf_path: str) -> list[dict]:
    """
    Steps 1 & 2 of the pipeline:
      - Parses the PDF into elements with font metadata.
      - Groups elements into raw sections using deterministic rules
        (section numbering patterns + bold/large font signals).

    Returns a list of raw section dicts:
      [{"title": "1.1 ...", "section_number": "1.1", "chunks": ["...", ...]}, ...]
    """
    logger.info("STEP 1: Parsing PDF + detecting raw sections...")

    parser = PDFParser(use_ocr=False)
    parsed_pages = parser.parse(pdf_path)
    logger.info(f"  Parsed {len(parsed_pages)} pages")

    total_elements = sum(len(p.get("elements", [])) for p in parsed_pages)
    header_count = sum(
        1 for p in parsed_pages
        for e in p.get("elements", [])
        if e["type"] == "Header"
    )
    logger.info(f"  Elements: {total_elements} total, {header_count} headers")

    structurer = TextStructurer(max_chunk_chars=800)
    raw_sections = structurer.structure(parsed_pages)
    logger.info(f"  Detected {len(raw_sections)} raw sections")

    for i, s in enumerate(raw_sections):
        logger.info(
            f"    [{s.get('section_number', '')}] {s['title']} "
            f"({len(s['chunks'])} chunks)"
        )

    return raw_sections


def _repair_and_store(
    raw_sections: list[dict],
    class_num: int,
    subject: str,
    chapter: str,
) -> list[ProcessedSection]:
    """
    Step 2 of the pipeline — for each raw section:
      1. Sends raw content to the LLM → repairs text + generates heading + summary.
      2. Embeds the summary into Qdrant `curriculum_routing` (for semantic routing).
      3. Embeds the repaired text into Qdrant `curriculum_content` (for RAG retrieval).

    Returns the list of ProcessedSection objects ready for DB storage.
    """
    logger.info("STEP 2: LLM repair + Qdrant storage (one call per section)...")

    repairer = LLMStructureRepair()
    router = SemanticRouter()
    retrieval_engine = RetrievalEngine()

    processed: list[ProcessedSection] = []

    for i, raw in enumerate(raw_sections):
        raw_content = "\n\n".join(raw["chunks"])

        if not raw_content.strip():
            logger.warning(f"  Skipping empty section: \"{raw['title']}\"")
            continue

        logger.info(
            f"  [{i+1}/{len(raw_sections)}] Processing: \"{raw['title']}\"..."
        )

        # LLM: repair content + generate heading + summary
        repaired: RepairedSection = repairer.repair_section(
            raw_content=raw_content,
            section_hint=raw["title"],
        )

        section = ProcessedSection(
            heading=repaired.heading,
            section_number=raw.get("section_number", ""),
            repaired_text=repaired.repaired_text,
            summary=repaired.summary,
            keywords=repaired.keywords,
        )
        processed.append(section)

        # Qdrant routing — embed summary so the router can map queries to topics
        router.add_route(
            class_num=class_num,
            subject=subject,
            chapter=chapter,
            topic=section.heading,
            summary=section.summary,
        )

        # Qdrant content — embed repaired text for RAG retrieval
        retrieval_engine.upsert_chunk(
            metadata={
                "class": class_num,
                "subject": subject,
                "chapter": chapter,
                "topic": section.heading,
            },
            text=section.repaired_text,
        )

        logger.info(
            f"  ✓ \"{section.heading}\" → Qdrant routing + content stored"
        )

    return processed


def _export_json(
    pdf_path: str,
    class_num: int,
    subject: str,
    chapter: str,
    sections: list[ProcessedSection],
) -> None:
    """
    Serialises the full ingestion result to a canonical JSON file next to the PDF.
    Filename: <pdf_stem>_canonical.json
    """
    canonical = CanonicalCurriculum(
        board="NCERT",
        class_num=class_num,
        subject=subject,
        chapter=chapter,
        section_count=len(sections),
        sections=sections,
    )
    base_name = os.path.basename(pdf_path).replace(".pdf", "")
    json_path = os.path.join(os.path.dirname(pdf_path), f"{base_name}_canonical.json")
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(canonical.model_dump_json(by_alias=True, indent=2))
    logger.info(f"  Canonical JSON saved: {json_path}")
