"""
retrieval/engine.py
───────────────────
Retrieves and upserts curriculum content from PostgreSQL.

Implements a 3-level cascading fallback strategy:
  Level 1: class + subject + chapter + topic  (most specific, ≥ min_results needed)
  Level 2: class + subject + chapter           (chapter fallback)
  Level 3: class + subject                     (subject fallback, last resort)

Also plugs into the 3-layer Redis cache (Phase 5):
  - Layer 1: embedding cache (7-day TTL)
  - Layer 2: scoped retrieval cache (30-day TTL for static curriculum)
"""
import os
import uuid
import logging
from sqlalchemy import func
from core.db_session import managed_session
from db.models import CurriculumContent
from routing.embedder import Embedder
from retrieval.cache import QueryCache

logger = logging.getLogger(__name__)

class RetrievalEngine:
    """
    Engine for querying and storing curriculum vector embeddings and content.
    """
    def __init__(self, collection_name: str = "curriculum_content"):
        self.collection_name = collection_name
        self.embedder = Embedder()
        self.cache = QueryCache()
        logger.info("Initializing PostgreSQL-based Retrieval Engine")

    def upsert_chunk(self, metadata: dict, text: str):
        """
        Embeds a curriculum chunk and stores it in PostgreSQL with its hierarchical metadata.
        """
        with managed_session() as db:
            try:
                vector = self.embedder.embed_document(text)
                point_id = str(uuid.uuid4())
                
                existing = db.query(CurriculumContent).filter(CurriculumContent.id == point_id).first()
                if existing:
                    existing.class_num = metadata.get("class")
                    existing.subject = metadata.get("subject")
                    existing.chapter = metadata.get("chapter")
                    existing.topic = metadata.get("topic")
                    existing.content = text
                    existing.vector = vector
                else:
                    chunk = CurriculumContent(
                        id=point_id,
                        class_num=metadata.get("class"),
                        subject=metadata.get("subject"),
                        chapter=metadata.get("chapter"),
                        topic=metadata.get("topic"),
                        content=text,
                        vector=vector
                    )
                    db.add(chunk)
                db.commit()
                logger.info(f"Upserted curriculum chunk for point_id: {point_id}")
            except Exception as e:
                logger.error(f"Error in upsert_chunk: {e}")
                raise e

    def retrieve(
        self,
        query: str,
        routing_metadata: dict,
        top_k: int = 5,
        min_results: int = 3,
    ) -> list[dict]:
        """
        Retrieves the most relevant chunks using a 3-level cascading fallback:
          Level 1: class + subject + chapter + topic (most specific)
          Level 2: class + subject + chapter
          Level 3: class + subject (broadest scoped fallback)

        Checks the scoped Redis retrieval cache first (30-day TTL).
        Falls back gracefully to direct DB queries if Redis is unavailable.
        """
        class_num = routing_metadata.get("class")
        subject   = routing_metadata.get("subject")

        # Check Phase 5 scoped retrieval cache
        cached = self.cache.get_chunks(query, class_num, subject)
        if cached:
            logger.info("Retrieval cache HIT — skipping embed + DB cascade")
            return cached

        # Check/populate embedding cache (Phase 5 Layer 1)
        query_vector = self.cache.get_embedding(query)
        if query_vector is None:
            query_vector = self.embedder.embed_query(query)
            self.cache.set_embedding(query, query_vector)

        results = self._cascade_retrieve(query_vector, routing_metadata, top_k, min_results)

        # Cache results for 30 days (curriculum is static)
        self.cache.set_chunks(query, class_num, subject, results)
        return results

    def _cascade_retrieve(
        self,
        query_vector: list[float],
        routing_metadata: dict,
        top_k: int,
        min_results: int,
    ) -> list[dict]:
        """
        Cascades through 3 filter levels until min_results chunks are found.
        Uses func.lower() on string fields to prevent case mismatch zero-results.
        """
        filter_levels = [
            {
                "class_num": routing_metadata.get("class"),
                "subject":   routing_metadata.get("subject"),
                "chapter":   routing_metadata.get("chapter"),
                "topic":     routing_metadata.get("topic"),
            },
            {
                "class_num": routing_metadata.get("class"),
                "subject":   routing_metadata.get("subject"),
                "chapter":   routing_metadata.get("chapter"),
            },
            {
                "class_num": routing_metadata.get("class"),
                "subject":   routing_metadata.get("subject"),
            },
        ]

        last_results: list[dict] = []
        for idx, filters in enumerate(filter_levels):
            results = self._run_filtered_query(query_vector, filters, top_k)
            last_results = results
            if len(results) >= min_results:
                logger.info(f"Retrieval satisfied at level {idx + 1} with {len(results)} chunks.")
                return results
            logger.info(f"Level {idx + 1} returned {len(results)} chunks — cascading...")

        return last_results  # best-effort on deepest level

    def _run_filtered_query(
        self,
        query_vector: list[float],
        filters: dict,
        top_k: int,
    ) -> list[dict]:
        """
        Runs a single filtered cosine-similarity query against CurriculumContent.
        Uses func.lower() on subject/chapter/topic for case-insensitive matching.
        """
        with managed_session() as db:
            try:
                distance = CurriculumContent.vector.cosine_distance(query_vector)
                query_obj = db.query(
                    CurriculumContent,
                    (1 - distance).label("score")
                )

                class_val = filters.get("class_num")
                if class_val is not None:
                    query_obj = query_obj.filter(CurriculumContent.class_num == class_val)

                subject_val = filters.get("subject")
                if subject_val is not None:
                    query_obj = query_obj.filter(
                        func.lower(CurriculumContent.subject) == subject_val.lower()
                    )

                chapter_val = filters.get("chapter")
                if chapter_val is not None:
                    query_obj = query_obj.filter(
                        func.lower(CurriculumContent.chapter) == chapter_val.lower()
                    )

                topic_val = filters.get("topic")
                if topic_val is not None:
                    query_obj = query_obj.filter(
                        func.lower(CurriculumContent.topic) == topic_val.lower()
                    )

                results = query_obj.order_by(distance).limit(top_k).all()

                context = []
                for r in results:
                    score = float(r.score) if r.score is not None else 0.0
                    context.append({
                        "score": score,
                        "content": r.CurriculumContent.content,
                        "metadata": {
                            "class":   r.CurriculumContent.class_num,
                            "subject": r.CurriculumContent.subject,
                            "chapter": r.CurriculumContent.chapter,
                            "topic":   r.CurriculumContent.topic,
                        }
                    })
                return context
            except Exception as e:
                logger.error(f"Error in _run_filtered_query: {e}")
                return []
