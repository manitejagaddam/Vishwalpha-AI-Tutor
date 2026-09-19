"""
app/infra/redis_cache.py
─────────────────────────
3-layer Redis cache for the retrieval pipeline.

Layer 1 — Embedding cache     key: "emb:<query>"          TTL: 7 days
Layer 2 — Retrieval cache     key: "ret:<class>:<sub>:<q>" TTL: 30 days
Layer 3 — Prerequisite cache  key: "prereq:<topic_id>"     TTL: 30 days

All methods are fail-safe: a Redis outage never breaks the chat flow —
it just means every request hits the DB directly.
"""
import re
import json
import logging

import redis as redis_lib

from app.config import settings

logger = logging.getLogger(__name__)


def _build_redis_client() -> "redis_lib.Redis | None":
    """Connects to Redis, returns None if unavailable."""
    try:
        if settings.REDIS_URL:
            client = redis_lib.Redis.from_url(
                settings.REDIS_URL, socket_timeout=2.0, decode_responses=True
            )
        else:
            client = redis_lib.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                username=settings.REDIS_USERNAME,
                password=settings.REDIS_PASSWORD,
                decode_responses=True,
                socket_timeout=2.0,
            )
        client.ping()
        logger.info("Redis cache: connected.")
        return client
    except Exception as exc:
        logger.warning(f"Redis unavailable ({exc}). Cache disabled — falling back to DB.")
        return None


class RetrievalCache:
    """
    3-layer Redis cache. Instantiate once and share (singleton pattern).
    Every public method is safe to call even when Redis is down.
    """

    def __init__(self):
        self._client = _build_redis_client()

    # ── Internals ──────────────────────────────────────────────────────────────

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower().strip()))

    def _safe_get(self, key: str):
        if not self._client:
            return None
        try:
            return self._client.get(key)
        except Exception as exc:
            logger.debug(f"Cache GET error [{key}]: {exc}")
            return None

    def _safe_setex(self, key: str, ttl: int, value: str) -> None:
        if not self._client:
            return
        try:
            self._client.setex(key, ttl, value)
        except Exception as exc:
            logger.debug(f"Cache SET error [{key}]: {exc}")

    # ── Layer 1: Embedding cache ───────────────────────────────────────────────

    def get_embedding(self, query: str) -> list[float] | None:
        raw = self._safe_get(f"emb:{self._normalize(query)}")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return None
        return None

    def set_embedding(self, query: str, vector: list[float]) -> None:
        self._safe_setex(
            f"emb:{self._normalize(query)}",
            settings.CACHE_EMB_TTL,
            json.dumps(vector),
        )

    # ── Layer 2: Scoped retrieval cache ───────────────────────────────────────

    def _ret_key(self, query: str, class_num, subject: str) -> str:
        cls = str(class_num) if class_num is not None else "any"
        sub = (subject or "any").lower()
        return f"ret:{cls}:{sub}:{self._normalize(query)}"

    def get_chunks(self, query: str, class_num, subject: str) -> list[dict] | None:
        raw = self._safe_get(self._ret_key(query, class_num, subject))
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return None
        return None

    def set_chunks(
        self, query: str, class_num, subject: str, chunks: list[dict]
    ) -> None:
        if not chunks:
            return
        self._safe_setex(
            self._ret_key(query, class_num, subject),
            settings.CACHE_CHUNK_TTL,
            json.dumps(chunks),
        )

    # ── Layer 3: Prerequisite cache ────────────────────────────────────────────

    def get_prerequisites(self, topic_id: int) -> list[dict] | None:
        raw = self._safe_get(f"prereq:{topic_id}")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return None
        return None

    def set_prerequisites(self, topic_id: int, prereqs: list[dict]) -> None:
        if not prereqs:
            return
        self._safe_setex(
            f"prereq:{topic_id}", settings.CACHE_PREREQ_TTL, json.dumps(prereqs)
        )

    # ── Cache invalidation ─────────────────────────────────────────────────────

    def invalidate_chapter(self, class_num, subject: str) -> int:
        """Clears all retrieval cache keys for a class+subject after re-ingestion."""
        if not self._client:
            return 0
        try:
            pattern = f"ret:{class_num}:{subject.lower()}:*"
            keys = self._client.keys(pattern)
            if keys:
                self._client.delete(*keys)
            logger.info(f"Cache invalidated {len(keys)} keys for class={class_num}, subject={subject}")
            return len(keys)
        except Exception as exc:
            logger.warning(f"Cache invalidation error: {exc}")
            return 0
