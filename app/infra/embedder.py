"""
app/infra/embedder.py
─────────────────────
Azure OpenAI embedding client — replaces the sentence-transformers local model.
Uses `viswalpha-text-embedding-3-small` via the Azure Foundry OpenAI-compatible
v1 endpoint. Caches embeddings through Redis (handled by RetrievalCache) so the
10k TPM quota is not exhausted on repeated identical queries.

Dimension: 1536 (default for text-embedding-3-small).
"""
import logging
from app.infra.azure_openai_client import get_openai
from app.config import settings

logger = logging.getLogger(__name__)


class Embedder:
    """
    Thin wrapper around the Azure OpenAI embeddings API.
    Thread-safe: the underlying OpenAI client is a module-level singleton.
    """

    def __init__(self, model: str | None = None):
        self.model = model or settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT
        self.dimensions = settings.AZURE_OPENAI_EMBEDDING_DIMENSIONS
        self.client = get_openai()

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Calls the Azure embedding API and returns a list of float vectors."""
        response = self.client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dimensions,
            encoding_format="float",
        )
        # response.data is sorted by index
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]

    def embed_document(self, text: str) -> list[float]:
        """Embeds a single document chunk for storage/retrieval."""
        return self._embed([text])[0]

    def embed_query(self, query: str) -> list[float]:
        """
        Embeds a search query.
        text-embedding-3-small does not need an instruction prefix —
        unlike BGE models, it handles asymmetric retrieval natively.
        """
        return self._embed([query])[0]
