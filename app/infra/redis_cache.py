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

    def _safe_del(self, *keys: str) -> None:
        if not self._client or not keys:
            return
        try:
            self._client.delete(*keys)
        except Exception as exc:
            logger.debug(f"Cache DEL error: {exc}")

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

    def _ret_key(self, query: str, class_num, subject: str, board_id=None) -> str:
        brd = str(board_id) if board_id is not None else "any"
        cls = str(class_num) if class_num is not None else "any"
        sub = (subject or "any").lower()
        return f"ret:{brd}:{cls}:{sub}:{self._normalize(query)}"

    def get_chunks(self, query: str, class_num, subject: str, board_id=None) -> list[dict] | None:
        raw = self._safe_get(self._ret_key(query, class_num, subject, board_id))
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return None
        return None

    def set_chunks(
        self, query: str, class_num, subject: str, chunks: list[dict], board_id=None
    ) -> None:
        if not chunks:
            return
        self._safe_setex(
            self._ret_key(query, class_num, subject, board_id),
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
        return self.invalidate_subject(class_num, subject)

    def invalidate_subject(self, class_num, subject: str, board_id=None) -> int:
        """Clears all retrieval cache keys for a board+class+subject after re-ingestion."""
        if not self._client:
            return 0
        try:
            brd = str(board_id) if board_id is not None else "*"
            pattern = f"ret:{brd}:{class_num}:{subject.lower()}:*"
            # Use SCAN instead of KEYS — KEYS is blocked on Upstash (serverless Redis)
            keys: list[str] = []
            cursor = 0
            while True:
                cursor, partial = self._client.scan(cursor, match=pattern, count=100)
                keys.extend(partial)
                if cursor == 0:
                    break
            if keys:
                self._client.delete(*keys)
            logger.info(
                f"Cache invalidated {len(keys)} keys for board={board_id}, class={class_num}, subject={subject}"
            )
            return len(keys)
        except Exception as exc:
            logger.warning(f"Cache invalidation error: {exc}")
            return 0

    # ── Layer 4: Ingestion structuring cache ───────────────────────────────────
    # Caches LLM _structure_chunk() results by MD5 of (chapter+text).
    # Avoids re-calling the LLM for identical PDF content on re-ingestion.

    _INGEST_STRUCT_TTL = 60 * 60 * 24 * 30  # 30 days

    def get_ingest_struct(self, cache_key: str) -> dict | None:
        raw = self._safe_get(f"ingest:struct:{cache_key}")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return None
        return None

    def set_ingest_struct(self, cache_key: str, data: dict) -> None:
        self._safe_setex(
            f"ingest:struct:{cache_key}",
            self._INGEST_STRUCT_TTL,
            json.dumps(data),
        )

    # ── Layer 5: Session State Cache ───────────────────────────────────────────
    # Caches per-student, per-subject data that changes only every BATCH_TURN_INTERVAL turns:
    #   - cognitive metrics (10 scores)       key: sess:metrics:{user_id}:{subject_id}
    #   - learning preferences                key: sess:prefs:{user_id}
    #   - student memory items                key: sess:memory:{user_id}:{subject_id}
    #   - weak topics list                    key: sess:weak:{user_id}:{subject_id}
    #
    # TTL is short (30 min session window). On batch update (every 4 turns),
    # the orchestrator calls invalidate_session_state() to force a fresh DB read.
    #
    # All methods are fail-safe — a Redis miss just means we read from DB.

    _SESSION_TTL = 60 * 30  # 30 minutes

    def get_session_metrics(self, user_id: str, subject_id: int) -> dict | None:
        raw = self._safe_get(f"sess:metrics:{user_id}:{subject_id}")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return None
        return None

    def set_session_metrics(self, user_id: str, subject_id: int, metrics: dict) -> None:
        self._safe_setex(
            f"sess:metrics:{user_id}:{subject_id}",
            self._SESSION_TTL,
            json.dumps(metrics),
        )

    def get_session_prefs(self, user_id: str) -> dict | None:
        raw = self._safe_get(f"sess:prefs:{user_id}")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return None
        return None

    def set_session_prefs(self, user_id: str, prefs: dict) -> None:
        self._safe_setex(
            f"sess:prefs:{user_id}",
            self._SESSION_TTL,
            json.dumps(prefs),
        )

    def get_session_memory(self, user_id: str, subject_id: int) -> list | None:
        raw = self._safe_get(f"sess:memory:{user_id}:{subject_id}")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return None
        return None

    def set_session_memory(self, user_id: str, subject_id: int, items: list) -> None:
        self._safe_setex(
            f"sess:memory:{user_id}:{subject_id}",
            self._SESSION_TTL,
            json.dumps(items),
        )

    def get_session_weak_topics(self, user_id: str, subject_id: int) -> list | None:
        raw = self._safe_get(f"sess:weak:{user_id}:{subject_id}")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return None
        return None

    def set_session_weak_topics(self, user_id: str, subject_id: int, topics: list) -> None:
        self._safe_setex(
            f"sess:weak:{user_id}:{subject_id}",
            self._SESSION_TTL,
            json.dumps(topics),
        )

    def invalidate_session_state(self, user_id: str, subject_id: int) -> None:
        """
        Called after every batch update (every 4 turns) to force a fresh DB read
        on the next turn. Also call after quiz completion or profile preset change.
        """
        keys = [
            f"sess:metrics:{user_id}:{subject_id}",
            f"sess:prefs:{user_id}",
            f"sess:memory:{user_id}:{subject_id}",
            f"sess:weak:{user_id}:{subject_id}",
        ]
        if not self._client:
            return
        try:
            self._client.delete(*keys)
            logger.debug(f"Session state cache invalidated for user={user_id} subject={subject_id}")
        except Exception as exc:
            logger.debug(f"Session cache invalidation error: {exc}")


_retrieval_cache_instance: RetrievalCache | None = None


def get_redis_cache() -> RetrievalCache:
    """Returns the singleton RetrievalCache instance."""
    global _retrieval_cache_instance
    if _retrieval_cache_instance is None:
        _retrieval_cache_instance = RetrievalCache()
    return _retrieval_cache_instance
