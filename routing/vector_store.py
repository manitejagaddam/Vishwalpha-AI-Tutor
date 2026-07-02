"""
routing/vector_store.py
───────────────────────
PostgreSQL vector store interface for curriculum routing.
"""
import os
import logging
from core.db_session import managed_session
from db.models import CurriculumRouting

logger = logging.getLogger(__name__)

class RoutingVectorStore:
    """
    Manages vector storage and similarity search for curriculum topics in PostgreSQL.
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

    def search_routes(self, query_vector: list[float], limit: int = 3) -> list[dict]:
        """
        Finds the closest topic routes for a given query vector.
        """
        with managed_session() as db:
            try:
                distance = CurriculumRouting.vector.cosine_distance(query_vector)
                results = db.query(
                    CurriculumRouting,
                    (1 - distance).label("score")
                ).order_by(distance).limit(limit).all()
                
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
