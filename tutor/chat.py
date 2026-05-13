"""
tutor/chat.py
─────────────
Agent-style chat orchestrator.

Two-step agent flow:
  Step 1 — CLASSIFY the question:
    "conversational" → answer from history only, NO Qdrant call
    "curriculum"     → retrieve from Qdrant with confidence gate, then generate

  Step 2 — GENERATE (mode-aware):
    conversational   → TutorLLM with history only (no context injected)
    curriculum       → TutorLLM with strictly retrieved context
                       If confidence < threshold → polite refusal (no hallucination)
"""

import os
import logging
from groq import Groq
from schemas import ChatRequest, ChatResponse, SourceInfo
from db.memory import get_or_create_session, get_history, save_turn
from tutor.llm import TutorLLM

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
# Minimum Qdrant cosine similarity score to consider a chunk relevant.
# Chunks below this are silently dropped — the LLM will not hallucinate to fill the gap.
RETRIEVAL_CONFIDENCE_THRESHOLD = 0.60

# ── Singletons ────────────────────────────────────────────────────────────────
_tutor_llm: TutorLLM | None = None
_groq_client: Groq | None = None


def _get_tutor() -> TutorLLM:
    global _tutor_llm
    if _tutor_llm is None:
        _tutor_llm = TutorLLM()
    return _tutor_llm


def _get_groq() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    return _groq_client


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Question Classifier
# ─────────────────────────────────────────────────────────────────────────────

def _classify_question(question: str, history_preview: str) -> str:
    """
    Classifies the student's message into one of two categories:
      "curriculum"     — a subject/topic question that needs Qdrant retrieval
      "conversational" — a greeting, acknowledgement, follow-up on what was JUST said,
                         or meta-question (e.g., "yes", "ok", "what did we discuss?")

    Uses a fast, cheap LLM call with temperature=0 for deterministic output.

    Returns:
        "curriculum" or "conversational"
    """
    prompt = f"""You are a question classifier for an educational chatbot.

Classify the student's message below into EXACTLY ONE of:
  - "curriculum"     : The student is asking about a specific subject topic, definition, concept,
                       equation, or any factual/educational content that requires a
                       textbook lookup. Examples: "What is photosynthesis?",
                       "Explain rancidity", "How do chemical reactions work?"
  - "conversational" : The student is chatting, asking a meta question, asking for study advice,
                       asking "what should I learn today?", asking for topic suggestions,
                       asking for a quiz, or continuing a conversation without needing
                       new textbook facts. Examples: "yes", "ok", "got it", "what did we discuss?",
                       "can you explain that again?", "tell me a topic I should learn today",
                       "give me a summary", "what's the plan?"

Recent conversation context (for reference):
{history_preview if history_preview else "(No prior conversation)"}

Student message: "{question}"

Reply with ONLY the word "curriculum" or "conversational". No explanation."""

    try:
        client = _get_groq()
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant"),
            temperature=0,
            max_tokens=5,
        )
        result = response.choices[0].message.content.strip().lower()
        if "curriculum" in result:
            return "curriculum"
        return "conversational"
    except Exception as e:
        logger.warning(f"Classifier failed, defaulting to curriculum: {e}")
        return "curriculum"


# ─────────────────────────────────────────────────────────────────────────────
# Step 2a: Retrieval with confidence gate
# ─────────────────────────────────────────────────────────────────────────────

def _retrieve_with_confidence(
    question: str,
) -> tuple[str, list[SourceInfo], list[dict], dict | None]:
    """
    Retrieves Qdrant chunks and filters out low-confidence results.

    Returns:
        (context, sources, raw_chunks, route)
        context will be "" if no chunk passes the confidence threshold.
    """
    from routing.router import SemanticRouter
    from retrieval.engine import RetrievalEngine
    from retrieval.reranker import Reranker

    # Route to the most relevant topic
    router = SemanticRouter()
    route = router.route_query(question)

    if not route:
        logger.info("Classifier→curriculum, but router found no matching topic.")
        return "", [], [], None

    logger.info(
        f"Routed → Class {route.get('class')} | {route.get('subject')} | "
        f"{route.get('chapter')} | {route.get('topic')}"
    )

    # Retrieve raw chunks
    engine = RetrievalEngine()
    raw_chunks = engine.retrieve(question, route, top_k=5)

    # ── Confidence gate ───────────────────────────────────────────────────────
    # Only keep chunks that meet the similarity threshold.
    # This prevents the LLM from "helping" with unrelated content.
    confident_chunks = [
        c for c in raw_chunks
        if c.get("score", 0) >= RETRIEVAL_CONFIDENCE_THRESHOLD
    ]

    if not confident_chunks:
        top_score = max((c.get("score", 0) for c in raw_chunks), default=0)
        logger.warning(
            f"All chunks below confidence threshold ({RETRIEVAL_CONFIDENCE_THRESHOLD}). "
            f"Best score: {top_score:.3f}. Blocking LLM from answering."
        )
        return "", [], raw_chunks, route  # raw_chunks still returned for UI display

    logger.info(
        f"Confidence gate: {len(confident_chunks)}/{len(raw_chunks)} chunks passed "
        f"(threshold={RETRIEVAL_CONFIDENCE_THRESHOLD})"
    )

    # Build source metadata from confident chunks only
    sources = []
    seen = set()
    for chunk in confident_chunks:
        meta = chunk.get("metadata", {})
        key = (meta.get("chapter", ""), meta.get("topic", ""))
        if key not in seen:
            seen.add(key)
            sources.append(SourceInfo(
                chapter=meta.get("chapter", "Unknown"),
                topic=meta.get("topic", "Unknown"),
                score=round(chunk.get("score", 0.0), 3),
            ))

    # Compress confident chunks into context string
    reranker = Reranker()
    context = reranker.compress_context(confident_chunks)

    return context, sources, raw_chunks, route


# ─────────────────────────────────────────────────────────────────────────────
# Main chat entry point
# ─────────────────────────────────────────────────────────────────────────────

def chat(request: ChatRequest) -> ChatResponse:
    """
    Agent-style chat flow:

      1. Get/create session + load conversation memory
      2. Classify question: "curriculum" or "conversational"
      3a. [conversational] → generate from history only
      3b. [curriculum]     → retrieve from Qdrant (with confidence gate)
                          → if no confident chunks: return "not in my materials"
                          → else: generate strictly from retrieved context
      4. Persist turn to PostgreSQL
      5. Return ChatResponse
    """
    # ── 1. Session + memory ───────────────────────────────────────────────────
    session_id = get_or_create_session(
        session_id=request.session_id,
        class_num=request.class_num,
        subject=request.subject,
    )
    memory_summary, recent_history = get_history(session_id)

    logger.info(
        f"Session {session_id[:8]}... | "
        f"Memory: {len(memory_summary)} chars | "
        f"Recent: {len(recent_history)} messages"
    )

    # ── 2. Classify ───────────────────────────────────────────────────────────
    # Build a brief history preview for the classifier
    history_preview = "\n".join(
        f"{m.role.capitalize()}: {m.content}" for m in recent_history[-4:]
    )
    question_type = _classify_question(request.question, history_preview)
    logger.info(f"Question classified as: '{question_type}'")

    # ── 3. Route by classification ────────────────────────────────────────────
    context = ""
    sources: list[SourceInfo] = []
    raw_chunks: list[dict] = []
    route: dict | None = None
    is_grounded = False

    if question_type == "conversational":
        # Pure conversational — no Qdrant, answer from history
        logger.info("Mode: conversational (no retrieval)")

    else:
        # Curriculum question — retrieve with confidence gate
        logger.info("Mode: curriculum (Qdrant retrieval)")
        context, sources, raw_chunks, route = _retrieve_with_confidence(request.question)
        is_grounded = bool(context)

        if not is_grounded:
            # No confident chunks found — return a polite refusal immediately
            # Do NOT call the generative LLM (prevents hallucination)
            refusal = (
                "I couldn't find specific information about this in the textbook content "
                "I have loaded right now. Could you try rephrasing your question, "
                "or ask about a topic from your NCERT chapters?"
            )
            total_messages = save_turn(
                session_id=session_id,
                question=request.question,
                answer=refusal,
                context_used="",
                routed_topic=route.get("topic", "") if route else "",
            )
            return ChatResponse(
                session_id=session_id,
                answer=refusal,
                sources=[],
                conversation_length=total_messages,
                raw_chunks=raw_chunks,
                routed_chapter=route.get("chapter", "") if route else "",
                routed_topic=route.get("topic", "") if route else "",
            )

    # ── 4. Generate ───────────────────────────────────────────────────────────
    tutor = _get_tutor()
    answer, prompt_messages = tutor.generate(
        question=request.question,
        context=context,                    # "" for conversational, real context for curriculum
        history=recent_history,
        memory_summary=memory_summary,
        question_type=question_type,        # controls system prompt strictness
        is_grounded=is_grounded,
        class_num=request.class_num,
        subject=request.subject,
    )


    # ── 5. Persist ────────────────────────────────────────────────────────────
    routed_topic = sources[0].topic if sources else (route.get("topic", "") if route else "")
    total_messages = save_turn(
        session_id=session_id,
        question=request.question,
        answer=answer,
        context_used=context[:500] if context else "",
        routed_topic=routed_topic,
    )

    # ── 6. Return ─────────────────────────────────────────────────────────────
    return ChatResponse(
        session_id=session_id,
        answer=answer,
        sources=sources,
        conversation_length=total_messages,
        raw_chunks=raw_chunks,
        routed_chapter=route.get("chapter", "") if route else "",
        routed_topic=route.get("topic", "") if route else "",
        question_type=question_type,
        prompt_messages=prompt_messages,
    )
