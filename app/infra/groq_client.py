"""
app/infra/groq_client.py
────────────────────────
Singleton Groq LLM client. Import `get_groq` anywhere to get the shared instance.
"""
from functools import lru_cache
from groq import Groq
from app.config import settings


@lru_cache(maxsize=1)
def get_groq() -> Groq:
    """Returns the singleton Groq client, initialised once on first call."""
    return Groq(api_key=settings.GROQ_API_KEY)
