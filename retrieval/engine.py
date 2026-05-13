import os
import uuid
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
from routing.embedder import Embedder
from retrieval.cache import QueryCache

class RetrievalEngine:
    def __init__(self, collection_name: str = "curriculum_content"):
        self.collection_name = collection_name
        self.embedder = Embedder()
        self.cache = QueryCache()
        
        qdrant_url = os.environ.get("QDRANT_URL")
        qdrant_api_key = os.environ.get("QDRANT_API_KEY")
        
        if qdrant_url and qdrant_api_key:
            self.client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        else:
            self.client = QdrantClient(":memory:")
            
        self._ensure_collection()

    def _ensure_collection(self):
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=384, distance=Distance.COSINE),
            )
            # Create payload indices for fast metadata filtering
            from qdrant_client.http.models import PayloadSchemaType
            self.client.create_payload_index(self.collection_name, "class", field_schema=PayloadSchemaType.INTEGER, wait=True)
            self.client.create_payload_index(self.collection_name, "subject", field_schema=PayloadSchemaType.KEYWORD, wait=True)
            self.client.create_payload_index(self.collection_name, "chapter", field_schema=PayloadSchemaType.KEYWORD, wait=True)
            self.client.create_payload_index(self.collection_name, "topic", field_schema=PayloadSchemaType.KEYWORD, wait=True)

    def upsert_chunk(self, metadata: dict, text: str):
        """
        Embeds a curriculum chunk and stores it in Qdrant with its hierarchical metadata.
        """
        vector = self.embedder.embed_document(text)
        point_id = str(uuid.uuid4())
        
        payload = metadata.copy()
        payload["content"] = text
        
        self.client.upsert(
            collection_name=self.collection_name,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)]
        )

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
        
        # 3. Build strict metadata filters based on routing layer output
        must_conditions = []
        for key in ["class", "subject", "chapter", "topic"]:
            if key in routing_metadata and routing_metadata[key] is not None:
                must_conditions.append(
                    FieldCondition(
                        key=key, 
                        match=MatchValue(value=routing_metadata[key])
                    )
                )
                
        query_filter = Filter(must=must_conditions) if must_conditions else None
        
        # 4. Search
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=query_filter,
            limit=top_k
        )
        results = response.points
        
        context = []
        for r in results:
            context.append({
                "score": r.score, 
                "content": r.payload["content"], 
                "metadata": {k:v for k,v in r.payload.items() if k != "content"}
            })
            
        # 5. Cache and return
        self.cache.set(query, context)
        return context
