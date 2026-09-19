"""
app/services/retrieval_service.py
───────────────────────────────────
Retrieves the most relevant curriculum content from pgvector.

Merges: retrieval/engine.py + retrieval/query.py + retrieval/reranker.py

Pipeline:
  1. Check Redis retrieval cache (30-day TTL for static curriculum content)
  2. Check Redis embedding cache (7-day TTL)
  3. Embed query via Embedder
  4. 3-level cascading pgvector query (topic → chapter → subject)
  5. Confidence gate (default 0.60)
  6. Compress + return context string
"""
import uuid
import logging

from sqlalchemy import func

from app.data.database import managed_session
from app.data.models import CurriculumContent
from app.infra.embedder import Embedder
from app.infra.redis_cache import RetrievalCache
from app.config import settings

logger = logging.getLogger(__name__)

# Module-level singletons (loaded once per process)
_embedder: Embedder | None = None
_cache: RetrievalCache | None = None


def _get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


def _get_cache() -> RetrievalCache:
    global _cache
    if _cache is None:
        _cache = RetrievalCache()
    return _cache


def upsert_chunk(metadata: dict, text: str) -> None:
    """Embeds a curriculum text chunk and upserts it into CurriculumContent."""
    vector = _get_embedder().embed_document(text)
    point_id = str(uuid.uuid4())

    with managed_session() as db:
        existing = db.query(CurriculumContent).filter(
            CurriculumContent.id == point_id
        ).first()

        if existing:
            existing.class_num = metadata.get("class")
            existing.subject   = metadata.get("subject")
            existing.chapter   = metadata.get("chapter")
            existing.topic     = metadata.get("topic")
            existing.content   = text
            existing.vector    = vector
        else:
            db.add(CurriculumContent(
                id=point_id,
                class_num=metadata.get("class"),
                subject=metadata.get("subject"),
                chapter=metadata.get("chapter"),
                topic=metadata.get("topic"),
                content=text,
                vector=vector,
            ))


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

    # ── Cache hit check ────────────────────────────────────────────────────────
    cached_chunks = cache.get_chunks(question, class_num, subject)
    if cached_chunks:
        logger.info("Retrieval cache HIT")
        confident = [c for c in cached_chunks if c.get("score", 0) >= threshold]
        return _compress(confident), confident

    # ── Embed (with embedding cache) ───────────────────────────────────────────
    query_vector = cache.get_embedding(question)
    if query_vector is None:
        query_vector = _get_embedder().embed_query(question)
        cache.set_embedding(question, query_vector)

    # ── 3-level cascade retrieval ─────────────────────────────────────────────
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
    """3-level cascade: topic → chapter → subject scope."""
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
    """Single filtered cosine-similarity query against CurriculumContent."""
    with managed_session() as db:
        try:
            distance = CurriculumContent.vector.cosine_distance(query_vector)
            q = db.query(CurriculumContent, (1 - distance).label("score"))

            if "class_num" in filters and filters["class_num"] is not None:
                q = q.filter(CurriculumContent.class_num == filters["class_num"])
            if "subject" in filters:
                q = q.filter(
                    func.lower(CurriculumContent.subject) == filters["subject"].lower()
                )
            if "chapter" in filters:
                q = q.filter(
                    func.lower(CurriculumContent.chapter) == filters["chapter"].lower()
                )
            if "topic" in filters:
                q = q.filter(
                    func.lower(CurriculumContent.topic) == filters["topic"].lower()
                )

            rows = q.order_by(distance).limit(top_k).all()
            return [
                {
                    "score": float(r.score) if r.score is not None else 0.0,
                    "content": r.CurriculumContent.content,
                    "metadata": {
                        "class":   r.CurriculumContent.class_num,
                        "subject": r.CurriculumContent.subject,
                        "chapter": r.CurriculumContent.chapter,
                        "topic":   r.CurriculumContent.topic,
                    },
                }
                for r in rows
            ]
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
