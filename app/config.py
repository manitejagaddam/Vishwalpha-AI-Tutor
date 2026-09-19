"""
app/config.py
─────────────
Single source of truth for all environment configuration.
Uses pydantic-settings so values are type-validated at startup.
All other modules import `settings` from here instead of calling os.getenv().
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ────────────────────────────────────────────────────────
    DATABASE_URL: str

    # ── AI / LLM ────────────────────────────────────────────────────────
    GROQ_API_KEY: str
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    HF_TOKEN: str = ""

    # ── Embedding ───────────────────────────────────────────────────────
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"

    # ── Redis Cache ─────────────────────────────────────────────────────
    REDIS_URL: str = ""
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_USERNAME: str = "default"
    REDIS_PASSWORD: str = ""
    CACHE_EMB_TTL: int = 604_800    # 7 days
    CACHE_CHUNK_TTL: int = 2_592_000 # 30 days
    CACHE_PREREQ_TTL: int = 2_592_000

    # ── Retrieval ────────────────────────────────────────────────────────
    RETRIEVAL_CONFIDENCE_THRESHOLD: float = 0.60

    # ── Rate Limiting ────────────────────────────────────────────────────
    RATE_LIMIT_CHAT: str = "30/minute"
    RATE_LIMIT_READ: str = "120/minute"
    RATE_LIMIT_AUTH: str = "10/minute"

    # ── Admin Security ───────────────────────────────────────────────────
    ADMIN_API_KEY: str = ""

    # ── TensorFlow (suppress oneDNN logs) ───────────────────────────────
    TF_ENABLE_ONEDNN_OPTS: str = "0"
    TF_CPP_MIN_LOG_LEVEL: str = "2"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Returns the singleton Settings instance. Cached after first call."""
    return Settings()


# Module-level alias for clean imports: `from app.config import settings`
settings = get_settings()
