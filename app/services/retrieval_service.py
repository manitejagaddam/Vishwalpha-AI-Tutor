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

from app.infra.azure_openai_client import get_openai
from app.data.database import managed_session
from app.data.models.content import ContentBlock, BlockEmbedding, Topic, Chapter, Book, Subject, SchoolClass
from app.config import settings

logger = logging.getLogger(__name__)

def embed_text(text: str) -> list[float]:
    client = get_openai()
    response = client.embeddings.create(
        input=text,
        model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT
    )
    return response.data[0].embedding
from app.infra.redis_cache import RetrievalCache

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

    cache = _get_cache()

    # ── Cache hit check ──
    cached_chunks = cache.get_chunks(question, class_num, subject)
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
    cache.set_chunks(question, class_num, subject, all_chunks)

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
            "class_num": routing_metadata.get("class"),
            "subject":   routing_metadata.get("subject"),
            "chapter":   routing_metadata.get("chapter"),
            "topic":     routing_metadata.get("topic"),
        }.items() if v is not None},
        {k: v for k, v in {
            "class_num": routing_metadata.get("class"),
            "subject":   routing_metadata.get("subject"),
            "chapter":   routing_metadata.get("chapter"),
        }.items() if v is not None},
        {k: v for k, v in {
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
            q = db.query(ContentBlock, (1 - distance).label("score"))\
                  .join(BlockEmbedding, ContentBlock.id == BlockEmbedding.block_id)

            needs_joins = any(k in filters for k in ("subject", "chapter", "class_num", "topic"))
            if needs_joins:
                q = q.join(Topic, ContentBlock.topic_id == Topic.id)
                
            if any(k in filters for k in ("subject", "chapter", "class_num")):
                q = q.join(Chapter, Topic.chapter_id == Chapter.id)
                q = q.join(Book, Chapter.book_id == Book.id)
                q = q.join(Subject, Book.subject_id == Subject.id)
                q = q.join(SchoolClass, Subject.class_id == SchoolClass.id)

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
                block = r.ContentBlock
                topic = db.query(Topic).filter(Topic.id == block.topic_id).first()
                chapter = db.query(Chapter).filter(Chapter.id == topic.chapter_id).first() if topic else None
                book = db.query(Book).filter(Book.id == chapter.book_id).first() if chapter else None
                subject = db.query(Subject).filter(Subject.id == book.subject_id).first() if book else None
                school_class = db.query(SchoolClass).filter(SchoolClass.id == subject.class_id).first() if subject else None

                results.append({
                    "score": float(r.score) if r.score is not None else 0.0,
                    "content": block.raw_text,
                    "metadata": {
                        "class": school_class.level if school_class else None,
                        "subject": subject.name if subject else None,
                        "chapter": chapter.title if chapter else None,
                        "topic": topic.title if topic else None,
                    },
                })
            return results
        except Exception as exc:
            logger.error(f"Retrieval query error: {exc}")
            return []


def _compress(chunks: list[dict], max_tokens: int = 1500) -> str:
    """Reranks by score and compresses chunks into a single context string."""
    sorted_chunks = sorted(chunks, key=lambda x: x["score"], reverse=True)
    parts = []
    token_count = 0

    for i, chunk in enumerate(sorted_chunks):
        tokens = len(chunk["content"]) // 4
        if token_count + tokens > max_tokens:
            break
        meta = chunk["metadata"]
        label = f"[{meta.get('chapter', '?')} — {meta.get('topic', '?')}]"
        parts.append(f"--- Source {i+1} {label} ---\n{chunk['content']}")
        token_count += tokens

    return "\n\n".join(parts).strip()
