"""
retrieval/query.py
──────────────────
Orchestrates the entire query and retrieval flow.
"""

import logging
from routing.router import SemanticRouter
from retrieval.engine import RetrievalEngine
from retrieval.reranker import Reranker

logger = logging.getLogger(__name__)

_router: SemanticRouter | None = None
_engine: RetrievalEngine | None = None
_reranker: Reranker | None = None

def _get_router() -> SemanticRouter:
    """Lazy initialization of the SemanticRouter."""
    global _router
    if _router is None:
        _router = SemanticRouter()
    return _router

def _get_engine() -> RetrievalEngine:
    """Lazy initialization of the RetrievalEngine."""
    global _engine
    if _engine is None:
        _engine = RetrievalEngine()
    return _engine

def _get_reranker() -> Reranker:
    """Lazy initialization of the Reranker."""
    global _reranker
    if _reranker is None:
        _reranker = Reranker()
    return _reranker

def query_system(
    question: str,
    class_num: int | None = None,   # Phase 1.7: scope routing to student class
    subject: str | None = None,     # Phase 1.7: scope routing to student subject
) -> str | None:
    """
    Routes a student question to the correct curriculum topic, retrieves
    the most relevant content chunks, and returns a compressed context string.

    Phase 1 fix: class_num and subject are now passed into route_query() as
    pre-filters BEFORE cosine similarity sorting (not patched on after).

    Args:
        question  : The student's question in natural language.
        class_num : Student's class number to scope routing (optional).
        subject   : Subject name to scope routing (optional).

    Returns:
        A compressed context string ready to be passed to a generation LLM,
        or None if routing fails.
    """
    logger.info("=" * 60)
    logger.info(f"QUERY: {question}")
    logger.info("=" * 60)

    router = _get_router()
    # Phase 1.7 fix: pass class_num + subject as pre-filters
    route = router.route_query(question, class_num=class_num, subject=subject)

    if not route:
        logger.warning("Routing failed: no confident curriculum topic found.")
        return None

    logger.info(
        f"Routed → Class {route['class']} | {route['subject']} | "
        f"{route['chapter']} | Topic: {route['topic']}"
    )

    retrieval_engine = _get_engine()
    chunks = retrieval_engine.retrieve(question, route, top_k=5)
    logger.info(f"Retrieved {len(chunks)} chunks")

    reranker = _get_reranker()
    context = reranker.compress_context(chunks)

    logger.info("Context compressed and ready.")
    return context
