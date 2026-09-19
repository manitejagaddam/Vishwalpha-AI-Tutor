"""
app/infra/embedder.py
─────────────────────
Sentence-transformer embedding model — loaded exactly once per process.
Uses functools.lru_cache so the model survives across requests without
being reloaded, even if the Embedder class is re-instantiated.
"""
import warnings
import logging
import functools

warnings.filterwarnings("ignore", message=".*Accessing `__path__`.*")

from sentence_transformers import SentenceTransformer
from app.config import settings

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _load_model(model_name: str, token: str) -> SentenceTransformer:
    """Loads and caches the SentenceTransformer model globally."""
    logger.info(f"Loading embedding model: {model_name} (one-time)")
    return SentenceTransformer(model_name, token=token or None)


class Embedder:
    """
    Thin wrapper around the globally-cached SentenceTransformer model.
    Thread-safe: lru_cache is process-level, not instance-level.
    """

    def __init__(self, model_name: str = None):
        model_name = model_name or settings.EMBEDDING_MODEL
        self.model = _load_model(model_name, settings.HF_TOKEN)

    def embed_document(self, text: str) -> list[float]:
        """Embeds a document chunk for storage/retrieval."""
        return self.model.encode(text, normalize_embeddings=True).tolist()

    def embed_query(self, query: str) -> list[float]:
        """
        Embeds a search query. BGE models benefit from an instruction prefix
        to improve retrieval quality.
        """
        instruction = "Represent this sentence for searching relevant passages: "
        return self.model.encode(
            instruction + query, normalize_embeddings=True
        ).tolist()
