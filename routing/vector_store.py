import os
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct

class RoutingVectorStore:
    def __init__(self, collection_name: str = "curriculum_routing"):
        self.collection_name = collection_name
        
        qdrant_url = os.environ.get("QDRANT_URL")
        qdrant_api_key = os.environ.get("QDRANT_API_KEY")
        
        if qdrant_url and qdrant_api_key:
            self.client = QdrantClient(
                url=qdrant_url,
                api_key=qdrant_api_key,
            )
        else:
            print("WARNING: Using in-memory Qdrant client because URL/API key missing.")
            self.client = QdrantClient(":memory:")
            
        self._ensure_collection()

    def _ensure_collection(self):
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                # BGE-small embedding dimension is 384
                vectors_config=VectorParams(size=384, distance=Distance.COSINE), 
            )

    def upsert_route(self, point_id: str, vector: list[float], payload: dict):
        """
        Upserts a routing vector.
        payload should contain: { "class": 7, "subject": "Science", "chapter": "Nutrition in Plants", "topic": "Photosynthesis" }
        """
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload
                )
            ]
        )

    def search_routes(self, query_vector: list[float], limit: int = 3) -> list[dict]:
        """
        Finds the closest topic routes for a given query vector.
        """
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=limit
        )
        results = response.points
        return [{"id": r.id, "score": r.score, "payload": r.payload} for r in results]
