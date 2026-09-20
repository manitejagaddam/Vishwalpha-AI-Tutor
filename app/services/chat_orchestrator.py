"""
app/services/chat_orchestrator.py
───────────────────────────────────
Main chat pipeline: routes, retrieves, classifies, generates, and persists.

Flow:
  1. Load session / create if new
  2. Load conversation history + student memory
  3. Classify question: conversational vs. curriculum
  4. If curriculum → route via VectorRouter → retrieve from pgvector
  5. Generate response via TutorLLM (correct mode)
  6. Persist turn + update cognitive signals (batched)
  7. Update topic mastery, streaks, and analytics
  8. Return ChatResponse

Two execution modes
────────────────────
  chat()        — blocking (used by sync fallback & tests)
  chat_stream() — async generator yielding SSE-compatible text chunks
                  used by the /chat/stream endpoint for real-time streaming

Enhanced with:
  - Topic mastery awareness (weak/strong topics injected into prompt)
  - Learning preference injection
  - Per-message analytics (response_time, sentiment, bloom_level)
  - Student streak updates
  - Spaced repetition review detection
  - Single metrics DB query per request (was two)
"""
import time
import logging
import asyncio
from typing import AsyncGenerator

from app.schemas import ChatRequest, ChatResponse, SourceInfo, QuizSuggestion, YesterdayContext
from app.data.session_repo import (
    get_or_create_session,
    get_history,
    get_full_history,
    save_turn,
    is_new_session,
    update_session_remark,
    update_student_memory,
    get_student_memory,
    get_student_tasks,
    update_session_mood,
    end_session,
)
from app.data.quiz_repo import (
    get_yesterday_session_context,
    update_session_topic,
)
from app.data.database import managed_session
from app.data.models import Student
from app.data.auth_repo import get_student
from app.data.cognitive_repo import (
    get_subject_metrics,
    get_full_subject_profile,
    compute_cognitive_skills,
    collect_turn_signals,
    detect_bloom_level,
    detect_sentiment,
    append_pending_signal,
    batch_update_cognitive_profile,
    increment_chat_turns,
    update_student_streak,
    increment_streak_questions,
    update_topic_mastery_from_chat,
    get_student_weak_topics,
    get_topics_due_for_review,
    get_learning_preferences,
    BATCH_TURN_INTERVAL,
)
from app.services.tutor_llm import TutorLLM
from app.services.question_classifier import is_conversational
from app.services.retrieval_service import retrieve_with_confidence
from app.services.quiz_service import detect_concept_completion
from app.infra.vector_router import VectorRouter

logger = logging.getLogger(__name__)

# ── Module-level singletons (one per process) ─────────────────────────────────
_tutor_llm: TutorLLM | None = None
_vector_router: VectorRouter | None = None


def _get_llm() -> TutorLLM:
    global _tutor_llm
    if _tutor_llm is None:
        _tutor_llm = TutorLLM()
    return _tutor_llm


def _get_router() -> VectorRouter:
    global _vector_router
    if _vector_router is None:
        _vector_router = VectorRouter()
    return _vector_router


def _resolve_topic_id(routed_topic: str, class_num: int | None, subject: str | None) -> int | None:
    """Attempts to resolve a topic name to a topic_id from the topics table."""
    if not routed_topic:
        return None
    try:
        from app.data.models import Topic
        from sqlalchemy import func
        with managed_session() as db:
            query = db.query(Topic).filter(
                func.lower(Topic.title) == routed_topic.lower()
            )
            topic = query.first()
            return topic.id if topic else None
    except Exception:
        return None


# ── Shared pre-generation setup ────────────────────────────────────────────────

def _build_pipeline_context(request: ChatRequest, student: Student) -> dict:
    """
    Gathers all data needed before LLM generation:
    session, history, memory, weak topics, routing, retrieval.
    Returns a dict of everything the generator function needs.
    Extracted to avoid duplicating logic between chat() and chat_stream().
    """
    class_num = request.class_num or (student.class_num if student else None)

    session_id = get_or_create_session(
        student_id=student.id,
        session_id=request.session_id,
        class_num=class_num,
        subject=request.subject,
    )

    new_session = is_new_session(session_id)
    memory_summary, history = get_history(session_id)

    # ── Yesterday context + spaced repetition reviews ─────────────────────────
    yesterday_ctx: YesterdayContext | None = None
    review_topics: list[dict] = []
    if new_session:
        ctx = get_yesterday_session_context(student.id)
        if ctx:
            yesterday_ctx = YesterdayContext(
                subject=ctx["subject"],
                topic=ctx["topic"],
                session_date=ctx["session_date"],
            )
        try:
            review_topics = get_topics_due_for_review(student.id)
        except Exception as e:
            logger.warning(f"Spaced repetition check failed: {e}")

    # ── Streak ────────────────────────────────────────────────────────────────
    try:
        update_student_streak(student.id)
        increment_streak_questions(student.id)
    except Exception as e:
        logger.warning(f"Streak update failed: {e}")

    # ── Student memory + learning preferences ─────────────────────────────────
    memory_items = get_student_memory(student.id, request.subject)
    student_memory_str = (
        "\n".join(f"- {m}" for m in memory_items)
        if memory_items else "(no memory yet)"
    )
    learning_prefs = get_learning_preferences(student.id)

    # ── Weak topics ───────────────────────────────────────────────────────────
    weak_topics_str = ""
    try:
        weak_topics = get_student_weak_topics(student.id, request.subject)
        if weak_topics:
            weak_topics_str = "\n".join(
                f"- {t['topic_title']} (mastery: {t['mastery_level']:.0f}%)"
                for t in weak_topics[:5]
            )
    except Exception as e:
        logger.warning(f"Weak topics fetch failed: {e}")

    # ── Question classification ───────────────────────────────────────────────
    llm = _get_llm()
    if is_conversational(request.question):
        question_type = "conversational"
    else:
        question_type = llm.classify_question(request.question, history)

    # ── Per-message analytics ─────────────────────────────────────────────────
    student_sentiment = detect_sentiment(request.question)
    student_bloom     = detect_bloom_level(request.question)
    contains_question = "?" in request.question

    # ── Retrieval (curriculum only) ───────────────────────────────────────────
    context         = ""
    sources: list[SourceInfo] = []
    routed_chapter  = ""
    routed_topic    = ""
    generation_mode = "conversational"
    confident_chunks: list[dict] = []

    if question_type == "curriculum":
        router = _get_router()
        route = router.route_query(
            request.question, class_num=class_num, subject=request.subject
        )
        if route:
            routed_chapter = route.get("chapter", "")
            routed_topic   = route.get("topic", "")
            context, confident_chunks = retrieve_with_confidence(
                question=request.question,
                routing_metadata=route,
            )
            if context:
                generation_mode = "curriculum"
                seen: set[tuple] = set()
                for chunk in confident_chunks:
                    meta = chunk.get("metadata", {})
                    key = (meta.get("chapter", ""), meta.get("topic", ""))
                    if key not in seen:
                        seen.add(key)
                        sources.append(SourceInfo(
                            chapter=meta.get("chapter", ""),
                            topic=meta.get("topic", ""),
                            score=round(chunk.get("score", 0), 2),
                        ))
            else:
                logger.info("No confident chunks → switching to open_curriculum mode")
                generation_mode = "open_curriculum"
        else:
            logger.info("Router found no route → open_curriculum mode")
            generation_mode = "open_curriculum"

    return {
        "session_id":       session_id,
        "new_session":      new_session,
        "history":          history,
        "class_num":        class_num,
        "student_memory_str": student_memory_str,
        "learning_prefs":   learning_prefs,
        "weak_topics_str":  weak_topics_str,
        "review_topics":    review_topics,
        "yesterday_ctx":    yesterday_ctx,
        "question_type":    question_type,
        "generation_mode":  generation_mode,
        "context":          context,
        "sources":          sources,
        "routed_chapter":   routed_chapter,
        "routed_topic":     routed_topic,
        "student_sentiment": student_sentiment,
        "student_bloom":    student_bloom,
        "contains_question": contains_question,
    }


def _post_generation_pipeline(
    request: ChatRequest,
    student: Student,
    ctx: dict,
    answer: str,
    response_time_ms: int,
) -> tuple[dict, dict, dict, int, list[str], QuizSuggestion | None]:
    """
    Everything after the LLM has returned an answer:
    persist, update metrics, return (metrics, metrics_adjustments, cognitive_skills, turn_count, tasks, quiz_suggestion).
    Extracted so both chat() and chat_stream() share identical post-processing.
    """
    llm           = _get_llm()
    session_id    = ctx["session_id"]
    new_session   = ctx["new_session"]
    routed_topic  = ctx["routed_topic"]
    generation_mode = ctx["generation_mode"]
    student_sentiment = ctx["student_sentiment"]
    student_bloom   = ctx["student_bloom"]
    contains_question = ctx["contains_question"]
    class_num       = ctx["class_num"]

    # ── Generate title for new sessions (background) ──────────────────────────
    if new_session:
        import threading
        from app.data.session_repo import update_session_title
        def _gen_title(sid: str, msg: str):
            try:
                title = llm.generate_chat_title(msg)
                if title:
                    update_session_title(sid, title)
            except Exception as e:
                logger.error(f"Failed background title generation: {e}")
        threading.Thread(
            target=_gen_title, args=(session_id, request.question), daemon=True
        ).start()

    # ── Track routed topic in session ─────────────────────────────────────────
    topic_id = None
    if routed_topic:
        try:
            update_session_topic(session_id, routed_topic)
            topic_id = _resolve_topic_id(routed_topic, class_num, request.subject)
        except Exception as e:
            logger.warning(f"Failed to update session topic: {e}")

    # ── Concept completion → quiz suggestion ──────────────────────────────────
    quiz_suggestion_obj: QuizSuggestion | None = None
    if generation_mode == "curriculum" and routed_topic:
        try:
            is_complete, topic_name = detect_concept_completion(answer, routed_topic)
            if is_complete:
                quiz_suggestion_obj = QuizSuggestion(
                    topic=topic_name or routed_topic,
                    subject=request.subject,
                    num_questions=7,
                )
        except Exception as e:
            logger.warning(f"Concept completion detection failed: {e}")

    # ── Persist turn ──────────────────────────────────────────────────────────
    save_turn(
        session_id=session_id,
        student_msg=request.question,
        tutor_msg=answer,
        response_time_ms=response_time_ms,
        student_sentiment=student_sentiment,
        student_bloom=student_bloom,
        student_contains_question=contains_question,
        routed_topic=routed_topic,
        topic_id=topic_id,
    )

    # ── Session mood ──────────────────────────────────────────────────────────
    try:
        if student_sentiment in ("frustrated", "confused"):
            update_session_mood(session_id, student_sentiment)
    except Exception as e:
        logger.warning(f"Session mood update failed: {e}")

    # ── Cognitive signals (collect once, query metrics once) ──────────────────
    with managed_session() as db:
        metrics = get_subject_metrics(db, student.id, request.subject)
        cognitive_skills = compute_cognitive_skills(metrics)

    signals = collect_turn_signals(
        question=request.question,
        answer=answer,
        question_type=generation_mode,
        metrics=metrics,
    )
    append_pending_signal(student.id, request.subject, session_id, signals)

    try:
        increment_chat_turns(student.id, request.subject)
    except Exception as e:
        logger.warning(f"Chat turn increment failed: {e}")

    # ── Topic mastery ─────────────────────────────────────────────────────────
    if topic_id and generation_mode == "curriculum":
        try:
            update_topic_mastery_from_chat(student.id, topic_id, student_bloom)
        except Exception as e:
            logger.warning(f"Topic mastery update failed: {e}")

    # ── Batch update every N turns ────────────────────────────────────────────
    from app.data.session_repo import get_session_message_count
    turn_count = get_session_message_count(session_id)
    metrics_adjustments: dict = {}
    if turn_count % BATCH_TURN_INTERVAL == 0:
        metrics_adjustments = batch_update_cognitive_profile(
            student.id, request.subject, session_id
        )
        context_snippet = request.question[:200] + " → " + answer[:200]
        remark = llm.generate_remark(context_snippet)
        if remark:
            update_session_remark(session_id, remark)
            update_student_memory(student.id, request.subject, remark, context_snippet)

    pending_tasks = get_student_tasks(student.id, request.subject)

    return metrics, metrics_adjustments, cognitive_skills, turn_count, pending_tasks, quiz_suggestion_obj


# ── Main orchestrator (blocking — for tests / sync callers) ───────────────────

def chat(request: ChatRequest, student: Student) -> ChatResponse:
    """
    Full chat pipeline. Returns a ChatResponse ready for JSON serialisation.
    student is the authenticated Student ORM object (resolved from JWT in the route).
    """
    ctx = _build_pipeline_context(request, student)
    llm = _get_llm()

    gen_start = time.time()
    answer, _ = llm.generate(
        mode=ctx["generation_mode"],
        question=request.question,
        history=ctx["history"],
        context=ctx["context"],
        student_memory=ctx["student_memory_str"],
        learning_preferences=ctx["learning_prefs"],
        weak_topics=ctx["weak_topics_str"],
        review_topics=ctx["review_topics"] if ctx["new_session"] else [],
    )
    response_time_ms = int((time.time() - gen_start) * 1000)

    metrics, metrics_adjustments, cognitive_skills, turn_count, pending_tasks, quiz_suggestion_obj = (
        _post_generation_pipeline(request, student, ctx, answer, response_time_ms)
    )

    return ChatResponse(
        session_id=ctx["session_id"],
        answer=answer,
        sources=ctx["sources"],
        conversation_length=turn_count,
        routed_chapter=ctx["routed_chapter"],
        routed_topic=ctx["routed_topic"],
        question_type=ctx["generation_mode"],
        metrics=metrics,
        metrics_adjustments=metrics_adjustments,
        cognitive_skills=cognitive_skills,
        is_session_start=ctx["new_session"],
        pending_tasks=pending_tasks,
        quiz_suggestion=quiz_suggestion_obj,
        yesterday_context=ctx["yesterday_ctx"],
    )


# ── Streaming orchestrator (async generator) ──────────────────────────────────

async def chat_stream(
    request: ChatRequest, student: Student
) -> AsyncGenerator[str, None]:
    """
    Async generator that yields Server-Sent Events (SSE) text chunks.

    SSE event format:
        data: <json_chunk>\n\n

    Chunk types:
        {"type": "meta",  "session_id": "...", "is_session_start": ...}
        {"type": "token", "content": "..."}          ← streamed tokens
        {"type": "done",  "sources": [...], ...}      ← final metadata

    The frontend reads the stream and progressively renders tokens.
    """
    import json as _json
    from app.infra.azure_openai_client import get_openai
    from app.config import settings

    # ── Build context (runs sync DB calls in a thread pool) ───────────────────
    ctx = await asyncio.to_thread(_build_pipeline_context, request, student)

    llm = _get_llm()

    # ── Emit meta event first so frontend knows session_id immediately ────────
    yield f"data: {_json.dumps({'type': 'meta', 'session_id': ctx['session_id'], 'is_session_start': ctx['new_session']})}\n\n"

    # ── Build messages list (same as TutorLLM.generate but streaming) ────────
    from app.services.tutor_llm import (
        _CURRICULUM_PROMPT, _OPEN_CURRICULUM_PROMPT, _CONVERSATIONAL_PROMPT,
        _build_teaching_style, _build_weak_topics_section, _build_review_section,
    )
    system_map = {
        "curriculum":      _CURRICULUM_PROMPT,
        "open_curriculum": _OPEN_CURRICULUM_PROMPT,
        "conversational":  _CONVERSATIONAL_PROMPT,
    }
    teaching_style = _build_teaching_style(ctx["learning_prefs"] or {})
    weak_section   = _build_weak_topics_section(ctx["weak_topics_str"])
    review_section = _build_review_section(
        ctx["review_topics"] if ctx["new_session"] else []
    )

    mode = ctx["generation_mode"]
    if mode == "curriculum":
        system_content = _CURRICULUM_PROMPT.format(
            context=ctx["context"] or "(no additional context)",
            student_memory=ctx["student_memory_str"] or "(no memory yet)",
            teaching_style=teaching_style,
            weak_topics_section=weak_section,
            review_section=review_section,
        )
        temp, max_tok = 0.3, 1500
    elif mode == "open_curriculum":
        system_content = _OPEN_CURRICULUM_PROMPT.format(
            student_memory=ctx["student_memory_str"] or "(no memory yet)",
            teaching_style=teaching_style,
            weak_topics_section=weak_section,
            review_section=review_section,
        )
        temp, max_tok = 0.5, 2000
    else:  # conversational
        system_content = _CONVERSATIONAL_PROMPT.format(
            student_memory=ctx["student_memory_str"] or "(no memory yet)",
            teaching_style=teaching_style,
        )
        temp, max_tok = 0.7, 400

    messages = [{"role": "system", "content": system_content}]
    for msg in ctx["history"]:
        messages.append({
            "role": "user" if msg.role == "student" else "assistant",
            "content": msg.content,
        })
    messages.append({"role": "user", "content": request.question})

    # ── Stream tokens from Azure OpenAI ──────────────────────────────────────
    client  = get_openai()
    full_answer = []
    gen_start   = time.time()

    try:
        stream = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                messages=messages,
                model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                temperature=temp,
                max_completion_tokens=max_tok,
                stream=True,
            )
        )
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                token = delta.content
                full_answer.append(token)
                yield f"data: {_json.dumps({'type': 'token', 'content': token})}\n\n"
    except Exception as exc:
        logger.error(f"Streaming error: {exc}")
        yield f"data: {_json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"
        return

    response_time_ms = int((time.time() - gen_start) * 1000)
    answer = "".join(full_answer)

    # ── Post-generation (persist, metrics, etc.) in a thread ─────────────────
    (
        metrics, metrics_adjustments, cognitive_skills,
        turn_count, pending_tasks, quiz_suggestion_obj,
    ) = await asyncio.to_thread(
        _post_generation_pipeline, request, student, ctx, answer, response_time_ms
    )

    # ── Final done event ──────────────────────────────────────────────────────
    done_payload = {
        "type": "done",
        "sources": [s.model_dump() for s in ctx["sources"]],
        "routed_chapter":   ctx["routed_chapter"],
        "routed_topic":     ctx["routed_topic"],
        "question_type":    ctx["generation_mode"],
        "metrics":          metrics,
        "metrics_adjustments": metrics_adjustments,
        "cognitive_skills": cognitive_skills,
        "conversation_length": turn_count,
        "pending_tasks":    pending_tasks,
        "quiz_suggestion":  quiz_suggestion_obj.model_dump() if quiz_suggestion_obj else None,
        "yesterday_context": ctx["yesterday_ctx"].model_dump() if ctx["yesterday_ctx"] else None,
    }
    yield f"data: {_json.dumps(done_payload)}\n\n"
