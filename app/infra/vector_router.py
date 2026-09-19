
"""
app/infra/vector_router.py
───────────────────────────
Semantic router: maps a student question to the most relevant curriculum
chapter/topic using pgvector cosine similarity on topic summaries.

Replaces: routing/router.py + routing/vector_store.py (Qdrant removed entirely).
100% pgvector — no external vector DB needed.
"""
import uuid
import logging

from sqlalchemy import func

from app.data.database import managed_session
from app.data.models import CurriculumRouting
from app.infra.embedder import Embedder

logger = logging.getLogger(__name__)

_embedder: Embedder | None = None


def _get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


class VectorRouter:
    """
    Pure pgvector semantic router.
    Embeds the student query and finds the closest topic in curriculum_routing.
    Supports class_num + subject pre-filters to prevent cross-class leakage.
    """

    def upsert_topic(
        self,
        class_num: int,
        subject: str,
        chapter: str,
        topic: str,
        summary: str,
    ) -> None:
        """Embeds a topic summary and upserts it into curriculum_routing."""
        vector = _get_embedder().embed_document(summary)
        point_id = str(uuid.uuid5(
            uuid.NAMESPACE_DNS,
            f"class_{class_num}_sub_{subject}_chap_{chapter}_top_{topic}",
        ))

        with managed_session() as db:
            existing = db.query(CurriculumRouting).filter(
                CurriculumRouting.id == point_id
            ).first()

            if existing:
                existing.class_num = class_num
                existing.subject = subject
                existing.chapter = chapter
                existing.topic = topic
                existing.vector = vector
            else:
                db.add(CurriculumRouting(
                    id=point_id,
                    class_num=class_num,
                    subject=subject,
                    chapter=chapter,
                    topic=topic,
                    vector=vector,
                ))
            logger.debug(f"Upserted routing vector: {chapter} / {topic}")

    def route_query(
        self,
        query: str,
        class_num: int | None = None,
        subject: str | None = None,
    ) -> dict | None:
        """
        Embeds the query and returns the best-matching curriculum topic metadata,
        or None if no routing result is found.

        Pre-filters by class_num and subject BEFORE cosine sort to prevent
        cross-class content leakage. Falls back to global search if scoped
        search returns nothing.
        """
        query_vector = _get_embedder().embed_query(query)

        with managed_session() as db:
            distance = CurriculumRouting.vector.cosine_distance(query_vector)
            q = db.query(CurriculumRouting, (1 - distance).label("score"))

            if class_num is not None:
                q = q.filter(CurriculumRouting.class_num == class_num)
            if subject is not None:
                q = q.filter(
                    func.lower(CurriculumRouting.subject) == subject.lower()
                )

            results = q.order_by(distance).limit(1).all()

            # Fallback: scoped search empty → try global
            if not results and (class_num is not None or subject is not None):
                logger.warning(
                    f"Scoped routing found nothing for class={class_num}, "
                    f"subject={subject}. Falling back to global search."
                )
                results = (
                    db.query(CurriculumRouting, (1 - distance).label("score"))
                    .order_by(distance)
                    .limit(1)
                    .all()
                )

            if not results:
                return None

            row = results[0]
            route = {
                "class":   row.CurriculumRouting.class_num,
                "subject": row.CurriculumRouting.subject,
                "chapter": row.CurriculumRouting.chapter,
                "topic":   row.CurriculumRouting.topic,
                "score":   float(row.score) if row.score else 0.0,
            }
            logger.info(
                f"Routed → Class {route['class']} | {route['subject']} | "
                f"{route['chapter']} | {route['topic']} (score={route['score']:.3f})"
            )
            return route
