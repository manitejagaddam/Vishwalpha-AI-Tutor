"""
routing/vector_store.py
───────────────────────
PostgreSQL vector store interface for curriculum routing.
"""
import logging
from sqlalchemy import func
from core.db_session import managed_session
from db.models import CurriculumRouting

logger = logging.getLogger(__name__)

class RoutingVectorStore:
    """
    Manages vector storage and similarity search for curriculum topics in PostgreSQL.
    Supports scoped pre-filters (class_num, subject) applied BEFORE cosine sort
    so a Class 7 student never gets Class 12 results.
    """
    def __init__(self, collection_name: str = "curriculum_routing"):
        self.collection_name = collection_name
        logger.info("Initializing PostgreSQL-based Routing Vector Store")

    def upsert_route(self, point_id: str, vector: list[float], payload: dict):
        """
        Upserts a routing vector.
        Payload should contain: class, subject, chapter, topic.
        """
        with managed_session() as db:
            try:
                existing = db.query(CurriculumRouting).filter(CurriculumRouting.id == point_id).first()
                if existing:
                    existing.class_num = payload.get("class")
                    existing.subject = payload.get("subject")
                    existing.chapter = payload.get("chapter")
                    existing.topic = payload.get("topic")
                    existing.vector = vector
                else:
                    route = CurriculumRouting(
                        id=point_id,
                        class_num=payload.get("class"),
                        subject=payload.get("subject"),
                        chapter=payload.get("chapter"),
                        topic=payload.get("topic"),
                        vector=vector
                    )
                    db.add(route)
                db.commit()
                logger.info(f"Upserted routing vector for point_id: {point_id}")
            except Exception as e:
                logger.error(f"Error in upsert_route: {e}")
                raise e

    def search_routes(
        self,
        query_vector: list[float],
        limit: int = 3,
        class_num: int | None = None,   # NEW: pre-filter before cosine sort
        subject: str | None = None,     # NEW: pre-filter before cosine sort
    ) -> list[dict]:
        """
        Finds the closest topic routes for a given query vector.
        Applies class_num and subject filters BEFORE ordering by cosine distance
        to prevent cross-class content leakage.

        Edge case: if scoped search returns nothing, falls back to global unscoped search.
        """
        with managed_session() as db:
            try:
                distance = CurriculumRouting.vector.cosine_distance(query_vector)
                query_obj = db.query(
                    CurriculumRouting,
                    (1 - distance).label("score")
                )

                # Apply pre-filters BEFORE cosine sort
                if class_num is not None:
                    query_obj = query_obj.filter(CurriculumRouting.class_num == class_num)
                if subject is not None:
                    query_obj = query_obj.filter(
                        func.lower(CurriculumRouting.subject) == subject.lower()
                    )

                results = query_obj.order_by(distance).limit(limit).all()

                # Edge case: scoped search returned nothing — fallback to global
                if not results and (class_num is not None or subject is not None):
                    logger.warning(
                        f"Scoped search empty for class={class_num}, subject={subject}. "
                        "Falling back to global unscoped search."
                    )
                    query_obj = db.query(
                        CurriculumRouting,
                        (1 - distance).label("score")
                    )
                    results = query_obj.order_by(distance).limit(limit).all()

                mapped_results = []
                for r in results:
                    score = float(r.score) if r.score is not None else 0.0
                    mapped_results.append({
                        "id": r.CurriculumRouting.id,
                        "score": score,
                        "payload": {
                            "class": r.CurriculumRouting.class_num,
                            "subject": r.CurriculumRouting.subject,
                            "chapter": r.CurriculumRouting.chapter,
                            "topic": r.CurriculumRouting.topic,
                        }
                    })
                return mapped_results
            except Exception as e:
                logger.error(f"Error in search_routes: {e}")
                return []
