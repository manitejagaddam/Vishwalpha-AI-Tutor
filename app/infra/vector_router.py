"""
app/infra/vector_router.py
─────────────────────────────────
Semantic router: maps a student question to the most relevant curriculum
chapter/topic using pgvector cosine similarity on Content Blocks.

Replaces: routing/router.py + routing/vector_store.py
"""
import logging
from sqlalchemy import func

from app.config import settings
from app.infra.azure_openai_client import get_openai
from app.data.database import managed_session
from app.data.models.content import ContentBlock, BlockEmbedding, Topic, Chapter, Book, Subject, SchoolClass
from app.services.retrieval_service import embed_text  # shared, avoid duplication

logger = logging.getLogger(__name__)


class VectorRouter:
    """
    Pure pgvector semantic router.
    Embeds the student query and finds the closest topic via BlockEmbedding.
    Supports class_num + subject pre-filters to prevent cross-class leakage.
    """
    def route_query(
        self,
        query: str,
        class_num: int | None = None,
        subject_id: int | None = None,
        board_id: int | None = None,
    ) -> dict | None:
        """
        Embeds the query and returns the best-matching curriculum topic metadata,
        or None if no routing result is found.

        Pre-filters by board_id, class_num and subject_id BEFORE cosine sort.
        """
        from app.infra.redis_cache import RetrievalCache as _RC
        _cache = _RC()
        query_vector = _cache.get_embedding(query)
        if query_vector is None:
            query_vector = embed_text(query)
            _cache.set_embedding(query, query_vector)

        with managed_session() as db:
            distance = BlockEmbedding.embedding.cosine_distance(query_vector)
            q = db.query(ContentBlock, (1 - distance).label("score"))\
                  .join(BlockEmbedding, ContentBlock.id == BlockEmbedding.block_id)\
                  .join(Topic, ContentBlock.topic_id == Topic.id)\
                  .join(Chapter, Topic.chapter_id == Chapter.id)\
                  .join(Book, Chapter.book_id == Book.id)\
                  .join(Subject, Book.subject_id == Subject.id)\
                  .join(SchoolClass, Subject.class_id == SchoolClass.id)

            if board_id is not None:
                q = q.filter(SchoolClass.board_id == int(board_id))
            if class_num is not None:
                q = q.filter(SchoolClass.level == int(class_num))
            if subject_id is not None:
                q = q.filter(Subject.id == subject_id)

            results = q.order_by(distance).limit(1).all()

            # Fallback: scoped search empty -> try global
            if not results and (class_num is not None or subject_id is not None or board_id is not None):
                logger.warning(
                    f"Scoped routing found nothing for board={board_id}, class={class_num}, "
                    f"subject_id={subject_id}. Falling back to global search."
                )
                results = (
                    db.query(ContentBlock, (1 - distance).label("score"))
                    .join(BlockEmbedding, ContentBlock.id == BlockEmbedding.block_id)
                    .order_by(distance)
                    .limit(1)
                    .all()
                )

            if not results:
                return None

            # Single joined query to pull the full hierarchy — avoids 5 separate N+1 fetches
            from sqlalchemy import func as _func
            row = results[0]
            block = row.ContentBlock

            hierarchy = (
                db.query(Topic, Chapter, Book, Subject, SchoolClass)
                .join(Chapter, Topic.chapter_id == Chapter.id)
                .join(Book, Chapter.book_id == Book.id)
                .join(Subject, Book.subject_id == Subject.id)
                .join(SchoolClass, Subject.class_id == SchoolClass.id)
                .filter(Topic.id == block.topic_id)
                .first()
            )
            if not hierarchy:
                return None

            topic_obj, chapter_obj, _, subject_obj, school_class_obj = hierarchy

            route = {
                "board_id": school_class_obj.board_id if school_class_obj else board_id,
                "class":   school_class_obj.level    if school_class_obj else class_num,
                "subject": subject_obj.name,
                "chapter": chapter_obj.title,
                "topic":   topic_obj.title,
                "score":   float(row.score) if row.score else 0.0,
            }
            logger.info(
                f"Routed -> Board {route['board_id']} | Class {route['class']} | {route['subject']} | "
                f"{route['chapter']} | {route['topic']} (score={route['score']:.3f})"
            )
            return route
