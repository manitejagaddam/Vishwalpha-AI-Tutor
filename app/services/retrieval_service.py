"""
app/services/retrieval_service.py
─────────────────────────────────
Handles pgvector cosine similarity search against ContentBlock / BlockEmbedding.
Caches queries to Redis (via Upstash) to save LLM/embedding cost on repeated questions.
"""
import json
import logging
from typing import Any
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.infra.azure_openai_client import get_openai
from app.infra.redis_cache import RetrievalCache
from app.data.database import managed_session
from app.data.models.content import (
    ContentBlock, BlockEmbedding, Topic, Chapter, Book, Subject, SchoolClass, BookIngestionLog
)
from app.config import settings

logger = logging.getLogger(__name__)

def embed_text(text: str) -> list[float]:
    client = get_openai()
    response = client.embeddings.create(
        input=text,
        model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT
    )
    return response.data[0].embedding

_cache = None
def _get_cache() -> RetrievalCache:
    global _cache
    if _cache is None:
        _cache = RetrievalCache()
    return _cache


def retrieve_with_confidence(
    question: str,
    routing_metadata: dict,
    top_k: int = 5,
    confidence_threshold: float | None = None,
) -> tuple[str, list[dict]]:
    """
    Retrieves curriculum chunks and applies a confidence gate.
    Returns (context_string, confident_chunks).
    context_string is empty if no chunks pass the threshold.
    """
    threshold = confidence_threshold or settings.RETRIEVAL_CONFIDENCE_THRESHOLD
    class_num = routing_metadata.get("class")
    subject   = routing_metadata.get("subject")
    board_id  = routing_metadata.get("board_id")

    cache = _get_cache()

    # ── Cache hit check ──
    cached_chunks = cache.get_chunks(question, class_num, subject, board_id=board_id)
    if cached_chunks:
        logger.info("Retrieval cache HIT")
        confident = [c for c in cached_chunks if c.get("score", 0) >= threshold]
        return _compress(confident), confident

    # ── Embed (with embedding cache) ──
    query_vector = cache.get_embedding(question)
    if query_vector is None:
        query_vector = embed_text(question)
        cache.set_embedding(question, query_vector)

    # ── 3-level cascade retrieval ──
    all_chunks = _cascade(query_vector, routing_metadata, top_k)

    # Cache all results (confident + not) for 30 days
    cache.set_chunks(question, class_num, subject, all_chunks, board_id=board_id)

    confident = [c for c in all_chunks if c.get("score", 0) >= threshold]

    if not confident:
        best = max((c.get("score", 0) for c in all_chunks), default=0)
        logger.warning(
            f"No chunks above confidence threshold {threshold}. "
            f"Best score: {best:.3f}"
        )
        return "", []

    logger.info(
        f"Confidence gate: {len(confident)}/{len(all_chunks)} chunks passed "
        f"(threshold={threshold})"
    )

    # ── Ingestion quality gate ──
    # Warn if any returned chunks come from chapters with low-confidence ingestion.
    # This prevents a bad scan from teaching students wrong information.
    bad_ingestion_chapters = [
        c["metadata"].get("chapter", "?") for c in confident
        if c.get("ingestion_status") in ("needs_review", "failed")
    ]
    if bad_ingestion_chapters:
        unique_bad = list(set(bad_ingestion_chapters))
        logger.warning(
            f"[Retrieval] Returning blocks from low-confidence ingestion chapters: {unique_bad}. "
            "Consider re-ingesting these chapters."
        )
        # Attach warning to the context string so the LLM is aware
        warning_note = (
            f"\n⚠️ Note: Content from chapter(s) {unique_bad} may be partially incomplete "
            "due to low-confidence ingestion. Cross-check with textbook if needed.\n"
        )
        return _compress(confident) + warning_note, confident

    return _compress(confident), confident


def _cascade(
    query_vector: list[float],
    routing_metadata: dict,
    top_k: int,
    min_results: int = 3,
) -> list[dict]:
    """3-level cascade: topic -> chapter -> subject scope."""
    filter_levels = [
        {k: v for k, v in {
            "board_id":  routing_metadata.get("board_id"),
            "class_num": routing_metadata.get("class"),
            "subject":   routing_metadata.get("subject"),
            "chapter":   routing_metadata.get("chapter"),
            "topic":     routing_metadata.get("topic"),
        }.items() if v is not None},
        {k: v for k, v in {
            "board_id":  routing_metadata.get("board_id"),
            "class_num": routing_metadata.get("class"),
            "subject":   routing_metadata.get("subject"),
            "chapter":   routing_metadata.get("chapter"),
        }.items() if v is not None},
        {k: v for k, v in {
            "board_id":  routing_metadata.get("board_id"),
            "class_num": routing_metadata.get("class"),
            "subject":   routing_metadata.get("subject"),
        }.items() if v is not None},
    ]

    best: list[dict] = []
    for i, filters in enumerate(filter_levels):
        results = _run_query(query_vector, filters, top_k)
        best = results
        if len(results) >= min_results:
            logger.info(f"Retrieval satisfied at level {i+1} ({len(results)} chunks)")
            return results
        logger.info(f"Level {i+1}: {len(results)} chunks — cascading...")

    return best


def _run_query(
    query_vector: list[float], filters: dict, top_k: int
) -> list[dict]:
    """Single filtered cosine-similarity query against BlockEmbedding."""
    with managed_session() as db:
        try:
            distance = BlockEmbedding.embedding.cosine_distance(query_vector)
            q = db.query(
                ContentBlock,
                (1 - distance).label("score"),
                Topic, Chapter, Book, Subject, SchoolClass,
            ).join(BlockEmbedding, ContentBlock.id == BlockEmbedding.block_id)

            needs_joins = any(k in filters for k in ("subject", "chapter", "class_num", "topic", "board_id"))
            if needs_joins:
                q = q.join(Topic, ContentBlock.topic_id == Topic.id)

            if any(k in filters for k in ("subject", "chapter", "class_num", "board_id")):
                q = q.join(Chapter, Topic.chapter_id == Chapter.id)
                q = q.join(Book, Chapter.book_id == Book.id)
                q = q.join(Subject, Book.subject_id == Subject.id)
                q = q.join(SchoolClass, Subject.class_id == SchoolClass.id)
            else:
                # Always join for metadata enrichment even when no filter applied
                q = (q
                     .join(Topic, ContentBlock.topic_id == Topic.id)
                     .join(Chapter, Topic.chapter_id == Chapter.id)
                     .join(Book, Chapter.book_id == Book.id)
                     .join(Subject, Book.subject_id == Subject.id)
                     .join(SchoolClass, Subject.class_id == SchoolClass.id)
                     )

            if "board_id" in filters and filters["board_id"] is not None:
                q = q.filter(SchoolClass.board_id == int(filters["board_id"]))
            if "class_num" in filters and filters["class_num"] is not None:
                q = q.filter(SchoolClass.level == int(filters["class_num"]))
            if "subject" in filters:
                q = q.filter(func.lower(Subject.name) == str(filters["subject"]).lower())
            if "chapter" in filters:
                q = q.filter(func.lower(Chapter.title) == str(filters["chapter"]).lower())
            if "topic" in filters:
                q = q.filter(func.lower(Topic.title) == str(filters["topic"]).lower())

            rows = q.order_by(distance).limit(top_k).all()
            results = []
            for r in rows:
                block        = r.ContentBlock
                topic_obj    = r.Topic
                chapter_obj  = r.Chapter
                subject_obj  = r.Subject
                cls_obj      = r.SchoolClass

                # Check ingestion quality for this chapter
                ingestion_status = None
                try:
                    latest_log = (
                        db.query(BookIngestionLog.status)
                        .filter(
                            BookIngestionLog.book_id == chapter_obj.book_id,
                            BookIngestionLog.chapter_number == chapter_obj.chapter_number,
                        )
                        .order_by(BookIngestionLog.ingested_at.desc())
                        .first()
                    )
                    if latest_log:
                        ingestion_status = latest_log.status
                except Exception:
                    pass

                results.append({
                    "score": float(r.score) if r.score is not None else 0.0,
                    # raw_text = verbatim textbook text — sent to LLM for answer generation
                    # summary  = LLM-cleaned 1-2 sentences — used for scoring/display only
                    "content": block.raw_text,
                    "summary": block.enriched_summary or "",
                    "ingestion_status": ingestion_status,
                    "metadata": {
                        "class":   cls_obj.level     if cls_obj     else None,
                        "subject": subject_obj.name  if subject_obj else None,
                        "chapter": chapter_obj.title if chapter_obj else None,
                        "topic":   topic_obj.title   if topic_obj   else None,
                        "keywords": block.enriched_keywords or [],
                    },
                })
            return results
        except Exception as exc:
            logger.error(f"Retrieval query error: {exc}")
            return []


def _compress(chunks: list[dict], max_tokens: int = 1500) -> str:
    """
    Reranks by score and builds the context string sent to the tutor LLM.

    TOKEN BUDGET DESIGN:
    - We send enriched_summary (1-2 clean sentences) NOT raw_text.
    - raw_text lives in content_raw_archive for auditing/migration only.
    - This keeps the prompt tight so the master prompt, student cognitive
      profile, and conversation history all fit within the token limit.
    - If a block has no summary yet (e.g. ingested before this pipeline
      version), we fall back to the first 300 chars of raw content.
    """
    sorted_chunks = sorted(chunks, key=lambda x: x["score"], reverse=True)
    parts = []
    token_count = 0

    for i, chunk in enumerate(sorted_chunks):
        # Use the LLM-generated summary — concise and clean for the tutor prompt.
        # Fall back to truncated raw content only when summary is missing.
        content = chunk.get("summary") or chunk["content"][:300]
        tokens = len(content) // 4
        if token_count + tokens > max_tokens:
            break
        meta = chunk["metadata"]
        label = f"[{meta.get('chapter', '?')} — {meta.get('topic', '?')}]"
        parts.append(f"--- Source {i+1} {label} ---\n{content}")
        token_count += tokens

    return "\n\n".join(parts).strip()
