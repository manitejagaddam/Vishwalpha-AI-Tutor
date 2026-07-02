"""
routing/router.py
─────────────────
Semantic routing logic for mapping queries to curriculum topics.
"""
import uuid
from routing.embedder import Embedder
from routing.vector_store import RoutingVectorStore

class SemanticRouter:
    """
    Handles routing user queries to the most relevant curriculum topic.
    """
    def __init__(self):
        self.embedder = Embedder()
        self.vector_store = RoutingVectorStore()

    def add_route(self, class_num: int, subject: str, chapter: str, topic: str, summary: str):
        """
        Embeds a topic summary and adds it to the routing vector store.
        """
        vector = self.embedder.embed_document(summary)
        
        unique_string = f"class_{class_num}_sub_{subject}_chap_{chapter}_top_{topic}"
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, unique_string))
        
        payload = {
            "class": class_num,
            "subject": subject,
            "chapter": chapter,
            "topic": topic
        }
        
        self.vector_store.upsert_route(point_id, vector, payload)

    def route_query(self, query: str) -> dict | None:
        """
        Takes a student query, embeds it, and finds the most relevant curriculum topic.
        Returns the metadata dictionary or None if no match is confident enough.
        """
        query_vector = self.embedder.embed_query(query)
        results = self.vector_store.search_routes(query_vector, limit=1)
        
        if results and results[0]["score"] > 0.4: 
            return results[0]["payload"]
            
        return None
