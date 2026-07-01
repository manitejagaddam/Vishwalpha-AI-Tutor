import os
import warnings
from dotenv import load_dotenv

# Suppress noisy transformers warnings
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
warnings.filterwarnings("ignore", message=".*Accessing `__path__`.*")

# Load environment variables early so Hugging Face client sees the HF_TOKEN
load_dotenv(override=True)

from sentence_transformers import SentenceTransformer

class Embedder:
    _model_cache = {}

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        # Initialize BGE-small locally only once
        if model_name not in Embedder._model_cache:
            print(f"Loading embedding model: {model_name}")
            hf_token = os.environ.get("HF_TOKEN")
            # Pass HF_TOKEN to ensure authenticated/faster download from HF Hub
            Embedder._model_cache[model_name] = SentenceTransformer(
                model_name, 
                token=hf_token
            )
        self.model = Embedder._model_cache[model_name]

    def embed_document(self, text: str) -> list[float]:
        """
        Embeds a document (like a chapter or topic summary).
        """
        return self.model.encode(text, normalize_embeddings=True).tolist()
        
    def embed_query(self, query: str) -> list[float]:
        """
        Embeds a search query. 
        BGE models often use a specific instruction for queries to improve retrieval.
        """
        instruction = "Represent this sentence for searching relevant passages: "
        return self.model.encode(instruction + query, normalize_embeddings=True).tolist()
