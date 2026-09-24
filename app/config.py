"""
app/config.py
─────────────
Single source of truth for all environment configuration.
Migrated from Groq + sentence-transformers → Azure OpenAI (viswalpha-foundry-50bd).
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

    # ── Azure OpenAI (viswalpha-foundry-50bd) ──────────────────────────
    AZURE_OPENAI_API_KEY: str
    AZURE_OPENAI_BASE_URL: str = "https://viswalpha-foundry-50bd.openai.azure.com/openai/v1/"
    AZURE_OPENAI_CHAT_DEPLOYMENT: str = "viswalpha-gpt-4.1-mini"
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = "viswalpha-text-embedding-3-small"
    AZURE_OPENAI_EMBEDDING_DIMENSIONS: int = 1536

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

    # ── Orchestration & Sync ─────────────────────────────────────────────
    COGNITIVE_BATCH_SIZE: int = 4
    SESSION_SYNC_THRESHOLD_MINUTES: int = 30

    # ── Rate Limiting ────────────────────────────────────────────────────
    RATE_LIMIT_CHAT: str = "30/minute"
    RATE_LIMIT_READ: str = "120/minute"
    RATE_LIMIT_AUTH: str = "10/minute"

    # ── Admin Security ───────────────────────────────────────────────────────
    ADMIN_API_KEY: str = ""

    # ── JWT Authentication ───────────────────────────────────────────────────
    JWT_SECRET_KEY: str = "change-me-in-production-use-openssl-rand-hex-32"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 10_080  # 7 days

    # ── CORS ─────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:3000,http://localhost:8000, https://vishwalpha-ai-tutor-production.up.railway.app"

    # ── TensorFlow (suppress oneDNN logs) ───────────────────────────────────
    TF_ENABLE_ONEDNN_OPTS: str = "0"
    TF_CPP_MIN_LOG_LEVEL: str = "2"

    # ── Legacy (kept for backwards compat; no longer used) ──────────────
    GROQ_API_KEY: str = ""
    HF_TOKEN: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Returns the singleton Settings instance. Cached after first call."""
    return Settings()


# Module-level alias for clean imports: `from app.config import settings`
settings = get_settings()
