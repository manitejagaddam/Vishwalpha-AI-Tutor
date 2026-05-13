"""
retrieval/query.py
──────────────────
Handles the student query flow:
  1. Semantic Router  — maps the question to the most relevant curriculum topic
  2. Retrieval Engine — fetches top-k content chunks from Qdrant
  3. Reranker         — compresses retrieved chunks into a clean context string
"""

import logging
from routing.router import SemanticRouter
from retrieval.engine import RetrievalEngine
from retrieval.reranker import Reranker

logger = logging.getLogger(__name__)


def query_system(question: str) -> str | None:
    """
    Routes a student question to the correct curriculum topic, retrieves
    the most relevant content chunks, and returns a compressed context string.

    Args:
        question : The student's question in natural language.

    Returns:
        A compressed context string ready to be passed to a generation LLM,
        or None if routing fails.
    """
    logger.info("=" * 60)
    logger.info(f"QUERY: {question}")
    logger.info("=" * 60)

    # ── Step 1: Semantic Routing ──────────────────────────────────────────────
    router = SemanticRouter()
    route = router.route_query(question)

    if not route:
        logger.warning("Routing failed: no confident curriculum topic found.")
        return None

    logger.info(
        f"Routed → Class {route['class']} | {route['subject']} | "
        f"{route['chapter']} | Topic: {route['topic']}"
    )

    # ── Step 2: Retrieval ─────────────────────────────────────────────────────
    retrieval_engine = RetrievalEngine()
    chunks = retrieval_engine.retrieve(question, route, top_k=5)
    logger.info(f"Retrieved {len(chunks)} chunks from Qdrant")

    # ── Step 3: Reranking + Context Compression ───────────────────────────────
    reranker = Reranker()
    context = reranker.compress_context(chunks)

    logger.info("Context compressed and ready.")
    return context
