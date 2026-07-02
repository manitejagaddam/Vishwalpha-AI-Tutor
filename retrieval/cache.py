"""
retrieval/cache.py
──────────────────
Redis-based caching for retrieval queries to reduce database load.
"""
import os
import redis
import json

class QueryCache:
    """
    Manages caching of retrieved context using Redis.
    Falls back gracefully if Redis is unavailable.
    """
    def __init__(self):
        self.redis_client = self._build_client()

    def _build_client(self) -> redis.Redis | None:
        """
        Builds and returns the Redis client, or None if connection fails.
        """
        redis_url = os.environ.get("REDIS_URL")
        try:
            if redis_url:
                client = redis.Redis.from_url(redis_url, socket_timeout=2.0, decode_responses=True)
            else:
                client = redis.Redis(
                    host='main-social-zany-35066.db.redis.io',
                    port=15761,
                    decode_responses=True,
                    username="default",
                    password="FcXa3bLULKaixeEItPMlWAWN22il4m9v",
                    socket_timeout=2.0
                )
            client.ping()
            return client
        except Exception as e:
            print(f"WARNING: Could not connect to Redis ({e}). Caching disabled.")
            return None

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
