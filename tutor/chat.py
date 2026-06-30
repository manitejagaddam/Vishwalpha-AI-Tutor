"""
tutor/chat.py
─────────────
Agent-style chat orchestrator.

Two-step agent flow:
  Step 1 — CLASSIFY the question:
    "conversational" → answer from history only, NO pgvector call
    "curriculum"     → retrieve from pgvector with confidence gate, then generate

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
# Minimum pgvector cosine similarity score to consider a chunk relevant.
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


import re

# ── Conversational Patterns & Keywords (Heuristics) ───────────────────────────
# List of regex patterns for conversational inputs that should skip pgvector retrieval
CONVERSATIONAL_PATTERNS = [
    # Greetings / Farewells / Politeness
    r"^(hi|hello|hey|greetings|good morning|good afternoon|good evening|bye|goodbye|see ya|see you)[\s.!]*$",
    r"^(thanks|thank you|thx|tysm|appreciate it)[\s.!]*$",
    # Acknowledgements / short replies
    r"^(yes|no|ok|okay|sure|yep|nope|got it|makes sense|i see|alright|fine|cool|indeed)[\s.!]*$",
    r"^(correct|wrong|true|false|exactly|absolutely)[\s.!]*$",
    # Meta questions / navigation
    r"^(what did we discuss|what did we talk about|what was the last thing|recap the last part|what did you say)[\s.!]*$",
    r"^(can we (do a quiz|start a quiz|do a test|practice|start|stop|continue|pause|resume|reset))[\s.!]*$",
    r"^(give me a (quiz|test|question|summary|recap))[\s.!]*$",
    r"^(what is the plan|what should we do next|what's next)[\s.!]*$",
    # Clarifications & feedback
    r"^(can you (explain that again|repeat that|say that again|rephrase that|explain in more detail))[\s.!]*$",
    r"^(i (don't understand|do not understand|get it|don't get it|understand))[\s.!]*$",
]

# Set of specific single words or short phrases that are definitely conversational
CONVERSATIONAL_KEYWORDS = {
    "yes", "no", "ok", "okay", "sure", "yep", "nope", "thanks", "thank you", "hi", "hello",
    "hey", "correct", "wrong", "got it", "i see", "undestood", "understood", "makes sense",
    "bye", "goodbye", "help", "next", "continue", "reset", "clear"
}

def _heuristic_is_conversational(question: str) -> bool:
    """
    Algorithmic heuristic to identify conversational messages.
    Returns True if the message is conversational (skips pgvector RAG),
    False if it requires pgvector textbook retrieval.
    """
    clean_question = question.strip().lower()
    
    # 1. Very short messages are almost always conversational (e.g. "ok", "why?", "yes")
    if len(clean_question) < 15:
        # If it contains "?" and is at least 8 chars, it could be a very short question like "What is pH?"
        if "?" in clean_question:
            # Check if it has textbook keywords to avoid false positives
            keywords = ["what", "why", "how", "define", "acid", "base", "salt", "metal", "reaction", "ph", "formula", "atom", "molecule"]
            if any(kw in clean_question for kw in keywords):
                return False
        return True
        
    # 2. Check exact matches in our common keyword set (removing punctuation)
    cleaned_words = re.sub(r"[^\w\s]", "", clean_question).strip()
    if cleaned_words in CONVERSATIONAL_KEYWORDS:
        return True
        
    # 3. Check regular expression patterns
    for pattern in CONVERSATIONAL_PATTERNS:
        if re.search(pattern, clean_question):
            return True
            
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Step 2a: Retrieval with confidence gate
# ─────────────────────────────────────────────────────────────────────────────

def _retrieve_with_confidence(
    question: str,
    class_num: int = None,
    subject: str = None
) -> tuple[str, list[SourceInfo], list[dict], dict | None]:
    """
    Retrieves pgvector chunks and filters out low-confidence results.

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

    # Retrieve raw chunks (engine should pre-filter by class_num and subject if supported)
    engine = RetrievalEngine()
    # If the engine supports pre-filtering, we can pass class_num and subject. 
    # For now, we rely on the router to constrain it, but we add them to the route constraints.
    if class_num:
        route["class"] = class_num
    if subject:
        route["subject"] = subject
        
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
      2. Run Cognitive Middleware (pre-generation metrics evaluation & adjustment)
      3. Classify question: "curriculum" or "conversational"
      4a. [conversational] → generate from history only
      4b. [curriculum]     → retrieve from pgvector (with confidence gate)
                          → if no confident chunks: return "not in my materials"
                          → else: generate strictly from retrieved context
      5. Persist turn to PostgreSQL
      6. Return ChatResponse
    """
    from db.database import SessionLocal
    from db.metrics import collect_turn_signals, append_pending_signal, batch_update_cognitive_profile, compute_cognitive_skills, BATCH_TURN_INTERVAL
    from db.profile import get_subject_metrics
    from db.auth import get_student
    from db.memory import update_session_remark, update_student_memory, get_student_memory

    db = SessionLocal()
    try:
        # Fetch student to get class_num
        student = get_student(db, request.student_id)
        class_num = student.class_num if student else 10

        # ── 1. Session + memory ───────────────────────────────────────────────────
        session_id = get_or_create_session(
            student_id=request.student_id,
            session_id=request.session_id,
            class_num=class_num,
            subject=request.subject,
        )
        memory_summary, recent_history = get_history(session_id)

        logger.info(
            f"Session {session_id[:8]}... | "
            f"Memory: {len(memory_summary)} chars | "
            f"Recent: {len(recent_history)} messages"
        )

        # Load metrics and compute cognitive skills (no LLM pre-gen call)
        metrics = get_subject_metrics(db, request.student_id, request.subject)
        cognitive_skills = compute_cognitive_skills(metrics)
        student_memory = get_student_memory(request.student_id, request.subject)
    finally:
        db.close()

    # ── 3. Classify via zero-token heuristic ──────────────────────────────────
    is_conv = _heuristic_is_conversational(request.question)
    question_type = "conversational" if is_conv else "curriculum"
    logger.info(f"Question heuristically classified as: '{question_type}'")

    # ── 4. Route by classification ────────────────────────────────────────────
    context = ""
    sources: list[SourceInfo] = []
    raw_chunks: list[dict] = []
    route: dict | None = None
    is_grounded = False

    if question_type == "conversational":
        # Pure conversational — no pgvector, answer from history
        logger.info("Mode: conversational (no retrieval)")

    else:
        # Curriculum question — retrieve with confidence gate
        logger.info("Mode: curriculum (pgvector retrieval)")
        context, sources, raw_chunks, route = _retrieve_with_confidence(
            request.question, 
            class_num=class_num, 
            subject=request.subject
        )
        is_grounded = bool(context)

        if not is_grounded:
            # No confident chunks found — fallback to a normal LLM response
            logger.info("No confident chunks found, falling back to conversational mode.")
            question_type = "conversational"

    # ── 5. Generate (personalized via metrics & cognitive skills) ─────────────
    tutor = _get_tutor()
    answer, prompt_messages = tutor.generate(
        question=request.question,
        context=context,
        history=recent_history,
        memory_summary=memory_summary,
        question_type=question_type,
        is_grounded=is_grounded,
        class_num=class_num,
        subject=request.subject,
        metrics=metrics,
        cognitive_skills=cognitive_skills,
        student_memory=student_memory,
    )

    # ── 6. Persist turn ───────────────────────────────────────────────────────
    routed_topic = sources[0].topic if sources else (route.get("topic", "") if route else "")
    total_messages = save_turn(
        session_id=session_id,
        question=request.question,
        answer=answer,
        context_used=context[:500] if context else "",
        routed_topic=routed_topic,
    )
    turn_count = total_messages // 2  # 2 messages per turn (student + tutor)

    # ── 7. Post-turn: algorithmic signal collection + batch trigger ───────────
    metrics_adjustments = {}
    signal = collect_turn_signals(
        question=request.question,
        answer=answer,
        history=recent_history,
        turn_number=turn_count,
    )
    db2 = SessionLocal()
    try:
        append_pending_signal(db2, request.student_id, request.subject, signal)

        # Every BATCH_TURN_INTERVAL turns → run holistic LLM cognitive update
        if turn_count > 0 and turn_count % BATCH_TURN_INTERVAL == 0:
            logger.info(f"Batch trigger at turn {turn_count} — running cognitive batch update.")
            metrics_adjustments, remark = batch_update_cognitive_profile(
                student_id=request.student_id,
                subject=request.subject,
                db=db2,
            )
            # Reload updated metrics and skills
            metrics = get_subject_metrics(db2, request.student_id, request.subject)
            cognitive_skills = compute_cognitive_skills(metrics)

            if remark:
                update_session_remark(session_id, remark)
                recent_turns_text = "\n".join(
                    f"{m.role}: {m.content[:200]}" for m in recent_history
                )
                update_student_memory(request.student_id, request.subject, remark, recent_turns_text)
    finally:
        db2.close()

    # ── 8. Return ─────────────────────────────────────────────────────────────
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
        metrics=metrics,
        metrics_adjustments=metrics_adjustments,
        cognitive_skills=cognitive_skills,
    )

