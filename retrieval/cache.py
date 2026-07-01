import os
import redis
import json

class QueryCache:
    def __init__(self):
        redis_url = os.environ.get("REDIS_URL")
        try:
            if redis_url:
                self.redis_client = redis.Redis.from_url(redis_url, socket_timeout=2.0, decode_responses=True)
            else:
                self.redis_client = redis.Redis(
                    host='main-social-zany-35066.db.redis.io',
                    port=15761,
                    decode_responses=True,
                    username="default",
                    password="FcXa3bLULKaixeEItPMlWAWN22il4m9v",
                    socket_timeout=2.0
                )
            self.redis_client.ping()
        except Exception as e:
            print(f"WARNING: Could not connect to Redis ({e}). Caching disabled.")
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
