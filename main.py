import os
import sys
import logging
from pydantic import BaseModel, Field

# Configure logging and encoding
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)
sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

from ingestion.parser import PDFParser
from ingestion.cleaner import TextCleaner
from ingestion.structurer import TextStructurer
from ingestion.llm_repair import LLMStructureRepair, RepairedSection
from routing.router import SemanticRouter
from retrieval.engine import RetrievalEngine
from retrieval.reranker import Reranker
from db.database import init_db, SessionLocal
from db.models import Board, SchoolClass, Subject as DBSubject, Chapter as DBChapter, Topic as DBTopic, ContentChunk

# Initialize PostgreSQL tables
init_db()


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────────────────────────

class ProcessedSection(BaseModel):
    """
    A fully processed section: deterministic structure + LLM repair output.
    This is the canonical unit that flows through the rest of the pipeline.

    Fields:
        heading:       LLM-generated accurate heading for this section.
        section_number: The deterministic section number (e.g., "1.1"), if found.
        repaired_text: LLM-repaired clean content text.
        summary:       LLM-generated 2-3 sentence summary (used for Qdrant routing).
        keywords:      Key terms extracted by the LLM.
    """
    heading: str
    section_number: str = ""
    repaired_text: str
    summary: str
    keywords: list[str] = Field(default_factory=list)


class CanonicalCurriculum(BaseModel):
    """Top-level canonical document saved as JSON after ingestion."""
    board: str
    class_num: int = Field(alias="class")
    subject: str
    chapter: str
    section_count: int
    sections: list[ProcessedSection]

    model_config = {"populate_by_name": True}


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion Pipeline
# ─────────────────────────────────────────────────────────────────────────────

def ingest_pdf(pdf_path: str, class_num: int, subject: str, chapter: str):
    """
    Complete ingestion pipeline:

      PDF → Parse → Clean → Detect Sections (deterministic)
          → Repair + Generate Heading (LLM, per section)
          → Embed summary into Qdrant routing collection
          → Embed repaired content into Qdrant content collection (for RAG)
          → Save hierarchy to PostgreSQL
          → Export canonical JSON
    """
    logger.info(f"{'='*60}")
    logger.info(f"INGESTING: {pdf_path}")
    logger.info(f"Class: {class_num}, Subject: {subject}, Chapter: {chapter}")
    logger.info(f"{'='*60}")

    # ─── STEP 1: Parse PDF with font metadata ───
    logger.info("STEP 1: Parsing PDF with layout detection...")
    parser = PDFParser(use_ocr=False)
    parsed_pages = parser.parse(pdf_path)
    logger.info(f"Parsed {len(parsed_pages)} pages")

    total_elements = sum(len(p.get("elements", [])) for p in parsed_pages)
    header_count = sum(
        1 for p in parsed_pages
        for e in p.get("elements", [])
        if e["type"] == "Header"
    )
    logger.info(f"Total elements: {total_elements}, Headers detected: {header_count}")

    # ─── STEP 2: Deterministic section detection ───
    # TextStructurer groups elements into loose topic sections using section
    # numbering and bold/large font signals. These raw groups are then sent
    # individually to the LLM for repair and proper heading generation.
    logger.info("STEP 2: Detecting raw sections deterministically...")
    structurer = TextStructurer(max_chunk_chars=800)
    raw_sections = structurer.structure(parsed_pages)
    logger.info(f"Found {len(raw_sections)} raw sections")

    for i, s in enumerate(raw_sections):
        logger.info(
            f"  Raw section {i+1}: [{s.get('section_number', '')}] "
            f"{s['title']} ({len(s['chunks'])} chunks)"
        )

    # ─── STEP 3: LLM Repair and Heading Generation (per section) ───
    # For each raw section, we send the full raw content to the LLM which:
    #   1. Repairs OCR noise, broken sentences, etc.
    #   2. Generates an accurate heading from the actual content.
    #   3. Provides a summary used for semantic routing embeddings.
    logger.info("STEP 3: LLM repair + heading generation for each section...")
    repairer = LLMStructureRepair()
    router = SemanticRouter()
    retrieval_engine = RetrievalEngine()

    processed_sections: list[ProcessedSection] = []

    for i, raw_section in enumerate(raw_sections):
        # Reconstruct the raw content from its chunks for the LLM
        raw_content = "\n\n".join(raw_section["chunks"])

        if not raw_content.strip():
            logger.warning(f"  Skipping empty section: {raw_section['title']}")
            continue

        logger.info(
            f"  Processing section {i+1}/{len(raw_sections)}: "
            f"\"{raw_section['title']}\"..."
        )

        # Send raw content to LLM → get heading, repaired_text, summary, keywords
        repaired: RepairedSection = repairer.repair_section(
            raw_content=raw_content,
            section_hint=raw_section["title"]   # e.g., "1.1 CHEMICAL EQUA AL TIONS"
        )

        section = ProcessedSection(
            heading=repaired.heading,
            section_number=raw_section.get("section_number", ""),
            repaired_text=repaired.repaired_text,
            summary=repaired.summary,
            keywords=repaired.keywords,
        )
        processed_sections.append(section)

        # ── Store summary embedding in Qdrant routing collection ──
        # The router uses section summaries to answer: "which topic does this query belong to?"
        router.add_route(
            class_num=class_num,
            subject=subject,
            chapter=chapter,
            topic=section.heading,
            summary=section.summary,
        )

        # ── Store repaired content in Qdrant content collection (RAG) ──
        # The content collection is searched at retrieval time to get actual text
        # passages that are returned to the LLM for answering student questions.
        metadata = {
            "class": class_num,
            "subject": subject,
            "chapter": chapter,
            "topic": section.heading,
        }
        retrieval_engine.upsert_chunk(metadata, section.repaired_text)

        logger.info(
            f"  ✓ \"{section.heading}\" — stored in Qdrant routing + content"
        )

    # ─── STEP 4: Save to PostgreSQL ───
    logger.info("STEP 4: Saving hierarchy to PostgreSQL...")
    _save_to_postgres(class_num, subject, chapter, processed_sections)

    # ─── STEP 5: Export canonical JSON ───
    logger.info("STEP 5: Exporting canonical JSON...")
    canonical = CanonicalCurriculum(
        board="NCERT",
        class_num=class_num,
        subject=subject,
        chapter=chapter,
        section_count=len(processed_sections),
        sections=processed_sections,
    )
    import os as _os
    base_name = _os.path.basename(pdf_path).replace(".pdf", "")
    json_path = _os.path.join(_os.path.dirname(pdf_path), f"{base_name}_canonical.json")
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(canonical.model_dump_json(by_alias=True, indent=2))
    logger.info(f"Canonical JSON saved: {json_path}")

    logger.info(f"{'='*60}")
    logger.info(
        f"INGESTION COMPLETE: {len(processed_sections)} sections stored "
        f"in PostgreSQL + Qdrant"
    )
    logger.info(f"{'='*60}")


# ─────────────────────────────────────────────────────────────────────────────
# PostgreSQL Persistence
# ─────────────────────────────────────────────────────────────────────────────

def _save_to_postgres(
    class_num: int,
    subject: str,
    chapter_title: str,
    sections: list[ProcessedSection],
):
    """
    Persists the ingested curriculum hierarchy to PostgreSQL.

    Hierarchy:
      Board → SchoolClass → Subject → Chapter → Topic → ContentChunk

    One ProcessedSection maps to:
      - 1 Topic row  (title = LLM heading, summary = LLM summary)
      - 1 ContentChunk row (content = LLM repaired text, chunk_index = 0)
    """
    db = SessionLocal()
    try:
        # ── Board ──
        board = db.query(Board).filter(Board.name == "NCERT").first()
        if not board:
            board = Board(
                name="NCERT",
                description="National Council of Educational Research and Training"
            )
            db.add(board)
            db.commit()

        # ── Class ──
        school_class = db.query(SchoolClass).filter(
            SchoolClass.board_id == board.id,
            SchoolClass.level == class_num,
        ).first()
        if not school_class:
            school_class = SchoolClass(
                board_id=board.id,
                name=f"Class {class_num}",
                level=class_num,
            )
            db.add(school_class)
            db.commit()

        # ── Subject ──
        db_subject = db.query(DBSubject).filter(
            DBSubject.class_id == school_class.id,
            DBSubject.name == subject,
        ).first()
        if not db_subject:
            db_subject = DBSubject(class_id=school_class.id, name=subject)
            db.add(db_subject)
            db.commit()

        # ── Chapter ──
        db_chapter = db.query(DBChapter).filter(
            DBChapter.subject_id == db_subject.id,
            DBChapter.title == chapter_title,
        ).first()
        if not db_chapter:
            db_chapter = DBChapter(
                subject_id=db_subject.id,
                title=chapter_title,
                chapter_number=1,
            )
            db.add(db_chapter)
            db.commit()

        # ── Topics and Content Chunks ──
        for i, section in enumerate(sections):
            # Check if this topic already exists (idempotent upsert)
            db_topic = db.query(DBTopic).filter(
                DBTopic.chapter_id == db_chapter.id,
                DBTopic.title == section.heading,
            ).first()

            if not db_topic:
                db_topic = DBTopic(
                    chapter_id=db_chapter.id,
                    title=section.heading,          # LLM-generated heading
                    topic_number=section.section_number if section.section_number else str(i + 1),
                    summary=section.summary,        # LLM-generated summary
                )
                db.add(db_topic)
                db.commit()
                logger.info(f"  DB: Created topic \"{section.heading}\"")
            else:
                logger.info(f"  DB: Topic already exists, skipping \"{section.heading}\"")

            # Store one ContentChunk per section (the full repaired text).
            # chunk_index=0 since it is a single coherent block per topic.
            existing_chunk = db.query(ContentChunk).filter(
                ContentChunk.topic_id == db_topic.id,
                ContentChunk.chunk_index == 0,
            ).first()

            if not existing_chunk:
                db.add(ContentChunk(
                    topic_id=db_topic.id,
                    content=section.repaired_text,  # LLM-repaired clean content
                    chunk_index=0,
                ))
                logger.info(
                    f"  DB: Stored content chunk for \"{section.heading}\" "
                    f"({len(section.repaired_text)} chars)"
                )

        db.commit()
        logger.info("Successfully saved all sections to PostgreSQL!")

    except Exception as e:
        logger.error(f"Database error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Query / Retrieval
# ─────────────────────────────────────────────────────────────────────────────

def query_system(question: str):
    """Routes a question and retrieves relevant context from Qdrant."""
    logger.info(f"\n{'='*60}")
    logger.info(f"QUERY: {question}")
    logger.info(f"{'='*60}")

    # 1. Route — find the most relevant curriculum topic
    router = SemanticRouter()
    route = router.route_query(question)

    if not route:
        logger.warning("Could not confidently route the question.")
        return

    logger.info(
        f"Routed → Class {route['class']}, {route['subject']}, "
        f"{route['chapter']}, {route['topic']}"
    )

    # 2. Retrieve — fetch top-k content chunks from Qdrant
    retrieval_engine = RetrievalEngine()
    chunks = retrieval_engine.retrieve(question, route, top_k=5)
    logger.info(f"Retrieved {len(chunks)} chunks")

    # 3. Compress Context
    reranker = Reranker()
    context = reranker.compress_context(chunks)
    print("\n--- Compressed Context ---")
    print(context)


if __name__ == "__main__":
    logger.info("AI Tutor Curriculum Engine v3.0")
    # ingest_pdf(
    #     pdf_path="DataSet/Class_10/Science/chapter_1.pdf",
    #     class_num=10,
    #     subject="Science",
    #     chapter="Chemical Reactions and Equations"
    # )
    query_system("What is the rancidity")
