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

Enhanced with:
  - Topic mastery awareness (weak/strong topics injected into prompt)
  - Learning preference injection
  - Per-message analytics (response_time, sentiment, bloom_level)
  - Student streak updates
  - Spaced repetition review detection
"""
import time
import logging

from app.schemas import ChatRequest, ChatResponse, SourceInfo, QuizSuggestion, YesterdayContext
from app.data.session_repo import (
    get_or_create_session,
    get_history,
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
        from app.data.models import Topic, Chapter, Subject as SubjectModel
        from sqlalchemy import func
        with managed_session() as db:
            query = db.query(Topic).filter(
                func.lower(Topic.title) == routed_topic.lower()
            )
            topic = query.first()
            return topic.id if topic else None
    except Exception:
        return None


# ── Main orchestrator ─────────────────────────────────────────────────────────

def chat(request: ChatRequest) -> ChatResponse:
    """
    Full chat pipeline. Returns a ChatResponse ready for JSON serialisation.
    """
    llm = _get_llm()
    router = _get_router()

    # ── Step 1: Student profile + session ─────────────────────────────────────
    with managed_session() as db:
        student = get_student(db, request.student_id)
        student_class_num = student.class_num if student else None

    class_num = request.class_num
    if not class_num and student_class_num:
        class_num = student_class_num

    session_id = get_or_create_session(
        student_id=request.student_id,
        session_id=request.session_id,
        class_num=class_num,
        subject=request.subject,
    )

    new_session = is_new_session(session_id)
    memory_summary, history = get_history(session_id)

    # ── Step 1b: Yesterday context + spaced repetition reviews ────────────────
    yesterday_ctx: YesterdayContext | None = None
    review_topics: list[dict] = []
    if new_session:
        ctx = get_yesterday_session_context(request.student_id)
        if ctx:
            yesterday_ctx = YesterdayContext(
                subject=ctx["subject"],
                topic=ctx["topic"],
                session_date=ctx["session_date"],
            )
        # Check for spaced repetition reviews due
        try:
            review_topics = get_topics_due_for_review(request.student_id)
        except Exception as e:
            logger.warning(f"Spaced repetition check failed: {e}")

    # ── Step 1c: Update streak on activity ────────────────────────────────────
    try:
        streak_info = update_student_streak(request.student_id)
        increment_streak_questions(request.student_id)
    except Exception as e:
        logger.warning(f"Streak update failed: {e}")
        streak_info = {}

    # ── Step 2: Student memory + learning preferences ─────────────────────────
    memory_items = get_student_memory(request.student_id, request.subject)
    student_memory_str = (
        "\n".join(f"- {m}" for m in memory_items)
        if memory_items else "(no memory yet)"
    )

    learning_prefs = get_learning_preferences(request.student_id)

    # ── Step 2b: Weak topics awareness ────────────────────────────────────────
    weak_topics_str = ""
    try:
        weak_topics = get_student_weak_topics(request.student_id, request.subject)
        if weak_topics:
            weak_topics_str = "\n".join(
                f"- {t['topic_title']} (mastery: {t['mastery_level']:.0f}%)"
                for t in weak_topics[:5]
            )
    except Exception as e:
        logger.warning(f"Weak topics fetch failed: {e}")

    # ── Step 3: Classify the question ─────────────────────────────────────────
    if is_conversational(request.question):
        question_type = "conversational"
    else:
        # LLM-based classifier as fallback for edge cases
        question_type = llm.classify_question(request.question, history)

    # ── Step 3b: Detect sentiment and bloom level ─────────────────────────────
    student_sentiment = detect_sentiment(request.question)
    student_bloom = detect_bloom_level(request.question)
    contains_question = "?" in request.question

    # ── Step 4: Retrieval (curriculum only) ───────────────────────────────────
    context = ""
    sources: list[SourceInfo] = []
    routed_chapter = ""
    routed_topic   = ""
    generation_mode = "conversational"

    if question_type == "curriculum":
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
                # Build source list (deduplicated by chapter+topic)
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

    # ── Step 5: Generate response ─────────────────────────────────────────────
    gen_start = time.time()
    answer, prompt_messages = llm.generate(
        mode=generation_mode,
        question=request.question,
        history=history,
        context=context,
        student_memory=student_memory_str,
        learning_preferences=learning_prefs,
        weak_topics=weak_topics_str,
        review_topics=review_topics if new_session else [],
    )
    response_time_ms = int((time.time() - gen_start) * 1000)

    # ── Step 5b: Track routed topic in session ────────────────────────────────
    topic_id = None
    if routed_topic:
        try:
            update_session_topic(session_id, routed_topic)
            topic_id = _resolve_topic_id(routed_topic, class_num, request.subject)
        except Exception as e:
            logger.warning(f"Failed to update session topic: {e}")

    # ── Step 5c: Detect concept completion → quiz suggestion ──────────────────
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

    # ── Step 6: Persist turn with analytics ───────────────────────────────────
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

    # ── Step 6b: Update session mood based on sentiment ───────────────────────
    try:
        if student_sentiment in ("frustrated", "confused"):
            update_session_mood(session_id, student_sentiment)
    except Exception as e:
        logger.warning(f"Session mood update failed: {e}")

    # ── Step 7: Cognitive signals (batched) ───────────────────────────────────
    with managed_session() as db:
        metrics = get_subject_metrics(db, request.student_id, request.subject)

    signals = collect_turn_signals(
        question=request.question,
        answer=answer,
        question_type=generation_mode,
        metrics=metrics,
    )
    append_pending_signal(request.student_id, request.subject, session_id, signals)

    # Increment chat turn counter
    try:
        increment_chat_turns(request.student_id, request.subject)
    except Exception as e:
        logger.warning(f"Chat turn increment failed: {e}")

    # ── Step 7b: Update topic mastery from chat ───────────────────────────────
    if topic_id and generation_mode == "curriculum":
        try:
            update_topic_mastery_from_chat(request.student_id, topic_id, student_bloom)
        except Exception as e:
            logger.warning(f"Topic mastery update failed: {e}")

    # ── Step 7c: Batch update on interval ─────────────────────────────────────
    from app.data.session_repo import get_session_message_count
    turn_count = get_session_message_count(session_id)
    metrics_adjustments: dict = {}
    if turn_count % BATCH_TURN_INTERVAL == 0:
        metrics_adjustments = batch_update_cognitive_profile(
            request.student_id, request.subject, session_id
        )
        # Update remark and memory on batch boundary
        context_snippet = request.question[:200] + " → " + answer[:200]
        remark = llm.generate_remark(context_snippet)
        if remark:
            update_session_remark(session_id, remark)
            update_student_memory(
                request.student_id, request.subject, remark, context_snippet
            )

    # ── Step 8: Build response ────────────────────────────────────────────────
    with managed_session() as db:
        metrics = get_subject_metrics(db, request.student_id, request.subject)
        cognitive_skills = compute_cognitive_skills(metrics)

    pending_tasks = get_student_tasks(request.student_id, request.subject)

    return ChatResponse(
        session_id=session_id,
        answer=answer,
        sources=sources,
        conversation_length=turn_count,
        routed_chapter=routed_chapter,
        routed_topic=routed_topic,
        question_type=generation_mode,
        metrics=metrics,
        metrics_adjustments=metrics_adjustments,
        cognitive_skills=cognitive_skills,
        is_session_start=new_session,
        pending_tasks=pending_tasks,
        quiz_suggestion=quiz_suggestion_obj,
        yesterday_context=yesterday_ctx,
    )
