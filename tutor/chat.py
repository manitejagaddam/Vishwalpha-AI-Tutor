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
from schemas import ChatRequest, ChatResponse, SourceInfo
from db.memory import get_or_create_session, get_history, save_turn, update_session_remark, update_student_memory, get_student_memory
from tutor.llm import TutorLLM
from tutor.patterns import heuristic_is_conversational
from core.db_session import managed_session
from routing.router import SemanticRouter
from retrieval.engine import RetrievalEngine
from retrieval.reranker import Reranker
from db.metrics import collect_turn_signals, append_pending_signal, batch_update_cognitive_profile, compute_cognitive_skills, BATCH_TURN_INTERVAL
from db.profile import get_subject_metrics
from db.auth import get_student
from db.memory import (
    get_diagnostic_state, set_diagnostic_state,
    is_new_session,
    get_student_tasks,
)
from tutor.socratic import SocraticTutor

logger = logging.getLogger(__name__)

RETRIEVAL_CONFIDENCE_THRESHOLD = 0.60

_tutor_llm: TutorLLM | None = None
_socratic_tutor: SocraticTutor | None = None

def _get_tutor() -> TutorLLM:
    """Returns a singleton instance of the TutorLLM."""
    global _tutor_llm
    if _tutor_llm is None:
        _tutor_llm = TutorLLM()
    return _tutor_llm

def _get_socratic() -> SocraticTutor:
    """Returns a singleton instance of the SocraticTutor."""
    global _socratic_tutor
    if _socratic_tutor is None:
        _socratic_tutor = SocraticTutor()
    return _socratic_tutor

def _retrieve_with_confidence(
    question: str,
    class_num: int = None,
    subject: str = None
) -> tuple[str, list[SourceInfo], list[dict], dict | None, "RetrievalEngine"]:
    """
    Retrieves pgvector chunks and filters out low-confidence results.
    Phase 1 fix: class_num and subject are passed INTO route_query() as pre-filters
    BEFORE cosine similarity sorting — not patched on after the fact.
    Returns: (context, sources, raw_chunks, route, engine)
    The engine is returned so callers can pass it to Socratic backtracking.
    """
    router = SemanticRouter()
    # Phase 1.6 fix: pass class_num + subject as pre-filters into the router
    route = router.route_query(question, class_num=class_num, subject=subject)

    engine = RetrievalEngine()

    if not route:
        logger.info("Classifier→curriculum, but router found no matching topic.")
        return "", [], [], None, engine

    logger.info(
        f"Routed → Class {route.get('class')} | {route.get('subject')} | "
        f"{route.get('chapter')} | {route.get('topic')}"
    )

    raw_chunks = engine.retrieve(question, route, top_k=5)

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
        return "", [], raw_chunks, route, engine

    logger.info(
        f"Confidence gate: {len(confident_chunks)}/{len(raw_chunks)} chunks passed "
        f"(threshold={RETRIEVAL_CONFIDENCE_THRESHOLD})"
    )

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

    reranker = Reranker()
    context = reranker.compress_context(confident_chunks)

    return context, sources, raw_chunks, route, engine

def chat(request: ChatRequest) -> ChatResponse:
    """
    Agent-style chat flow:
      1. Get/create session + load conversation memory
      2. [Session Start] If new session, generate a warm opener (both modes)
      3. Classify question: "curriculum" or "conversational"
      4a. [standard]         → retrieve + TutorLLM.generate() (unchanged)
      4b. [deep, phase 1]    → retrieve + SocraticTutor.start_diagnostic() → return diagnostic question
      4c. [deep, phase 2]    → SocraticTutor.evaluate_and_explain() → return adaptive explanation
      5. Persist turn to PostgreSQL
      6. Return ChatResponse
    """
    with managed_session() as db:
        # Phase 1.5: honour class_num from request if provided, else resolve from DB
        if request.class_num is not None:
            class_num = request.class_num
        else:
            student = get_student(db, request.student_id)
            class_num = student.class_num if student else 10  # default to Class 10

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

        metrics = get_subject_metrics(db, request.student_id, request.subject)
        cognitive_skills = compute_cognitive_skills(metrics)
        student_memory = get_student_memory(request.student_id, request.subject)
        tasks = get_student_tasks(request.student_id, request.subject)

    # ── Session start logic removed — handled statically by UI now ───────────    # ── Deep mode — Phase 2: student answered the diagnostic ─────────────────
    if request.tutor_mode == "deep":
        diagnostic_state = get_diagnostic_state(session_id)
        if diagnostic_state and diagnostic_state.get("phase") == "awaiting_response":
            logger.info("Deep mode Phase 2: evaluating diagnostic response.")
            socratic = _get_socratic()
            # Pass a RetrievalEngine so Phase 2 can fetch lower-class backtrack content
            _engine_for_backtrack = RetrievalEngine()
            answer = socratic.evaluate_and_explain(
                student_response=request.question,
                state=diagnostic_state,
                metrics=metrics,
                history=recent_history,
                engine=_engine_for_backtrack,
            )
            # Check if backtracking happened — if so keep updated state alive
            from tutor.patterns import detect_understanding, detect_give_up
            _und = detect_understanding(request.question, diagnostic_state.get("expected_keywords", []))
            _gave_up = detect_give_up(request.question)
            _depth = diagnostic_state.get("backtrack_depth", 0)
            _should_clear = (
                _gave_up
                or _und >= 0.50
                or _depth >= 3
                or not diagnostic_state.get("prereq_description")
            )
            if _should_clear:
                set_diagnostic_state(session_id, None)  # Clear — session resolved
            else:
                # Update state for continued backtracking next turn
                _new_state = {
                    **diagnostic_state,
                    "backtrack_depth": _depth + 1,
                    "visited_topics": diagnostic_state.get("visited_topics", []) + [
                        diagnostic_state.get("prereq_description", "")
                    ],
                    "phase": "awaiting_response",
                }
                set_diagnostic_state(session_id, _new_state)
            total_messages = save_turn(
                session_id=session_id,
                question=request.question,
                answer=answer,
                routed_topic=diagnostic_state.get("topic", ""),
            )
            turn_count = total_messages // 2
            metrics_adjustments = {}
            remark = ""
            signal = collect_turn_signals(
                question=request.question,
                answer=answer,
                history=recent_history,
                turn_number=turn_count,
            )
            with managed_session() as db2:
                append_pending_signal(db2, request.student_id, request.subject, signal)
                db2.commit()
                if turn_count > 0 and turn_count % BATCH_TURN_INTERVAL == 0:
                    metrics_adjustments, remark = batch_update_cognitive_profile(
                        student_id=request.student_id, subject=request.subject, db=db2,
                    )
                    metrics = get_subject_metrics(db2, request.student_id, request.subject)
                    cognitive_skills = compute_cognitive_skills(metrics)
                    if remark:
                        update_session_remark(session_id, remark)
                        recent_turns_text = "\n".join(
                            f"{m.role}: {m.content[:200]}" for m in recent_history
                        )
                        update_student_memory(request.student_id, request.subject, remark, recent_turns_text)
            return ChatResponse(
                session_id=session_id,
                answer=answer,
                sources=[],
                conversation_length=total_messages,
                routed_chapter=diagnostic_state.get("chapter", ""),
                routed_topic=diagnostic_state.get("topic", ""),
                question_type="deep_explanation",
                metrics=metrics,
                metrics_adjustments=metrics_adjustments,
                cognitive_skills=cognitive_skills,
                pending_tasks=tasks,
            )

    # ── Standard retrieval path (shared by standard mode + deep Phase 1) ─────
    is_conv = heuristic_is_conversational(request.question)
    question_type = "conversational" if is_conv else "curriculum"
    logger.info(f"Question heuristically classified as: '{question_type}'")

    context = ""
    sources: list[SourceInfo] = []
    raw_chunks: list[dict] = []
    route: dict | None = None
    is_grounded = False

    if question_type == "conversational":
        logger.info("Mode: conversational (no retrieval)")
    else:
        logger.info("Mode: curriculum (pgvector retrieval)")
        context, sources, raw_chunks, route, _ret_engine = _retrieve_with_confidence(
            request.question,
            class_num=class_num,
            subject=request.subject
        )
        is_grounded = bool(context)

        if not is_grounded:
            logger.info("No confident chunks found, falling back to conversational mode.")
            question_type = "conversational"

    # ── Deep mode — Phase 1: generate diagnostic question ─────────────────────
    if request.tutor_mode == "deep" and question_type == "curriculum" and is_grounded:
        logger.info("Deep mode Phase 1: starting Socratic diagnostic.")
        topic = sources[0].topic if sources else (route.get("topic", "") if route else "")
        chapter = sources[0].chapter if sources else (route.get("chapter", "") if route else "")
        socratic = _get_socratic()
        diag_question, state = socratic.start_diagnostic(
            question=request.question,
            topic=topic,
            chapter=chapter,
            class_num=class_num,
            subject=request.subject,
            context=context,
            metrics=metrics,
        )
        set_diagnostic_state(session_id, state)
        total_messages = save_turn(
            session_id=session_id,
            question=request.question,
            answer=diag_question,
            context_used=context[:500],
            routed_topic=topic,
        )
        return ChatResponse(
            session_id=session_id,
            answer=diag_question,
            sources=sources,
            conversation_length=total_messages,
            routed_chapter=chapter,
            routed_topic=topic,
            question_type="deep_diagnostic",
            metrics=metrics,
            cognitive_skills=cognitive_skills,
            diagnostic_question=diag_question,
            pending_tasks=tasks,
        )

    # ── Standard generation ───────────────────────────────────────────────────
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
        student_id=request.student_id,
        session_id=session_id,
    )

    routed_topic = sources[0].topic if sources else (route.get("topic", "") if route else "")
    total_messages = save_turn(
        session_id=session_id,
        question=request.question,
        answer=answer,
        context_used=context[:500] if context else "",
        routed_topic=routed_topic,
    )
    turn_count = total_messages // 2

    metrics_adjustments = {}
    remark = ""
    signal = collect_turn_signals(
        question=request.question,
        answer=answer,
        history=recent_history,
        turn_number=turn_count,
    )

    with managed_session() as db2:
        append_pending_signal(db2, request.student_id, request.subject, signal)
        db2.commit()

        logger.info(f"Turn #{turn_count} signal appended. Batch trigger every {BATCH_TURN_INTERVAL} turns.")

        if turn_count > 0 and turn_count % BATCH_TURN_INTERVAL == 0:
            logger.info(f"=== Batch cognitive update triggered at turn {turn_count} ===")
            metrics_adjustments, remark = batch_update_cognitive_profile(
                student_id=request.student_id,
                subject=request.subject,
                db=db2,
            )
            metrics = get_subject_metrics(db2, request.student_id, request.subject)
            cognitive_skills = compute_cognitive_skills(metrics)
            logger.info(f"Updated metrics: {metrics}")

            if remark:
                update_session_remark(session_id, remark)
                recent_turns_text = "\n".join(
                    f"{m.role}: {m.content[:200]}" for m in recent_history
                )
                update_student_memory(request.student_id, request.subject, remark, recent_turns_text)

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
        pending_tasks=tasks,
    )
