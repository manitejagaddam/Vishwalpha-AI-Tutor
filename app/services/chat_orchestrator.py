"""
app/services/chat_orchestrator.py
───────────────────────────────────
Main chat pipeline: routes, retrieves, classifies, generates, and persists.

Flow:
  1. Load conversation / create if new
  2. Save student message to tree & load conversation history (linearized)
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
"""
import time
import logging
import asyncio
import re
import threading
from typing import AsyncGenerator

from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.legacy import SourceInfo, QuizSuggestion, YesterdayContext
from app.data.repos.conversation_repo import (
    get_or_create_conversation,
    save_message,
    get_message_history,
    update_conversation_title,
)
from app.data.session_repo import (
    update_session_remark,
    update_student_memory,
    get_student_memory,
    get_student_tasks,
    update_session_mood,
    add_fast_memory_fact,
    consolidate_student_memories,
)
from app.data.quiz_repo import (
    get_yesterday_session_context,
)
from app.data.database import managed_session
from app.data.models.platform import User
from app.data.models.learning import StudentProfile
from app.data.cognitive_repo import (
    get_subject_metrics,
    get_full_subject_profile,
    compute_cognitive_skills,
    collect_turn_signals,
    detect_bloom_level,
    detect_sentiment,
    append_pending_signal,
    batch_update_cognitive_profile,
    batch_increment_chat_counters,
    increment_chat_turns,
    update_student_streak,
    increment_streak_questions,
    update_topic_mastery_from_chat,
    get_student_weak_topics,
    get_topics_due_for_review,
    extract_realtime_memory_and_nudges,
    nudge_learning_preference,
    set_learning_preference_field,
    get_learning_preferences,
    llm_update_cognitive_profile,
)
from app.config import settings
from app.services.tutor_llm import TutorLLM
from app.services.question_classifier import is_conversational
from app.services.retrieval_service import retrieve_with_confidence
from app.services.quiz_service import detect_concept_completion
from app.infra.vector_router import VectorRouter
from app.infra.redis_cache import RetrievalCache

logger = logging.getLogger(__name__)

# ── Module-level singletons (one per process) ────────────────────────────────────────
_tutor_llm: TutorLLM | None = None
_vector_router: VectorRouter | None = None
_session_cache: RetrievalCache | None = None


def _get_session_cache() -> RetrievalCache:
    global _session_cache
    if _session_cache is None:
        _session_cache = RetrievalCache()
    return _session_cache


def run_deep_session_sync(
    user_id: str,
    subject_id: int | None,
    conversation_id: str,
    context_snippet: str,
) -> None:
    """
    Runs ALL heavy end-of-session operations in the background thread.
    Triggered by:
      - POST /chat/session/end (explicit, on every chat/session switch, new chat, app close)
      - SESSION_SYNC_THRESHOLD_MINUTES timer (every 30 min during long sessions)

    Steps:
      1. Generate session remark + update student memory (LLM)
      2. Generate + write SessionInsight (topics mastered/struggled, summary, recommendations)
      3. Generate + write StudentTask rows from recommendations
      4. LLM-analyse full conversation and apply metric deltas
      5. Invalidate session cache so next turn reads fresh data
    """
    try:
        llm = _get_llm()
        sid_int = int(subject_id) if subject_id else 0

        # Fetch full conversation history for LLM analysis
        full_history: list[dict] = []
        subject_name = ""
        try:
            with managed_session() as db:
                full_history = get_message_history(db, conversation_id, limit=40)
                if subject_id:
                    from app.data.models.content import Subject as SubjectModel
                    sub = db.query(SubjectModel).filter(SubjectModel.id == subject_id).first()
                    if sub:
                        subject_name = sub.name
        except Exception as e:
            logger.warning(f"[DeepSync] Failed to fetch full history: {e}")

        # ── Step 1: Long-Term Memory consolidation (Full History, Non-Destructive) ──
        try:
            existing_memories = get_student_memory(user_id, subject_id)
            mem_result = llm.extract_durable_memories(
                existing_memories=existing_memories,
                conversation_history=full_history if full_history else [{"role": "user", "content": context_snippet}],
                subject=subject_name,
            )
            new_facts = mem_result.get("new_facts", [])
            resolved_facts = mem_result.get("resolved_facts", [])
            pref_nudges = mem_result.get("preference_nudges", {})

            last_msg_id = full_history[-1].get("id") if full_history else None
            consolidate_student_memories(
                student_id=user_id,
                subject_id=subject_id,
                new_facts=new_facts,
                resolved_facts=resolved_facts,
                source_message_id=last_msg_id,
            )

            # Apply preference nudges from LLM
            if pref_nudges:
                for p_key, p_val in pref_nudges.items():
                    if p_key == "preferred_length" and p_val in ("short", "medium", "detailed"):
                        set_learning_preference_field(user_id, "preferred_length", p_val)
                    elif isinstance(p_val, (int, float)) and p_val != 0:
                        nudge_learning_preference(user_id, p_key, float(p_val))
                _get_session_cache()._safe_del(f"sess:prefs:{user_id}")

            logger.info(f"[DeepSync] Memory consolidated: {len(new_facts)} new, {len(resolved_facts)} resolved")
        except Exception as e:
            logger.warning(f"[DeepSync] Memory consolidation failed: {e}", exc_info=True)

        # ── Step 2: Session Insight ───────────────────────────────────────────
        if full_history and len(full_history) >= 2:
            try:
                insight_data = llm.generate_session_insight(full_history, subject=subject_name)
                if insight_data:
                    from app.data.models.learning import SessionInsight
                    import uuid as _uuid
                    with managed_session() as db:
                        db.add(SessionInsight(
                            id=_uuid.uuid4(),
                            conversation_id=conversation_id,
                            user_id=user_id,
                            subject_id=subject_id,
                            topics_mastered=insight_data.get("topics_mastered", []),
                            topics_struggled=insight_data.get("topics_struggled", []),
                            misconceptions_found=insight_data.get("misconceptions_found", []),
                            bloom_levels_achieved=insight_data.get("bloom_levels_achieved"),
                            engagement_rating=insight_data.get("engagement_rating"),
                            session_summary=insight_data.get("session_summary", ""),
                            recommendations=insight_data.get("recommendations", []),
                        ))
                    logger.info(f"[DeepSync] SessionInsight written for conv {conversation_id}")

                    # ── Step 3: Student Tasks from recommendations ────────────
                    recommendations = insight_data.get("recommendations", [])
                    if recommendations:
                        from app.data.models.learning import StudentTask
                        with managed_session() as db:
                            for rec in recommendations[:3]:  # max 3 tasks per session
                                if isinstance(rec, str) and rec.strip():
                                    db.add(StudentTask(
                                        user_id=user_id,
                                        subject_id=subject_id,
                                        task=rec.strip(),
                                        is_done=False,
                                    ))
                        logger.info(f"[DeepSync] {len(recommendations[:3])} StudentTask(s) created")

            except Exception as e:
                logger.warning(f"[DeepSync] SessionInsight/Task generation failed: {e}", exc_info=True)

        # ── Step 4: LLM-based cognitive metric update ─────────────────────────
        if full_history and subject_id:
            try:
                llm_signals = llm.generate_llm_metric_signals(full_history)
                if llm_signals:
                    llm_update_cognitive_profile(user_id, subject_id, llm_signals)
                    logger.info(f"[DeepSync] LLM metric signals applied: {list(llm_signals.keys())}")
            except Exception as e:
                logger.warning(f"[DeepSync] LLM metric update failed: {e}")

        # ── Step 5: Invalidate session cache ──────────────────────────────────
        _get_session_cache().invalidate_session_state(user_id, sid_int)

    except Exception as e:
        logger.error(f"Deep session sync failed: {e}", exc_info=True)


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
        from app.data.models.content import Topic
        from sqlalchemy import func
        with managed_session() as db:
            query = db.query(Topic).filter(
                func.lower(Topic.title) == routed_topic.lower()
            )
            topic = query.first()
            return topic.id if topic else None
    except Exception:
        return None


class Msg:
    def __init__(self, role, content):
        self.role = role
        self.content = content


# ── Shared pre-generation setup ────────────────────────────────────────────────

def _build_pipeline_context(request: ChatRequest, user: User) -> dict:
    """
    Gathers all data needed before LLM generation:
    conversation tree, memory, weak topics, routing, retrieval.
    Returns a dict of everything the generator function needs.
    """
    # In Phase 2, class_num is on the User model
    class_num = user.class_num
    board_id = user.profile.board_id if user.profile else None
    subject_id_resolved = request.subject_id
    
    with managed_session() as db:
        if subject_id_resolved is None and request.subject:
            from app.data.models.content import Subject
            sub = db.query(Subject).filter(Subject.name == request.subject).first()
            if sub:
                subject_id_resolved = sub.id

        conv = get_or_create_conversation(
            db,
            user_id=user.id,
            conversation_id=request.conversation_id,
            subject_id=subject_id_resolved,
            study_space_id=request.study_space_id,
        )
        conversation_id = conv.id
        new_conversation = (conv.total_messages == 0)
        study_space_id = conv.study_space_id

        # Use the conversation's subject if we didn't have one
        if subject_id_resolved is None and conv.subject_id:
            subject_id_resolved = conv.subject_id
            
        # Extract workspace instructions while session is active
        space_instructions = ""
        space_title = ""
        if study_space_id:
            try:
                from app.data.models.content import StudySpace
                space = db.query(StudySpace).filter(StudySpace.id == study_space_id).first()
                if space and space.custom_instructions:
                    space_instructions = space.custom_instructions
                    space_title = space.title
            except Exception as e:
                logger.warning(f"Failed to fetch workspace instructions: {e}")
            
        # Fallback to the first subject in the DB if somehow it's still missing 
        # (prevents foreign key crashes for cross-subject chats until cross-subject metrics are supported)
        if subject_id_resolved is None:
            from app.data.models.content import Subject
            first_sub = db.query(Subject).first()
            if first_sub:
                subject_id_resolved = first_sub.id
            else:
                subject_id_resolved = None   # No subjects in DB — chat proceeds unscoped
                logger.warning("[Chat] No subject found in DB — student chatting without subject scope.")

        conv_last_topic = conv.last_topic_name if conv else None
        parent_id = request.parent_message_id or (conv.active_message_id if conv else None)

        # ── Per-message analytics ──────────────────────────────────────────────
        student_sentiment = detect_sentiment(request.question)
        student_bloom = detect_bloom_level(request.question)
        contains_question = "?" in request.question

        # ── Get History Up To This Message (Linearized working context) ───────
        history_dicts = get_message_history(
            db, 
            conversation_id, 
            leaf_message_id=parent_id, 
            limit=18
        )
        history = [Msg(h["role"], h["content"]) for h in history_dicts]

        # ── Save Student Message Node ─────────────────────────────────────────
        student_msg = save_message(
            db,
            conversation_id=conversation_id,
            role="student",
            content=request.question,
            parent_message_id=parent_id,
            idempotency_key=request.idempotency_key,
            sentiment=student_sentiment,
            bloom_level=student_bloom,
            contains_question=contains_question
        )
        student_msg_id = student_msg.id

        if request.attachments:
            from app.data.models.chat import MessageContentBlock
            for idx, att in enumerate(request.attachments, start=1):
                ctype = att.get("content_type", "")
                b_type = "image" if ctype.startswith("image/") else "text"
                db.add(MessageContentBlock(
                    message_id=student_msg.id,
                    block_type=b_type,
                    content=att.get("url") or att.get("filename"),
                    extra_data=att,
                    block_index=idx,
                ))
            db.flush()

    # ── Process Student Attachments (Multimodal Context) ──────────────────────
    attachment_context_str = ""
    attachment_query_addon = ""
    if request.attachments:
        att_parts = []
        for att in request.attachments:
            fn = att.get("filename", "attachment")
            desc = att.get("description", "")
            txt = att.get("extracted_text", "")
            hint = att.get("topic_hint", "")
            part = f"- File: {fn}"
            if desc:
                part += f"\n  Visual/Diagram Analysis: {desc}"
            if txt:
                part += f"\n  Transcribed Questions/Math: {txt}"
            if hint:
                part += f"\n  Topic Hint: {hint}"
            att_parts.append(part)
            if txt:
                attachment_query_addon += f" {txt[:200]}"
            elif hint:
                attachment_query_addon += f" {hint}"
        if att_parts:
            attachment_context_str = "[Student Uploaded Attachment(s) / Diagram / Homework Photo]:\n" + "\n".join(att_parts)

    # ── Yesterday context + spaced repetition reviews ─────────────────────────
    yesterday_ctx: YesterdayContext | None = None
    review_topics: list[dict] = []
    if new_conversation:
        ctx = get_yesterday_session_context(user.id)
        if ctx:
            yesterday_ctx = YesterdayContext(
                subject=ctx["subject"],
                topic=ctx["topic"],
                session_date=ctx["session_date"],
            )
        try:
            review_topics = get_topics_due_for_review(user.id)
        except Exception as e:
            logger.warning(f"Spaced repetition check failed: {e}")

    # ── Real-time memory & learning preference capture (Zero LLM, per-turn) ───
    _sc = _get_session_cache()
    sid_int = int(subject_id_resolved) if subject_id_resolved else 0

    try:
        rt_scan = extract_realtime_memory_and_nudges(request.question)
        fast_facts = rt_scan.get("facts", [])
        nudges = rt_scan.get("nudges", {})
        pref_fields = rt_scan.get("pref_field", {})

        new_fact_added = False
        for ff in fast_facts:
            if add_fast_memory_fact(
                student_id=str(user.id),
                fact=ff,
                subject_id=subject_id_resolved,
                source_message_id=str(student_msg_id),
            ):
                new_fact_added = True

        for n_key, n_val in nudges.items():
            nudge_learning_preference(str(user.id), n_key, n_val)
        for pf_key, pf_val in pref_fields.items():
            set_learning_preference_field(str(user.id), pf_key, pf_val)

        # Invalidate session cache so the current turn immediately picks up newly captured facts/prefs
        if new_fact_added:
            _sc._safe_del(f"sess:memory:{user.id}:{sid_int}")
        if nudges or pref_fields:
            _sc._safe_del(f"sess:prefs:{user.id}")
    except Exception as e:
        logger.warning(f"[Chat] Real-time memory capture failed: {e}")

    # ── Student memory + learning preferences (session-cached) ───────────────────────
    memory_items = _sc.get_session_memory(str(user.id), sid_int)
    if memory_items is None:
        memory_items = get_student_memory(user.id, subject_id_resolved)
        _sc.set_session_memory(str(user.id), sid_int, memory_items or [])

    student_memory_str = (
        "\n".join(f"- {m}" for m in memory_items)
        if memory_items else "(no memory yet)"
    )

    # ── Study Space custom instructions injection ─────────────────────────────
    if space_instructions:
        student_memory_str = f"[Study Workspace: '{space_title}'] Custom Instructions: {space_instructions}\n" + student_memory_str

    learning_prefs = _sc.get_session_prefs(str(user.id))
    if learning_prefs is None:
        learning_prefs = get_learning_preferences(user.id)
        _sc.set_session_prefs(str(user.id), learning_prefs)

    # ── Weak topics (session-cached) ────────────────────────────────────────────────
    weak_topics_str = ""
    try:
        cached_weak = _sc.get_session_weak_topics(str(user.id), sid_int)
        if cached_weak is None:
            cached_weak = get_student_weak_topics(user.id, subject_id_resolved)
            _sc.set_session_weak_topics(str(user.id), sid_int, cached_weak or [])
        if cached_weak:
            weak_topics_str = "\n".join(
                f"- {t['topic_title']} (mastery: {t['mastery_level']:.0f}%)"
                for t in cached_weak[:5]
            )
    except Exception as e:
        logger.warning(f"Weak topics fetch failed: {e}")

    # ── Question classification ───────────────────────────────────────────────
    llm = _get_llm()
    referential_triggers = {
        "it", "this", "that", "these", "those", "discussing", "discussed",
        "topic", "topics", "continue", "more", "again", "we are", "what was", "right now",
        "explain", "tell me"
    }
    q_words = set(re.findall(r"\w+", request.question.lower()))
    has_reference = bool(q_words & referential_triggers)

    if is_conversational(request.question) and not request.attachments and not (has_reference and (conv_last_topic or history)):
        question_type = "conversational"
    else:
        question_type = "curriculum" if request.attachments else llm.classify_question(request.question, history)

    # ── Retrieval (curriculum only) ───────────────────────────────────────────
    context         = ""
    sources: list[SourceInfo] = []
    routed_chapter  = ""
    routed_topic    = ""
    generation_mode = "conversational"
    confident_chunks: list[dict] = []

    if question_type == "curriculum":
        router = _get_router()
        routing_query = request.question
        if attachment_query_addon:
            routing_query = f"{request.question} {attachment_query_addon}".strip()
        elif has_reference:
            if conv_last_topic:
                routing_query = f"{conv_last_topic} {request.question}"
            elif history:
                prev_student_msg = next((m.content for m in reversed(history) if m.role == "student"), "")
                if prev_student_msg:
                    routing_query = f"{prev_student_msg[:120]} {request.question}"

        route = router.route_query(
            routing_query, class_num=class_num, subject_id=subject_id_resolved, board_id=board_id
        )
        if route:
            routed_chapter = route.get("chapter", "")
            routed_topic   = route.get("topic", "")
            context, confident_chunks = retrieve_with_confidence(
                question=routing_query,
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

    if attachment_context_str:
        context = (attachment_context_str + ("\n\n[Relevant NCERT Textbook Context]:\n" + context if context else "")).strip()
        if generation_mode == "conversational":
            generation_mode = "curriculum"

    return {
        "conversation_id":  conversation_id,
        "new_conversation": new_conversation,
        "student_msg_id":   student_msg_id,
        "attachments":      request.attachments or [],
        "history":          history,
        "class_num":        class_num,
        "subject_id":       subject_id_resolved,
        "student_memory_str": student_memory_str,
        "learning_prefs":   learning_prefs,
        "weak_topics_str":  weak_topics_str,
        "review_topics":    review_topics,
        "yesterday_ctx":    yesterday_ctx,
        "question_type":    question_type,
        "generation_mode":  generation_mode,
        "context":          context,
        "confident_chunks": confident_chunks,
        "sources":          sources,
        "routed_chapter":   routed_chapter,
        "routed_topic":     routed_topic,
        "conv_last_topic":  conv_last_topic,
        "student_sentiment": student_sentiment,
        "student_bloom":    student_bloom,
        "contains_question": contains_question,
    }


def _post_generation_pipeline(
    request: ChatRequest,
    user: User,
    ctx: dict,
    answer: str,
    response_time_ms: int,
) -> tuple[dict, dict, dict, int, list[str], QuizSuggestion | None, str]:
    """
    Everything after the LLM has returned an answer:
    persist, update metrics, return everything required for response.
    """
    llm           = _get_llm()
    conversation_id = ctx["conversation_id"]
    new_conversation = ctx["new_conversation"]
    student_msg_id = ctx["student_msg_id"]
    routed_topic  = ctx["routed_topic"]
    generation_mode = ctx["generation_mode"]
    student_sentiment = ctx["student_sentiment"]
    student_bloom   = ctx["student_bloom"]
    contains_question = ctx["contains_question"]
    class_num       = ctx["class_num"]
    subject_id_resolved = ctx["subject_id"]
    subject_str     = str(subject_id_resolved) if subject_id_resolved else "0"

    # ── Generate title for new sessions (background) ──────────────────────────
    if new_conversation:
        def _gen_title(cid, msg: str):
            try:
                with managed_session() as db:
                    title = llm.generate_chat_title(msg)
                    if title:
                        update_conversation_title(db, cid, title)
            except Exception as e:
                logger.error(f"Failed background title generation: {e}")
        threading.Thread(
            target=_gen_title, args=(conversation_id, request.question), daemon=True
        ).start()

    # ── Track routed topic in session ─────────────────────────────────────────
    topic_id = None
    if routed_topic:
        try:
            topic_id = _resolve_topic_id(routed_topic, class_num, subject_str)
        except Exception as e:
            logger.warning(f"Failed to update session topic: {e}")

    # ── Concept completion → quiz suggestion ──────────────────────────────────
    quiz_suggestion_obj: QuizSuggestion | None = None
    if generation_mode == "curriculum" and routed_topic:
        try:
            is_complete, topic_name = detect_concept_completion(answer, routed_topic)
            if is_complete:
                subject_name = request.subject or "Science"
                if subject_id_resolved:
                    try:
                        with managed_session() as db:
                            from app.data.models.content import Subject as SubjectModel
                            sub_obj = db.query(SubjectModel).filter(SubjectModel.id == subject_id_resolved).first()
                            if sub_obj:
                                subject_name = sub_obj.name
                    except Exception:
                        pass
                quiz_suggestion_obj = QuizSuggestion(
                    topic=topic_name or routed_topic,
                    subject=subject_name,
                    num_questions=7,
                )
        except Exception as e:
            logger.warning(f"Concept completion detection failed: {e}")

    # ── Persist Tutor Answer Node ─────────────────────────────────────────────
    with managed_session() as db:
        metadata = {
            "sources": [s.model_dump() for s in ctx.get("sources", [])],
            "chapter": ctx.get("routed_chapter", ""),
            "topic": ctx.get("routed_topic", ""),
            "question_type": ctx.get("generation_mode", "conversational"),
            "context": ctx.get("context", ""),
            "chunks": [
                {
                    "score": float(c.get("score", 0)),
                    "content": c.get("summary") or c.get("content") or "",
                    "metadata": c.get("metadata", {})
                }
                for c in ctx.get("confident_chunks", [])
            ],
            "prompt_messages": ctx.get("prompt_messages", []),
        }
        tutor_msg = save_message(
            db,
            conversation_id=conversation_id,
            role="assistant",
            content=answer,
            parent_message_id=student_msg_id,
            response_time_ms=response_time_ms,
            topic_id=topic_id,
            metadata=metadata
        )
        tutor_msg_id = tutor_msg.id

        # Direct query — avoid get_or_create accidentally spawning a ghost conversation
        from app.data.models.chat import Conversation as ConvModel
        conv = db.query(ConvModel).filter(ConvModel.id == conversation_id).first()
        turn_count = (conv.total_messages // 2) if conv else 0
        if conv and routed_topic:
            conv.last_topic_name = routed_topic
            if topic_id and topic_id not in (conv.topics_covered or []):
                conv.topics_covered = (conv.topics_covered or []) + [topic_id]

    # ── Session mood (skipped if incognito) ───────────────────────────────────
    if not request.incognito:
        try:
            if student_sentiment in ("frustrated", "confused"):
                update_session_mood(str(conversation_id), student_sentiment)
        except Exception as e:
            logger.warning(f"Session mood update failed: {e}")

    # ── Cognitive signals — metrics from session cache (saves DB query on turns 1-3) ─────────
    _sc = _get_session_cache()
    sid_int = int(subject_id_resolved) if subject_id_resolved else 0

    metrics = _sc.get_session_metrics(str(user.id), sid_int)
    if metrics is None:
        with managed_session() as db:
            metrics = get_subject_metrics(db, user.id, subject_id_resolved)
        _sc.set_session_metrics(str(user.id), sid_int, metrics)

    cognitive_skills = compute_cognitive_skills(metrics)
    metrics_adjustments: dict = {}

    if not request.incognito:
        signals = collect_turn_signals(
            question=request.question,
            answer=answer,
            question_type=generation_mode,
            metrics=metrics,
        )
        if signals:
            # 10b: Fire-and-forget in background daemon thread (non-blocking)
            threading.Thread(
                target=append_pending_signal,
                args=(str(user.id), subject_id_resolved, str(conversation_id), signals),
                daemon=True,
            ).start()

        # 10a: Batch update streak and chat-turn counters in 1 transaction
        try:
            batch_increment_chat_counters(str(user.id), subject_id_resolved)
        except Exception as e:
            logger.warning(f"Batch counter increment failed: {e}")

        # ── Topic mastery ─────────────────────────────────────────────────────────
        if topic_id and generation_mode == "curriculum":
            try:
                update_topic_mastery_from_chat(user.id, topic_id, student_bloom)
            except Exception as e:
                logger.warning(f"Topic mastery update failed: {e}")

        # ── Batch update every N turns ────────────────────────────────────────────
        if turn_count > 0 and turn_count % settings.COGNITIVE_BATCH_SIZE == 0:
            metrics_adjustments = batch_update_cognitive_profile(
                user.id, subject_id_resolved, str(conversation_id)
            )

            # Re-read updated metrics from DB, refresh session cache with new values
            with managed_session() as db:
                fresh_metrics = get_subject_metrics(db, user.id, subject_id_resolved)
            _sc.set_session_metrics(str(user.id), sid_int, fresh_metrics)
            metrics = fresh_metrics
            cognitive_skills = compute_cognitive_skills(metrics)

        # ── Deep Session Sync (Background) ─────────────────────────────────────────
        # Triggers every SESSION_SYNC_THRESHOLD_MINUTES to update memory & weak topics
        last_sync_key = f"sess:last_sync:{user.id}:{sid_int}"
        last_sync = _sc._safe_get(last_sync_key)
        now_ts = int(time.time())
        
        if not last_sync:
            # First turn of session, just set the timestamp
            _sc._safe_setex(last_sync_key, _sc._SESSION_TTL, str(now_ts))
        else:
            elapsed_mins = (now_ts - int(last_sync)) / 60
            if elapsed_mins >= settings.SESSION_SYNC_THRESHOLD_MINUTES:
                # Trigger deep sync in background
                _sc._safe_setex(last_sync_key, _sc._SESSION_TTL, str(now_ts))
                context_snippet = request.question[:200] + " → " + answer[:200]
                threading.Thread(
                    target=run_deep_session_sync,
                    args=(str(user.id), subject_id_resolved, str(conversation_id), context_snippet),
                    daemon=True,   # don't block process shutdown
                ).start()

    pending_tasks = get_student_tasks(user.id, subject_id_resolved)

    # ── Real-Time Cross-Device Sync (Addon #4) ────────────────────────────────
    try:
        from app.services.sync_service import sync_manager
        sync_manager.sync_broadcast(
            user_id=str(user.id),
            event="message_received",
            data={
                "session_id": str(conversation_id),
                "message": {
                    "id": str(tutor_msg_id),
                    "role": "tutor",
                    "content": answer,
                    "topic": ctx.get("routed_topic", ""),
                    "chapter": ctx.get("routed_chapter", ""),
                    "question_type": ctx.get("generation_mode", "conversational"),
                    "sources": [s.model_dump() for s in ctx.get("sources", [])],
                },
                "conversation_length": turn_count,
            },
        )
    except Exception as e:
        logger.debug(f"[RealTime Sync] Message sync broadcast error: {e}")

    return metrics, metrics_adjustments, cognitive_skills, turn_count, pending_tasks, quiz_suggestion_obj, tutor_msg_id


# ── Main orchestrator (blocking — for tests / sync callers) ───────────────────

def chat(request: ChatRequest, user: User) -> ChatResponse:
    """
    Full chat pipeline. Returns a ChatResponse ready for JSON serialisation.
    """
    ctx = _build_pipeline_context(request, user)
    llm = _get_llm()

    gen_start = time.time()
    answer, prompt_messages = llm.generate(
        mode=ctx["generation_mode"],
        question=request.question,
        history=ctx["history"],
        context=ctx["context"],
        student_memory=ctx["student_memory_str"],
        learning_preferences=ctx["learning_prefs"],
        weak_topics=ctx["weak_topics_str"],
        review_topics=ctx["review_topics"] if ctx["new_conversation"] else [],
        user_id=str(user.id),
        conversation_id=str(ctx["conversation_id"]),
    )
    ctx["prompt_messages"] = prompt_messages
    response_time_ms = int((time.time() - gen_start) * 1000)

    metrics, metrics_adjustments, cognitive_skills, turn_count, pending_tasks, quiz_suggestion_obj, msg_id = (
        _post_generation_pipeline(request, user, ctx, answer, response_time_ms)
    )

    return ChatResponse(
        conversation_id=ctx["conversation_id"],
        message_id=msg_id,
        answer=answer,
        sources=ctx["sources"],
        attachments=ctx.get("attachments", []),
        conversation_length=turn_count,
        routed_chapter=ctx["routed_chapter"],
        routed_topic=ctx["routed_topic"],
        question_type=ctx["generation_mode"],
        metrics=metrics,
        metrics_adjustments=metrics_adjustments,
        cognitive_skills=cognitive_skills,
        is_new_conversation=ctx["new_conversation"],
        pending_tasks=pending_tasks,
        quiz_suggestion=quiz_suggestion_obj,
        yesterday_context=ctx["yesterday_ctx"],
        context=ctx.get("context", ""),
        chunks=[
            {
                "score": float(c.get("score", 0)),
                "content": c.get("summary") or c.get("content") or "",
                "metadata": c.get("metadata", {})
            }
            for c in ctx.get("confident_chunks", [])
        ],
        prompt_messages=prompt_messages,
    )


# ── Streaming orchestrator (async generator) ──────────────────────────────────

async def chat_stream(
    request: ChatRequest, user: User
) -> AsyncGenerator[str, None]:
    import json as _json
    from app.infra.azure_openai_client import get_openai
    from app.config import settings

    # ── Build context (runs sync DB calls in a thread pool) ───────────────────
    ctx = await asyncio.to_thread(_build_pipeline_context, request, user)

    llm = _get_llm()

    # ── Emit meta event first so frontend knows conversation_id immediately ───
    yield f"data: {_json.dumps({'type': 'meta', 'conversation_id': str(ctx['conversation_id']), 'is_new_conversation': ctx['new_conversation']})}\n\n"

    from app.services.tutor_llm import (
        _CURRICULUM_PROMPT, _OPEN_CURRICULUM_PROMPT, _CONVERSATIONAL_PROMPT,
        _build_teaching_style, _build_weak_topics_section, _build_review_section,
    )
    teaching_style = _build_teaching_style(ctx["learning_prefs"] or {})
    weak_section   = _build_weak_topics_section(ctx["weak_topics_str"])
    review_section = _build_review_section(
        ctx["review_topics"] if ctx["new_conversation"] else []
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
    ctx["prompt_messages"] = messages

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
                max_tokens=max_tok,
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
        turn_count, pending_tasks, quiz_suggestion_obj, msg_id
    ) = await asyncio.to_thread(
        _post_generation_pipeline, request, user, ctx, answer, response_time_ms
    )

    # ── Final done event ──────────────────────────────────────────────────────
    done_payload = {
        "type": "done",
        "message_id": str(msg_id),
        "sources": [s.model_dump() for s in ctx["sources"]],
        "attachments":      ctx.get("attachments", []),
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
        "context":          ctx.get("context", ""),
        "chunks":           [
            {
                "score": float(c.get("score", 0)),
                "content": c.get("summary") or c.get("content") or "",
                "metadata": c.get("metadata", {})
            }
            for c in ctx.get("confident_chunks", [])
        ],
        "prompt_messages":  messages,
    }
    yield f"data: {_json.dumps(done_payload)}\n\n"
