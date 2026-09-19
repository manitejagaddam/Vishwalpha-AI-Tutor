"""
retrieval/cache.py
──────────────────
3-layer Redis-backed cache for the retrieval engine (Phase 5.2).

Layer 1 — Embedding cache
    key  : "emb:<normalized_query>"
    TTL  : 7 days  (604 800 s)
    value: JSON-serialised list[float]

Layer 2 — Scoped retrieval cache
    key  : "retrieval:<class_num>:<subject>:<normalized_query>"
    TTL  : 30 days (2 592 000 s) — curriculum is static for ≥ 1 year
    value: JSON-serialised list[dict]

Layer 3 — Prerequisite cache
    key  : "prereqs:<topic_id>"
    TTL  : 30 days (2 592 000 s)
    value: JSON-serialised list[dict]

All public methods wrap every Redis call in try/except so a Redis outage
degrades gracefully to direct DB queries without breaking the chat flow.
Cache invalidation: call invalidate_chapter() after any curriculum re-ingestion.
"""
import os
import re
import json
import logging
import redis

logger = logging.getLogger(__name__)

_EMB_TTL   = int(os.getenv("CACHE_EMB_TTL",    604_800))    # 7 days
_CHUNK_TTL = int(os.getenv("CACHE_CHUNK_TTL", 2_592_000))   # 30 days
_PREREQ_TTL = int(os.getenv("CACHE_PREREQ_TTL", 2_592_000)) # 30 days


class QueryCache:
    """
    3-layer Redis cache used by the RetrievalEngine.
    Falls back gracefully to None / empty if Redis is unavailable.
    """

    def __init__(self):
        self._client: redis.Redis | None = self._build_client()

    # ─────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────

    def _build_client(self) -> redis.Redis | None:
        redis_url = os.environ.get("REDIS_URL")
        try:
            if redis_url:
                client = redis.Redis.from_url(
                    redis_url, socket_timeout=2.0, decode_responses=True
                )
            else:
                client = redis.Redis(
                    host=os.getenv("REDIS_HOST", "main-social-zany-35066.db.redis.io"),
                    port=int(os.getenv("REDIS_PORT", 15761)),
                    username=os.getenv("REDIS_USERNAME", "default"),
                    password=os.getenv("REDIS_PASSWORD", "FcXa3bLULKaixeEItPMlWAWN22il4m9v"),
                    decode_responses=True,
                    socket_timeout=2.0,
                )
            client.ping()
            logger.info("QueryCache: Redis connected.")
            return client
        except Exception as e:
            logger.warning(f"QueryCache: Redis unavailable ({e}). Caching disabled.")
            return None

    def _normalize(self, query: str) -> str:
        """Strips punctuation, lowercases, collapses whitespace."""
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", query.lower().strip()))

    def _scoped_key(self, query: str, class_num, subject) -> str:
        norm = self._normalize(query)
        cls  = str(class_num) if class_num is not None else "any"
        sub  = (subject or "any").lower()
        return f"retrieval:{cls}:{sub}:{norm}"

    def _safe_get(self, key: str):
        if not self._client:
            return None
        try:
            return self._client.get(key)
        except Exception as e:
            logger.debug(f"QueryCache.get error for key={key}: {e}")
            return None

    def _safe_setex(self, key: str, ttl: int, value: str) -> None:
        if not self._client:
            return
        try:
            self._client.setex(key, ttl, value)
        except Exception as e:
            logger.debug(f"QueryCache.set error for key={key}: {e}")

    # ─────────────────────────────────────────────────────────────
    # Layer 1 — Embedding cache (7-day TTL)
    # ─────────────────────────────────────────────────────────────

    def get_embedding(self, query: str) -> list[float] | None:
        """Returns cached embedding vector for a query, or None on miss."""
        raw = self._safe_get(f"emb:{self._normalize(query)}")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return None
        return None

    def set_embedding(self, query: str, vector: list[float], ttl: int = _EMB_TTL) -> None:
        """Caches an embedding vector for a query."""
        self._safe_setex(
            f"emb:{self._normalize(query)}", ttl, json.dumps(vector)
        )

    # ─────────────────────────────────────────────────────────────
    # Layer 2 — Scoped retrieval cache (30-day TTL)
    # ─────────────────────────────────────────────────────────────

    def get_chunks(
        self, query: str, class_num, subject
    ) -> list[dict] | None:
        """Returns cached chunks for a scoped query, or None on miss."""
        raw = self._safe_get(self._scoped_key(query, class_num, subject))
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return None
        return None

    def set_chunks(
        self,
        query: str,
        class_num,
        subject,
        chunks: list[dict],
        ttl: int = _CHUNK_TTL,
    ) -> None:
        """Caches the retrieved chunks for a scoped query."""
        if not chunks:
            return  # don't cache empty results
        self._safe_setex(
            self._scoped_key(query, class_num, subject), ttl, json.dumps(chunks)
        )

    # ─────────────────────────────────────────────────────────────
    # Layer 3 — Prerequisite cache (30-day TTL)
    # ─────────────────────────────────────────────────────────────

    def get_prerequisites(self, topic_id: int) -> list[dict] | None:
        """Returns cached prerequisites for a topic_id, or None on miss."""
        raw = self._safe_get(f"prereqs:{topic_id}")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return None
        return None

    def set_prerequisites(
        self, topic_id: int, prereqs: list[dict], ttl: int = _PREREQ_TTL
    ) -> None:
        """Caches prerequisites for a topic_id."""
        if not prereqs:
            return
        self._safe_setex(f"prereqs:{topic_id}", ttl, json.dumps(prereqs))

    # ─────────────────────────────────────────────────────────────
    # Cache invalidation
    # ─────────────────────────────────────────────────────────────

    def invalidate_chapter(self, class_num, subject: str, chapter: str) -> int:
        """
        Flushes all retrieval cache keys for a given class/subject scope.
        Call after re-ingesting curriculum content for a chapter.
        Returns number of keys deleted.
        """
        if not self._client:
            return 0
        try:
            pattern = f"retrieval:{class_num}:{subject.lower()}:*"
            keys = self._client.keys(pattern)
            if keys:
                self._client.delete(*keys)
            logger.info(
                f"QueryCache: invalidated {len(keys)} keys for "
                f"class={class_num}, subject={subject}, chapter={chapter}"
            )
            return len(keys)
        except Exception as e:
            logger.warning(f"QueryCache.invalidate_chapter error: {e}")
            return 0

    # ─────────────────────────────────────────────────────────────
    # Legacy compatibility shim (used by old callers)
    # ─────────────────────────────────────────────────────────────

    def get(self, query: str) -> list[dict] | None:
        """Legacy single-key get — maps to unscoped chunk lookup."""
        return self.get_chunks(query, None, None)

    def set(self, query: str, context: list[dict], ttl_seconds: int = 3600) -> None:
        """Legacy single-key set — maps to unscoped chunk store."""
        self.set_chunks(query, None, None, context, ttl=ttl_seconds)
