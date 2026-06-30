import os
import uuid
import logging
from db.database import SessionLocal
from db.models import CurriculumContent
from routing.embedder import Embedder
from retrieval.cache import QueryCache

logger = logging.getLogger(__name__)

class RetrievalEngine:
    def __init__(self, collection_name: str = "curriculum_content"):
        self.collection_name = collection_name
        self.embedder = Embedder()
        self.cache = QueryCache()
        logger.info("Initializing PostgreSQL-based Retrieval Engine")

    def upsert_chunk(self, metadata: dict, text: str):
        """
        Embeds a curriculum chunk and stores it in PostgreSQL with its hierarchical metadata.
        """
        db = SessionLocal()
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
            db.rollback()
            logger.error(f"Error in upsert_chunk: {e}")
            raise e
        finally:
            db.close()

    def retrieve(self, query: str, routing_metadata: dict, top_k: int = 5) -> list[dict]:
        """
        Retrieves the most relevant chunks for a given query, STRICTLY filtered
        by the provided routing metadata (class, subject, chapter, topic).
        """
        # 1. Check cache
        cached_results = self.cache.get(query)
        if cached_results:
            return cached_results
            
        # 2. Embed query
        query_vector = self.embedder.embed_query(query)
        
        # 3. Search database
        db = SessionLocal()
        try:
            distance = CurriculumContent.vector.cosine_distance(query_vector)
            query_obj = db.query(
                CurriculumContent,
                (1 - distance).label("score")
            )
            
            # Apply filters based on routing metadata
            class_val = routing_metadata.get("class")
            if class_val is not None:
                query_obj = query_obj.filter(CurriculumContent.class_num == class_val)
                
            subject_val = routing_metadata.get("subject")
            if subject_val is not None:
                query_obj = query_obj.filter(CurriculumContent.subject == subject_val)
                
            chapter_val = routing_metadata.get("chapter")
            if chapter_val is not None:
                query_obj = query_obj.filter(CurriculumContent.chapter == chapter_val)
                
            topic_val = routing_metadata.get("topic")
            if topic_val is not None:
                query_obj = query_obj.filter(CurriculumContent.topic == topic_val)
                
            results = query_obj.order_by(distance).limit(top_k).all()
            
            context = []
            for r in results:
                score = float(r.score) if r.score is not None else 0.0
                context.append({
                    "score": score,
                    "content": r.CurriculumContent.content,
                    "metadata": {
                        "class": r.CurriculumContent.class_num,
                        "subject": r.CurriculumContent.subject,
                        "chapter": r.CurriculumContent.chapter,
                        "topic": r.CurriculumContent.topic,
                    }
                })
                
            # 4. Cache and return
            self.cache.set(query, context)
            return context
        except Exception as e:
            logger.error(f"Error in retrieve: {e}")
            return []
        finally:
            db.close()
