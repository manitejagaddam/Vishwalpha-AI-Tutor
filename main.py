"""
main.py
───────
Entry point for the AI Tutor Curriculum Engine.

Module layout:
  schemas.py              — Pydantic models (ProcessedSection, CanonicalCurriculum)
  ingestion/
    parser.py             — PDF parsing with font/layout metadata
    structurer.py         — Deterministic section boundary detection
    cleaner.py            — Text noise removal (footers, OCR artifacts)
    llm_repair.py         — LLM repair: heading + cleaned text + summary per section
    pipeline.py           — Orchestrates the full ingestion flow
  db/
    models.py             — SQLAlchemy ORM models
    database.py           — DB engine and session factory
    writer.py             — PostgreSQL persistence (Board→Class→Subject→Chapter→Topic→Chunk)
  routing/
    embedder.py           — Sentence embedding (BGE-small)
    vector_store.py       — Qdrant curriculum_routing collection
    router.py             — Semantic routing: query → curriculum topic
  retrieval/
    engine.py             — Qdrant curriculum_content collection + retrieval
    reranker.py           — Context compression / reranking
    cache.py              — Redis query cache
    query.py              — Student query flow (route → retrieve → compress)
"""

import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from db.database import init_db
from ingestion.pipeline import ingest_pdf
from retrieval.query import query_system

# Ensure all PostgreSQL tables exist before anything runs
init_db()


if __name__ == "__main__":
    logger.info("AI Tutor Curriculum Engine v3.0")

    # ── Ingest a chapter ───────────────────────────────────────────────────────
    ingest_pdf(
        pdf_path="DataSet/Class_10/Science/chapter_1.pdf",
        class_num=10,
        subject="Science",
        chapter="Chemical Reactions and Equations",
    )

    # # ── Query the system ───────────────────────────────────────────────────────
    context = query_system("What is rancidity?")
    if context:
        print("\n--- Compressed Context ---")
        print(context)
