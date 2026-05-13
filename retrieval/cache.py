import os
import redis
import json

class QueryCache:
    def __init__(self):
        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            self.redis_client = redis.Redis.from_url(redis_url)
        else:
            print("WARNING: Redis URL not found. Caching disabled.")
            self.redis_client = None

    def get(self, query: str) -> list[dict] | None:
        """
        Retrieves cached retrieval context for a query.
        """
        if not self.redis_client:
            return None
            
        try:
            cached = self.redis_client.get(f"query_cache:{query}")
            if cached:
                return json.loads(cached)
        except Exception as e:
            print(f"Redis get error: {e}")
            
        return None

    def set(self, query: str, context: list[dict], ttl_seconds: int = 3600):
        """
        Caches retrieval context for a query.
        """
        if not self.redis_client:
            return
            
        try:
            self.redis_client.setex(
                f"query_cache:{query}", 
                ttl_seconds, 
                json.dumps(context)
            )
        except Exception as e:
            print(f"Redis set error: {e}")
