"""
tutor/chat.py
─────────────
The chat orchestrator — the single function that ties everything together:

  1. Session management  (db/memory.py)
  2. Context retrieval   (retrieval/query.py)
  3. Answer generation   (tutor/llm.py)
  4. Turn persistence    (db/memory.py)

This is what the FastAPI endpoint calls. It is also usable from CLI.
"""

import logging
from schemas import ChatRequest, ChatResponse, SourceInfo
from db.memory import get_or_create_session, get_history, save_turn, get_session_message_count
from retrieval.query import query_system
from tutor.llm import TutorLLM

logger = logging.getLogger(__name__)

# ── Singleton TutorLLM to avoid re-creating the Groq client per request ──────
_tutor_llm: TutorLLM | None = None


def _get_tutor() -> TutorLLM:
    global _tutor_llm
    if _tutor_llm is None:
        _tutor_llm = TutorLLM()
    return _tutor_llm


def chat(request: ChatRequest) -> ChatResponse:
    """
    Complete chat flow:
      1. Get or create conversation session
      2. Load conversation memory (summary + recent 2 turns)
      3. Retrieve curriculum context from Qdrant
      4. Generate answer via TutorLLM
      5. Save the turn to PostgreSQL
      6. Return structured response

    Args:
        request : ChatRequest with session_id, question, class_num, subject

    Returns:
        ChatResponse with answer, sources, and session metadata
    """
    # ── 1. Session ────────────────────────────────────────────────────────────
    session_id = get_or_create_session(
        session_id=request.session_id,
        class_num=request.class_num,
        subject=request.subject,
    )

    # ── 2. Load memory ───────────────────────────────────────────────────────
    memory_summary, recent_history = get_history(session_id)
    logger.info(
        f"Session {session_id[:8]}... | "
        f"Memory: {len(memory_summary)} chars | "
        f"Recent: {len(recent_history)} messages"
    )

    # ── 3. Retrieve context ──────────────────────────────────────────────────
    context, sources, raw_chunks, route = _retrieve_context(request.question)

    # ── 4. Generate answer ───────────────────────────────────────────────────
    tutor = _get_tutor()
    answer = tutor.generate(
        question=request.question,
        context=context,
        history=recent_history,
        memory_summary=memory_summary,
    )

    # ── 5. Persist the turn ──────────────────────────────────────────────────
    routed_topic = sources[0].topic if sources else ""
    total_messages = save_turn(
        session_id=session_id,
        question=request.question,
        answer=answer,
        context_used=context[:500] if context else "",   # truncate for storage
        routed_topic=routed_topic,
    )

    # ── 6. Return ────────────────────────────────────────────────────────────
    return ChatResponse(
        session_id=session_id,
        answer=answer,
        sources=sources,
        conversation_length=total_messages,
        raw_chunks=raw_chunks,
        routed_chapter=route.get("chapter", "") if route else "",
        routed_topic=route.get("topic", "") if route else "",
    )


def _retrieve_context(question: str) -> tuple[str, list[SourceInfo], list[dict], dict | None]:
    """
    Calls the existing retrieval pipeline and extracts source metadata.

    Returns:
        (context_string, sources, raw_chunks, route)
    """
    # Import here to access the internals for source extraction
    from routing.router import SemanticRouter
    from retrieval.engine import RetrievalEngine
    from retrieval.reranker import Reranker

    # Route
    router = SemanticRouter()
    route = router.route_query(question)

    if not route:
        logger.warning("Routing failed — no curriculum topic matched.")
        return "", [], [], None

    logger.info(
        f"Routed → Class {route['class']} | {route['subject']} | "
        f"{route['chapter']} | {route['topic']}"
    )

    # Retrieve
    engine = RetrievalEngine()
    chunks = engine.retrieve(question, route, top_k=5)

    # Extract source metadata
    sources = []
    seen = set()
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        key = (meta.get("chapter", ""), meta.get("topic", ""))
        if key not in seen:
            seen.add(key)
            sources.append(SourceInfo(
                chapter=meta.get("chapter", "Unknown"),
                topic=meta.get("topic", "Unknown"),
                score=round(chunk.get("score", 0.0), 3),
            ))

    # Compress
    reranker = Reranker()
    context = reranker.compress_context(chunks)

    logger.info(f"Retrieved {len(chunks)} chunks, {len(sources)} unique sources")
    return context, sources, chunks, route
