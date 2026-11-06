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
from typing import AsyncGenerator, Any

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

        # ── Step 4a: Drain all accumulated per-turn signals into the profile ──────
        # This replaces the old per-turn batch trigger. Signals queued during the
        # session (regex-based, zero-LLM) are now drained once at session end for
        # a much more stable, session-level cognitive snapshot.
        if subject_id:
            try:
                from app.data.cognitive_repo import batch_update_cognitive_profile
                batch_update_cognitive_profile(user_id, subject_id, conversation_id)
                logger.info(f"[DeepSync] Pending per-turn signals drained for user {user_id}, subject {subject_id}")
            except Exception as e:
                logger.warning(f"[DeepSync] Per-turn signal drain failed: {e}")

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
        from app.data.models.content import Topic, Chapter, Book, Subject as SubjectModel, SchoolClass
        from sqlalchemy import func
        with managed_session() as db:
            query = db.query(Topic).filter(
                func.lower(Topic.title) == routed_topic.lower()
            )
            # Scope by subject name to prevent cross-subject mastery pollution
            if subject and str(subject).isdigit():
                # subject passed as subject_id integer
                query = query.join(Chapter, Topic.chapter_id == Chapter.id)\
                             .join(Book, Chapter.book_id == Book.id)\
                             .filter(Book.subject_id == int(subject))
            elif subject and not str(subject).isdigit():
                # subject passed as name string (fallback)
                query = query.join(Chapter, Topic.chapter_id == Chapter.id)\
                             .join(Book, Chapter.book_id == Book.id)\
                             .join(SubjectModel, Book.subject_id == SubjectModel.id)\
                             .filter(func.lower(SubjectModel.name) == subject.lower())
            topic = query.first()
            return topic.id if topic else None
    except Exception:
        return None


# ── Fast In-Memory L1 Caches for Static Educational & Session Data (0ms latency) ──
_IN_MEMORY_SYLLABUS_CACHE: dict[int, str] = {}
_IN_MEMORY_TOPICS_CACHE: dict[int, list] = {}
_IN_MEMORY_CONV_CACHE: dict[str, dict] = {}


def _save_student_message_sync(
    conversation_id,
    question: str,
    parent_id,
    idempotency_key,
    sentiment,
    bloom_level,
    contains_question,
    attachments,
) -> tuple[Any, int]:
    """Saves student message node to PostgreSQL asynchronously during LLM stream."""
    t_start = time.time()
    try:
        with managed_session() as db:
            student_msg = save_message(
                db,
                conversation_id=conversation_id,
                role="student",
                content=question,
                parent_message_id=parent_id,
                idempotency_key=idempotency_key,
                sentiment=sentiment,
                bloom_level=bloom_level,
                contains_question=contains_question
            )
            student_msg_id = student_msg.id
            if attachments:
                from app.data.models.chat import MessageContentBlock
                for idx, att in enumerate(attachments, start=1):
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
        return student_msg_id, int((time.time() - t_start) * 1000)
    except Exception as e:
        logger.error(f"Async student message save failed: {e}", exc_info=True)
        return None, int((time.time() - t_start) * 1000)


def _fast_resolve_topic_from_syllabus(
    question: str,
    subject_id: int | None,
    class_num: int | None,
    conv_last_topic: str | None = None,
) -> tuple[str, str, int | None]:
    """
    RAG-Free, zero-latency topic matcher (V4).
    Checks student question against cached chapters and topics in the subject's syllabus
    using exact substring and high-signal keyword token overlap.
    Returns: (routed_chapter, routed_topic, topic_id)
    """
    if not subject_id:
        return ("", conv_last_topic or "", None)

    q_lower = question.lower()
    q_words = set(re.findall(r"\w+", q_lower))
    stop_words = {"and", "the", "of", "in", "a", "an", "for", "to", "with", "on", "what", "is", "how", "can", "you", "explain", "tell", "me", "about"}

    global _IN_MEMORY_TOPICS_CACHE
    topics = _IN_MEMORY_TOPICS_CACHE.get(subject_id)
    if topics is None:
        try:
            from app.data.models.content import Topic, Chapter, Book
            with managed_session() as db:
                topics = (
                    db.query(Topic.id, Topic.title, Chapter.title.label("chapter_title"))
                    .join(Chapter, Topic.chapter_id == Chapter.id)
                    .join(Book, Chapter.book_id == Book.id)
                    .filter(Book.subject_id == subject_id)
                    .all()
                )
                if topics:
                    _IN_MEMORY_TOPICS_CACHE[subject_id] = topics
        except Exception as e:
            logger.warning(f"[V4] Fast topic resolve query failed: {e}")

    if not topics:
        return ("", conv_last_topic or "", None)

    try:
        # 1. Direct substring match
        for tid, t_title, ch_title in topics:
            if len(t_title) > 3 and t_title.lower() in q_lower:
                return (ch_title, t_title, tid)

        # 2. Keyword token overlap match
        best_match = None
        best_score = 0.0
        for tid, t_title, ch_title in topics:
            t_words = set(re.findall(r"\w+", t_title.lower())) - stop_words
            if not t_words:
                continue
            common = t_words & q_words
            if len(common) >= 2 or (len(t_words) == 1 and len(common) == 1):
                score = len(common) / len(t_words)
                if score > best_score:
                    best_score = score
                    best_match = (ch_title, t_title, tid)

        if best_match:
            return best_match

        # 3. Chapter title keyword match
        for tid, t_title, ch_title in topics:
            ch_words = set(re.findall(r"\w+", ch_title.lower())) - stop_words
            if not ch_words:
                continue
            common = ch_words & q_words
            if len(common) >= 2 or (len(ch_words) == 1 and len(common) == 1):
                return (ch_title, t_title, tid)

        # 4. Fallback to conversation's last active topic
        if conv_last_topic:
            for tid, t_title, ch_title in topics:
                if t_title.lower() == conv_last_topic.lower():
                    return (ch_title, t_title, tid)
    except Exception as e:
        logger.warning(f"[V4] Fast topic resolve failed: {e}")

    return ("", conv_last_topic or "", None)


class Msg:
    def __init__(self, role, content):
        self.role = role
        self.content = content


# ── Shared pre-generation setup ────────────────────────────────────────────────

def _build_subject_context(db, class_num: int, subject_id: int | None) -> str:
    """Build syllabus tree string. Cached in-memory & Redis per subject (24h TTL)."""
    if not subject_id:
        return f"Class {class_num} (Subject not specified)"

    global _IN_MEMORY_SYLLABUS_CACHE
    if subject_id in _IN_MEMORY_SYLLABUS_CACHE:
        return _IN_MEMORY_SYLLABUS_CACHE[subject_id]

    _sc = _get_session_cache()
    cached = _sc.get_syllabus(subject_id)
    if cached:
        _IN_MEMORY_SYLLABUS_CACHE[subject_id] = cached
        return cached

    from app.data.models.content import Subject, Book, Chapter, Topic

    def _query_syllabus(session):
        sub = session.query(Subject).filter(Subject.id == subject_id).first()
        if not sub:
            return f"Class {class_num}"

        rows = (
            session.query(Topic, Chapter)
            .join(Chapter, Topic.chapter_id == Chapter.id)
            .join(Book, Chapter.book_id == Book.id)
            .filter(Book.subject_id == subject_id)
            .order_by(Chapter.display_order, Topic.display_order)
            .all()
        )

        chapter_map = {}
        for r in rows:
            ch = r.Chapter
            t = r.Topic
            if ch.id not in chapter_map:
                chapter_map[ch.id] = {
                    "num": ch.chapter_number,
                    "title": ch.title,
                    "topics": []
                }
            if len(chapter_map[ch.id]["topics"]) < 3:
                t_title = t.title.strip()
                if t_title and t_title not in chapter_map[ch.id]["topics"]:
                    chapter_map[ch.id]["topics"].append(t_title)

        context_lines = [f"Class {class_num}, Subject: {sub.name}", "NCERT Curriculum Outline:"]
        for cid, cinfo in chapter_map.items():
            top_str = f" (Key topics: {', '.join(cinfo['topics'])})" if cinfo['topics'] else ""
            context_lines.append(f"- Chapter {cinfo['num']}: {cinfo['title']}{top_str}")

        return "\n".join(context_lines)

    if db is not None:
        result = _query_syllabus(db)
    else:
        with managed_session() as new_db:
            result = _query_syllabus(new_db)

    _IN_MEMORY_SYLLABUS_CACHE[subject_id] = result
    _sc.set_syllabus(subject_id, result)
    return result


def _build_pipeline_context(request: ChatRequest, user: User) -> dict:
    """
    Gathers all data needed before LLM generation:
    conversation tree, memory, weak topics, routing, retrieval.
    Returns a dict of everything the generator function needs.
    """
    # In Phase 2, class_num is on the User model
    t_prep_start = time.time()
    timings: dict[str, int] = {}

    class_num = user.class_num
    board_id = user.profile.board_id if user.profile else None
    subject_id_resolved = request.subject_id
    
    t_conv_start = time.time()
    conv_cid = str(request.conversation_id) if request.conversation_id else None
    conv_cached = _IN_MEMORY_CONV_CACHE.get(conv_cid) if conv_cid else None

    if conv_cached:
        conversation_id = conv_cached["id"]
        new_conversation = conv_cached.get("new_conversation", False)
        study_space_id = conv_cached.get("study_space_id")
        space_instructions = conv_cached.get("space_instructions", "")
        space_title = conv_cached.get("space_title", "")
        if subject_id_resolved is None:
            subject_id_resolved = conv_cached.get("subject_id")
        conv_last_topic = conv_cached.get("last_topic_name")
        parent_id = request.parent_message_id or conv_cached.get("active_message_id")
        timings["conv_init_ms"] = int((time.time() - t_conv_start) * 1000)
    else:
        with managed_session() as db:
            if subject_id_resolved is None and request.subject:
                from app.api.deps import resolve_subject
                sub = resolve_subject(db, request.subject, class_num)
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
            if subject_id_resolved is None:
                from app.data.models.content import Subject, SchoolClass
                first_sub = (
                    db.query(Subject)
                    .join(SchoolClass, Subject.class_id == SchoolClass.id)
                    .filter(SchoolClass.level == class_num)
                    .first()
                )
                if not first_sub:
                    first_sub = db.query(Subject).first()
                if first_sub:
                    subject_id_resolved = first_sub.id
                else:
                    subject_id_resolved = None
                    logger.warning("[Chat] No subject found in DB — student chatting without subject scope.")

            conv_last_topic = conv.last_topic_name if conv else None
            parent_id = request.parent_message_id or (conv.active_message_id if conv else None)
            
            _IN_MEMORY_CONV_CACHE[str(conversation_id)] = {
                "id": conversation_id,
                "new_conversation": new_conversation,
                "study_space_id": study_space_id,
                "space_instructions": space_instructions,
                "space_title": space_title,
                "subject_id": subject_id_resolved,
                "last_topic_name": conv_last_topic,
                "active_message_id": parent_id,
            }
            timings["conv_init_ms"] = int((time.time() - t_conv_start) * 1000)

    t_syl = time.time()
    subject_context_str = _build_subject_context(None, class_num, subject_id_resolved)
    timings["syllabus_ms"] = int((time.time() - t_syl) * 1000)

    # ── Student topic progress (cached, single optimised query) ───────────
    t_prog = time.time()
    student_progress_str = "(No progress data yet — start learning to track your journey!)"
    if subject_id_resolved:
        try:
            sid_int_prog = int(subject_id_resolved)
            _sc_prog = _get_session_cache()
            prog_cached = _sc_prog.get_session_progress(str(user.id), sid_int_prog)
            if prog_cached is None:
                from app.data.cognitive_repo import get_student_topic_progress
                prog_cached = get_student_topic_progress(str(user.id), sid_int_prog)
                if prog_cached:
                    _sc_prog.set_session_progress(str(user.id), sid_int_prog, prog_cached)
            if prog_cached:
                lines = []
                if prog_cached.get("mastered"):
                    lines.append("✅ Mastered topics:")
                    for t in prog_cached["mastered"][:8]:
                        lines.append(f"  - {t['topic_title']} (Ch. {t['chapter_num']}) — {t['mastery']}% mastery")
                if prog_cached.get("in_progress"):
                    lines.append("📖 Currently learning (in progress):")
                    for t in prog_cached["in_progress"][:5]:
                        lines.append(f"  - {t['topic_title']} (Ch. {t['chapter_num']}) — {t['mastery']}% mastery")
                if prog_cached.get("next_recommended"):
                    lines.append("🎯 Recommended next topics:")
                    for t in prog_cached["next_recommended"]:
                        lines.append(f"  - {t['topic_title']} ({t['chapter']})")
                if not prog_cached.get("mastered") and not prog_cached.get("in_progress"):
                    not_started = prog_cached.get("not_started", [])
                    if not_started:
                        lines.append("🚀 You haven’t started yet — suggested first topics:")
                        for t in not_started[:3]:
                            lines.append(f"  - {t['topic_title']} ({t['chapter']})")
                if lines:
                    student_progress_str = "\n".join(lines)
        except Exception as _prog_err:
            logger.warning(f"[Chat] Progress fetch failed: {_prog_err}")
    timings["progress_ms"] = int((time.time() - t_prog) * 1000)

    # ── Per-message analytics ──────────────────────────────────────────────
    student_sentiment = detect_sentiment(request.question)
    student_bloom = detect_bloom_level(request.question)
    contains_question = "?" in request.question

    # ── Get History Up To This Message (Linearized working context) ───────
    t_hist = time.time()
    _sc_hist = _get_session_cache()
    cached_hist = _sc_hist.get_conversation_history(str(conversation_id))
    if cached_hist is not None and not request.parent_message_id:
        history = [Msg(h["role"], h["content"]) for h in cached_hist]
    elif new_conversation:
        history = []
        _sc_hist.set_conversation_history(str(conversation_id), [])
    else:
        with managed_session() as db:
            history_dicts = get_message_history(
                db, 
                conversation_id, 
                leaf_message_id=parent_id, 
                limit=18
            )
            history = [Msg(h["role"], h["content"]) for h in history_dicts]
            _sc_hist.set_conversation_history(str(conversation_id), history_dicts)
    timings["history_ms"] = int((time.time() - t_hist) * 1000)
    timings["save_msg_ms"] = 0

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
                source_message_id=None,
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

    # ── Student memory + learning preferences (session-cached, single-pass bundle) ───
    t_prof = time.time()
    memory_items = _sc.get_session_memory(str(user.id), sid_int)
    learning_prefs = _sc.get_session_prefs(str(user.id))
    cached_weak = _sc.get_session_weak_topics(str(user.id), sid_int)

    # If any profile element is uncached, fetch all three in a single unified DB pass
    if memory_items is None or learning_prefs is None or cached_weak is None:
        try:
            from app.data.cognitive_repo import get_student_profile_bundle
            m_bundle, p_bundle, w_bundle = get_student_profile_bundle(str(user.id), subject_id_resolved)
            if memory_items is None:
                memory_items = m_bundle
                _sc.set_session_memory(str(user.id), sid_int, memory_items)
            if learning_prefs is None:
                learning_prefs = p_bundle
                _sc.set_session_prefs(str(user.id), learning_prefs)
            if cached_weak is None:
                cached_weak = w_bundle
                _sc.set_session_weak_topics(str(user.id), sid_int, cached_weak)
        except Exception as _prof_err:
            logger.warning(f"[Chat] Unified profile bundle fetch error: {_prof_err}")
            memory_items = memory_items or []
            learning_prefs = learning_prefs or {}
            cached_weak = cached_weak or []

    # ── Build prioritized student memory string ───────────────────────────────
    # Priority order: (1) goals/exams/high-signal, (2) academic preferences,
    # (3) subject-specific struggles, (4) general habits. Capped at 15 items.
    # This ensures the LLM always sees the most actionable context first.
    def _build_priority_memory(items: list[str]) -> str:
        if not items:
            return "(no memory yet)"
        priority_keywords = ["exam", "test", "target", "score", "board", "struggling", "weak", "class"]
        pref_keywords = ["prefers", "learns", "best with", "language", "step-by-step", "bullet", "analogy"]
        high, pref, other = [], [], []
        for item in items:
            il = item.lower()
            if any(k in il for k in priority_keywords):
                high.append(item)
            elif any(k in il for k in pref_keywords):
                pref.append(item)
            else:
                other.append(item)
        ordered = high[:5] + pref[:4] + other[:6]
        return "\n".join(f"- {m}" for m in ordered[:15])

    student_memory_str = _build_priority_memory(memory_items or [])

    # ── Study Space custom instructions injection ─────────────────────────────
    if space_instructions:
        student_memory_str = f"[Study Workspace: '{space_title}'] Custom Instructions: {space_instructions}\n" + student_memory_str

    # ── Weak topics string ───────────────────────────────────────────────────
    weak_topics_str = ""
    if cached_weak:
        weak_topics_str = "\n".join(
            f"- {t['topic_title']} (mastery: {t['mastery_level']:.0f}%)"
            for t in cached_weak[:5]
        )
    timings["profile_ms"] = int((time.time() - t_prof) * 1000)

    # ── Question classification (Zero-Latency Heuristic) ──────────────────────
    referential_triggers = {
        "it", "this", "that", "these", "those", "discussing", "discussed",
        "topic", "topics", "continue", "more", "again", "we are", "what was", "right now",
        "explain", "tell me"
    }
    q_words = set(re.findall(r"\w+", request.question.lower()))
    has_reference = bool(q_words & referential_triggers)

    if is_conversational(request.question) and not request.attachments and not (has_reference and (conv_last_topic or history)):
        question_type = "conversational"
        generation_mode = "conversational"
    else:
        question_type = "curriculum"
        generation_mode = "curriculum"

    # ── Version 4 Core: RAG-Free Direct LLM (Zero Embedding & pgvector Latency) ───
    # Bypasses VectorRouter and pgvector chunk cascade.
    # LLM operates with strict grade-adaptive boundaries and subject syllabus context.
    context = ""
    sources: list[SourceInfo] = []
    routed_chapter = ""
    routed_topic = conv_last_topic or ""
    confident_chunks: list[dict] = []

    # Fast in-memory topic resolution from syllabus for tracking (0ms delay)
    t_match = time.time()
    ch_fast, top_fast, tid_fast = _fast_resolve_topic_from_syllabus(
        request.question, subject_id_resolved, class_num, conv_last_topic
    )
    if ch_fast:
        routed_chapter = ch_fast
    if top_fast:
        routed_topic = top_fast
    timings["topic_match_ms"] = int((time.time() - t_match) * 1000)

    if attachment_context_str:
        context = attachment_context_str
        if generation_mode == "conversational":
            generation_mode = "curriculum"

    timings["db_prep_ms"] = int((time.time() - t_prep_start) * 1000)

    return {
        "conversation_id":  conversation_id,
        "new_conversation": new_conversation,
        "student_msg_id":   None,
        "parent_id":        parent_id,
        "attachments":      request.attachments or [],
        "attachment_context_str": attachment_context_str,
        "history":          history,
        "class_num":        class_num,
        "subject_id":       subject_id_resolved,
        "subject_context_str": subject_context_str,
        "student_progress_str": student_progress_str,
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
        "topic_id":         tid_fast,
        "conv_last_topic":  conv_last_topic,
        "student_sentiment": student_sentiment,
        "student_bloom":    student_bloom,
        "contains_question": contains_question,
        "timings":          timings,
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

    # ── Track routed topic in session (V4 zero-latency resolution) ───────────
    topic_id = ctx.get("topic_id")
    if not routed_topic:
        ch_fast, top_fast, tid_fast = _fast_resolve_topic_from_syllabus(
            request.question, subject_id_resolved, class_num, ctx.get("conv_last_topic")
        )
        if top_fast:
            routed_topic = top_fast
            ctx["routed_topic"] = top_fast
        if ch_fast:
            ctx["routed_chapter"] = ch_fast
        if tid_fast:
            topic_id = tid_fast

    if routed_topic and topic_id is None:
        try:
            topic_id = _resolve_topic_id(routed_topic, class_num, subject_str)
        except Exception as e:
            logger.warning(f"Failed to update session topic: {e}")

    # ── Concept completion → quiz suggestion (background, 1.5s cap) ─────────
    quiz_suggestion_obj: QuizSuggestion | None = None
    _quiz_container: list = []

    def _detect_completion_bg():
        try:
            is_complete, topic_name = detect_concept_completion(answer, routed_topic)
            if is_complete:
                _sname = request.subject or "Science"
                if subject_id_resolved:
                    try:
                        with managed_session() as _db:
                            from app.data.models.content import Subject as SubjectModel
                            _s = _db.query(SubjectModel).filter(SubjectModel.id == subject_id_resolved).first()
                            if _s:
                                _sname = _s.name
                    except Exception:
                        pass
                _quiz_container.append(QuizSuggestion(
                    topic=topic_name or routed_topic,
                    subject=_sname,
                    num_questions=7,
                ))
        except Exception as _e:
            logger.warning(f"Concept completion detection failed: {_e}")

    if generation_mode == "curriculum" and routed_topic:
        _ct = threading.Thread(target=_detect_completion_bg, daemon=True)
        _ct.start()
        _ct.join(timeout=1.5)  # Cap — don't block done event longer than 1.5s
        quiz_suggestion_obj = _quiz_container[0] if _quiz_container else None

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

        # 10a: Batch update streak and chat-turn counters in background
        threading.Thread(
            target=lambda: batch_increment_chat_counters(str(user.id), subject_id_resolved),
            daemon=True,
        ).start()

        # ── Topic mastery (background persistence & in-place cache update) ───
        if topic_id and generation_mode == "curriculum":
            _sid_bg = int(subject_id_resolved) if subject_id_resolved else 0
            _uid_bg = str(user.id)
            def _update_mastery_bg(_uid=_uid_bg, _tid=topic_id, _bloom=student_bloom, _sc_ref=_sc, _sid=_sid_bg):
                try:
                    new_lvl, new_bloom, t_title = update_topic_mastery_from_chat(_uid, _tid, _bloom)
                    # Update progress in-place in Redis & L1 (0ms latency, zero cache busting)
                    if t_title:
                        _sc_ref.update_cached_topic_mastery(_uid, _sid, t_title, new_lvl, new_bloom)
                except Exception as _e:
                    logger.warning(f"Topic mastery update failed: {_e}")
            threading.Thread(target=_update_mastery_bg, daemon=True).start()

        # NOTE: Cognitive metric batch_update_cognitive_profile has been moved to
        # run_deep_session_sync (triggered at session-end / 10-min timer).
        # Per-turn signals still queue via append_pending_signal; they are drained
        # at session end to produce a more accurate, session-level cognitive assessment.

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
    student_msg_id, save_ms = _save_student_message_sync(
        ctx["conversation_id"],
        request.question,
        ctx.get("parent_id"),
        request.idempotency_key,
        ctx.get("student_sentiment"),
        ctx.get("student_bloom"),
        ctx.get("contains_question", False),
        request.attachments,
    )
    ctx["student_msg_id"] = student_msg_id
    ctx["timings"]["save_msg_ms"] = save_ms
    _get_session_cache().append_conversation_history(
        str(ctx["conversation_id"]),
        {"role": "student", "content": request.question}
    )

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
        subject_context=ctx["subject_context_str"],
        student_progress=ctx["student_progress_str"],
        user_id=str(user.id),
        conversation_id=str(ctx["conversation_id"]),
        class_num=ctx["class_num"],
        attachment_context=ctx.get("attachment_context_str", ""),
    )
    ctx["prompt_messages"] = prompt_messages
    response_time_ms = int((time.time() - gen_start) * 1000)

    metrics, metrics_adjustments, cognitive_skills, turn_count, pending_tasks, quiz_suggestion_obj, msg_id = (
        _post_generation_pipeline(request, user, ctx, answer, response_time_ms)
    )

    _get_session_cache().append_conversation_history(
        str(ctx["conversation_id"]),
        {"role": "assistant", "content": answer}
    )
    if str(ctx["conversation_id"]) in _IN_MEMORY_CONV_CACHE:
        _IN_MEMORY_CONV_CACHE[str(ctx["conversation_id"])]["active_message_id"] = msg_id
        if ctx.get("routed_topic"):
            _IN_MEMORY_CONV_CACHE[str(ctx["conversation_id"])]["last_topic_name"] = ctx["routed_topic"]

    timings = dict(ctx.get("timings", {}))
    timings["llm_total_ms"] = response_time_ms
    timings["total_turn_ms"] = response_time_ms + timings.get("db_prep_ms", 0)

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
        timings=timings,
    )


# ── Streaming orchestrator (async generator) ──────────────────────────────────

async def chat_stream(
    request: ChatRequest, user: User
) -> AsyncGenerator[str, None]:
    import json as _json
    from app.infra.azure_openai_client import get_openai
    from app.config import settings

    t_turn_start = time.time()

    # ── Build context (runs sync DB calls in a thread pool) ───────────────────
    ctx = await asyncio.to_thread(_build_pipeline_context, request, user)
    timings = dict(ctx.get("timings", {}))
    timings["db_prep_ms"] = int((time.time() - t_turn_start) * 1000)

    # ── Kick off async student message persistence concurrently with LLM stream ──
    save_student_task = asyncio.create_task(
        asyncio.to_thread(
            _save_student_message_sync,
            ctx["conversation_id"],
            request.question,
            ctx.get("parent_id"),
            request.idempotency_key,
            ctx.get("student_sentiment"),
            ctx.get("student_bloom"),
            ctx.get("contains_question", False),
            request.attachments,
        )
    )

    llm = _get_llm()

    # ── Emit meta event first so frontend knows conversation_id & prep timings immediately ───
    yield f"data: {_json.dumps({'type': 'meta', 'conversation_id': str(ctx['conversation_id']), 'is_new_conversation': ctx['new_conversation'], 'timings': timings})}\n\n"

    from app.services.tutor_llm import (
        _V4_DIRECT_TUTOR_PROMPT, _OPEN_CURRICULUM_PROMPT, _CONVERSATIONAL_PROMPT,
        _build_teaching_style, _build_weak_topics_section, _build_review_section,
    )
    from app.prompts import get_grade_boundary_instructions
    teaching_style = _build_teaching_style(ctx["learning_prefs"] or {})
    weak_section   = _build_weak_topics_section(ctx["weak_topics_str"])
    review_section = _build_review_section(
        ctx["review_topics"] if ctx["new_conversation"] else []
    )

    mode = ctx["generation_mode"]
    if mode == "curriculum":
        grade_boundaries = get_grade_boundary_instructions(ctx.get("class_num"))
        att_section = f"\n{ctx.get('attachment_context_str', '')}" if ctx.get("attachment_context_str") else ""
        system_content = _V4_DIRECT_TUTOR_PROMPT.format(
            grade_boundaries=grade_boundaries,
            subject_context=ctx["subject_context_str"],
            student_progress=ctx["student_progress_str"],
            student_memory=ctx["student_memory_str"] or "(no memory yet)",
            teaching_style=teaching_style,
            weak_topics_section=weak_section,
            review_section=review_section,
            attachment_section=att_section,
        )
        temp, max_tok = 0.4, 1800
    elif mode == "open_curriculum":
        system_content = _OPEN_CURRICULUM_PROMPT.format(
            student_memory=ctx["student_memory_str"] or "(no memory yet)",
            teaching_style=teaching_style,
            weak_topics_section=weak_section,
            review_section=review_section,
            subject_context=ctx["subject_context_str"],
            student_progress=ctx["student_progress_str"],
        )
        temp, max_tok = 0.5, 2000
    else:  # conversational
        system_content = _CONVERSATIONAL_PROMPT.format(
            student_memory=ctx["student_memory_str"] or "(no memory yet)",
            teaching_style=teaching_style,
            weak_topics_section=weak_section,
            subject_context=ctx["subject_context_str"],
            student_progress=ctx["student_progress_str"],
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
    first_token_time = None

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
                if first_token_time is None:
                    first_token_time = time.time()
                    timings["llm_ttft_ms"] = int((first_token_time - gen_start) * 1000)
                    timings["total_ttft_ms"] = int((first_token_time - t_turn_start) * 1000)
                    yield f"data: {_json.dumps({'type': 'latency_update', 'timings': timings})}\n\n"
                full_answer.append(token)
                yield f"data: {_json.dumps({'type': 'token', 'content': token})}\n\n"
    except Exception as exc:
        logger.error(f"Streaming error: {exc}")
        if not save_student_task.done():
            save_student_task.cancel()
        yield f"data: {_json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"
        return

    # ── Ensure concurrent student message save has completed ────────────────
    student_msg_id, save_ms = await save_student_task
    ctx["student_msg_id"] = student_msg_id
    timings["save_msg_ms"] = save_ms

    _get_session_cache().append_conversation_history(
        str(ctx["conversation_id"]),
        {"role": "student", "content": request.question}
    )

    t_stream_end = time.time()
    timings["llm_stream_ms"] = int((t_stream_end - (first_token_time or gen_start)) * 1000)
    timings["total_turn_ms"] = int((t_stream_end - t_turn_start) * 1000)
    response_time_ms = int((t_stream_end - gen_start) * 1000)
    answer = "".join(full_answer)

    # ── Post-generation (persist, metrics, etc.) in a thread ─────────────────
    (
        metrics, metrics_adjustments, cognitive_skills,
        turn_count, pending_tasks, quiz_suggestion_obj, msg_id
    ) = await asyncio.to_thread(
        _post_generation_pipeline, request, user, ctx, answer, response_time_ms
    )

    _get_session_cache().append_conversation_history(
        str(ctx["conversation_id"]),
        {"role": "assistant", "content": answer}
    )
    if str(ctx["conversation_id"]) in _IN_MEMORY_CONV_CACHE:
        _IN_MEMORY_CONV_CACHE[str(ctx["conversation_id"])]["active_message_id"] = msg_id
        if ctx.get("routed_topic"):
            _IN_MEMORY_CONV_CACHE[str(ctx["conversation_id"])]["last_topic_name"] = ctx["routed_topic"]

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
        "timings":          timings,
    }
    yield f"data: {_json.dumps(done_payload)}\n\n"
