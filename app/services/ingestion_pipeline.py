"""
app/services/ingestion_pipeline.py
───────────────────────────────────
PDF → PostgreSQL ingestion pipeline for Phase 2 schema.

Hierarchy written to DB:
  Board → SchoolClass → Subject → Book → Chapter → Topic → ContentBlock → BlockEmbedding

Usage (CLI):
  python -m scripts.ingest path/to/book.pdf \\
      --board NCERT --class 10 --subject Science \\
      --book-title "NCERT Science Class 10" \\
      --book-key "NCERT_10_Science_en_2023" \\
      --chapter "Light — Reflection and Refraction" --chapter-num 10

Usage (programmatic):
  from app.services.ingestion_pipeline import IngestionPipeline
  pipeline = IngestionPipeline()
  result = pipeline.process_pdf(
      pdf_path="path/to/file.pdf",
      board_name="NCERT",
      class_num=10,
      subject_name="Science",
      book_title="NCERT Science Class 10",
      book_natural_key="NCERT_10_Science_en_2023",
      chapter_title="Light — Reflection and Refraction",
      chapter_number=10,
  )
"""
import os
import json
import logging
import uuid
from PyPDF2 import PdfReader

from sqlalchemy.orm import Session

from app.infra.azure_openai_client import get_openai
from app.config import settings
from app.data.database import managed_session
from app.data.models.content import (
    Board, SchoolClass, Subject, Book, Chapter, Topic,
    ContentBlock, BlockEmbedding,
)

logger = logging.getLogger(__name__)


def _embed(text: str) -> list[float]:
    client = get_openai()
    resp = client.embeddings.create(
        input=text[:8000],   # safe limit for text-embedding-3-small
        model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    )
    return resp.data[0].embedding


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_or_create_board(db: Session, name: str) -> Board:
    obj = db.query(Board).filter(Board.name == name).first()
    if not obj:
        obj = Board(name=name)
        db.add(obj)
        db.flush()
    return obj


def _get_or_create_class(db: Session, board_id: int, level: int) -> SchoolClass:
    obj = db.query(SchoolClass).filter(
        SchoolClass.board_id == board_id,
        SchoolClass.level == level,
    ).first()
    if not obj:
        obj = SchoolClass(board_id=board_id, level=level, display_name=f"Class {level}")
        db.add(obj)
        db.flush()
    return obj


def _get_or_create_subject(db: Session, class_id: int, name: str) -> Subject:
    obj = db.query(Subject).filter(
        Subject.class_id == class_id,
        Subject.name == name,
    ).first()
    if not obj:
        obj = Subject(class_id=class_id, name=name, display_name=name)
        db.add(obj)
        db.flush()
    return obj


def _get_or_create_book(
    db: Session, subject_id: int, title: str, natural_key: str
) -> Book:
    obj = db.query(Book).filter(Book.natural_key == natural_key).first()
    if not obj:
        obj = Book(
            subject_id=subject_id,
            title=title,
            natural_key=natural_key,
        )
        db.add(obj)
        db.flush()
    return obj


def _get_or_create_chapter(
    db: Session, book_id: int, title: str, chapter_number: int, natural_key: str
) -> Chapter:
    obj = db.query(Chapter).filter(Chapter.natural_key == natural_key).first()
    if not obj:
        obj = Chapter(
            book_id=book_id,
            title=title,
            chapter_number=chapter_number,
            natural_key=natural_key,
        )
        db.add(obj)
        db.flush()
    return obj


def _upsert_topic(db: Session, chapter_id: int, title: str, order: int) -> Topic:
    slug = title.lower().replace(" ", "_")[:80]
    natural_key = f"ch{chapter_id}_{slug}"
    obj = db.query(Topic).filter(Topic.natural_key == natural_key).first()
    if not obj:
        obj = Topic(
            chapter_id=chapter_id,
            title=title,
            display_order=order,
            natural_key=natural_key,
        )
        db.add(obj)
        db.flush()
    else:
        obj.display_order = order
    return obj


def _upsert_block_and_embedding(
    db: Session, topic_id: int, raw_text: str, block_index: int
) -> None:
    """Upserts a ContentBlock and its embedding. Replaces existing block at same index."""
    block = db.query(ContentBlock).filter(
        ContentBlock.topic_id == topic_id,
        ContentBlock.block_index == block_index,
    ).first()
    if not block:
        block = ContentBlock(
            topic_id=topic_id,
            block_type="text",
            raw_text=raw_text,
            block_index=block_index,
        )
        db.add(block)
        db.flush()
    else:
        block.raw_text = raw_text

    # Upsert embedding
    vector = _embed(raw_text)
    emb = db.query(BlockEmbedding).filter(
        BlockEmbedding.block_id == block.id,
        BlockEmbedding.embedding_model == settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    ).first()
    if emb:
        emb.embedding = vector
    else:
        db.add(BlockEmbedding(
            block_id=block.id,
            embedding=vector,
            embedding_model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
        ))


# ── Main Pipeline ─────────────────────────────────────────────────────────────

class IngestionPipeline:
    def __init__(self):
        self.llm = get_openai()

    def process_pdf(
        self,
        pdf_path: str,
        board_name: str,
        class_num: int,
        subject_name: str,
        book_title: str,
        book_natural_key: str,
        chapter_title: str,
        chapter_number: int,
    ) -> dict:
        """
        Full ingestion: PDF → structured sections → DB rows + embeddings.

        Returns: {status, sections_ingested, chapter_id}
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        logger.info(f"[Ingestion] Starting: {pdf_path}")
        raw_text = self._extract_text(pdf_path)
        logger.info(f"[Ingestion] Extracted {len(raw_text)} chars")

        # Chunk text into ~4000 char blocks for LLM structuring
        raw_chunks = [raw_text[i: i + 4000] for i in range(0, len(raw_text), 4000)]

        all_sections: list[dict] = []
        for i, chunk in enumerate(raw_chunks):
            logger.info(f"[Ingestion] Structuring chunk {i + 1}/{len(raw_chunks)}...")
            structured = self._structure_chunk(chunk, chapter_title)
            if structured:
                all_sections.extend(structured.get("sections", []))

        if not all_sections:
            logger.warning("[Ingestion] No sections extracted from PDF.")
            return {"status": "empty", "sections_ingested": 0}

        # Write to DB in one transaction
        chapter_id_result = None
        total_blocks = 0

        with managed_session() as db:
            board    = _get_or_create_board(db, board_name)
            sc       = _get_or_create_class(db, board.id, class_num)
            subject  = _get_or_create_subject(db, sc.id, subject_name)
            book     = _get_or_create_book(db, subject.id, book_title, book_natural_key)
            chapter_nk = f"{book_natural_key}_C{chapter_number:02d}"
            chapter  = _get_or_create_chapter(
                db, book.id, chapter_title, chapter_number, chapter_nk
            )
            chapter_id_result = chapter.id

            block_counter = 0
            for order, section in enumerate(all_sections):
                heading      = section.get("heading", "General")
                repaired     = section.get("repaired_text", "").strip()
                if not repaired:
                    continue

                topic = _upsert_topic(db, chapter.id, heading, order)

                # Split repaired text into smaller blocks (~800 chars each)
                sub_chunks = [repaired[j: j + 800] for j in range(0, len(repaired), 800)]
                for sub_chunk in sub_chunks:
                    if sub_chunk.strip():
                        _upsert_block_and_embedding(db, topic.id, sub_chunk, block_counter)
                        block_counter += 1
                        total_blocks += 1

        logger.info(f"[Ingestion] Done — {total_blocks} blocks stored for chapter '{chapter_title}'")
        return {
            "status": "success",
            "sections_ingested": len(all_sections),
            "blocks_stored": total_blocks,
            "chapter_id": chapter_id_result,
        }

    def _extract_text(self, pdf_path: str) -> str:
        reader = PdfReader(pdf_path)
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages)

    def _structure_chunk(self, text: str, chapter: str) -> dict | None:
        """
        Asks the LLM to clean OCR errors, split into topics, and return structured JSON.
        """
        prompt = f"""You are a textbook ingestion pipeline.
I will give you raw text extracted from a PDF chapter: '{chapter}'.
Fix OCR errors, split into logical topics (sections), and clean the text.

Output EXACTLY a JSON object:
{{
  "sections": [
    {{
      "heading": "Topic title string",
      "repaired_text": "Clean full text of this section"
    }}
  ]
}}

Raw text:
{text}"""
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
