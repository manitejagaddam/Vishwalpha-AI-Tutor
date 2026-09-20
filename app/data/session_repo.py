"""
app/data/session_repo.py
─────────────────────────
All conversation session and memory operations.

Conversation memory strategy:
  - Last 2 student/tutor pairs → sent verbatim to the LLM
  - Older messages            → AI-summarised and stored on the session row
  - Persistent student memory → AI-curated facts across all sessions

Enhanced with:
  - Session duration tracking (ended_at, session_duration_sec)
  - Per-message analytics (avg_student_msg_len, total counts)
  - Session mood tracking
"""
import uuid
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func as sqla_func

from app.data.database import managed_session
from app.data.models import (
    ConversationSession,
    ConversationMessage,
    StudentMemory,
    StudentTask,
    DiagnosticState,
    PromptLog,
)
from app.infra.azure_openai_client import get_openai
from app.config import settings

logger = logging.getLogger(__name__)

MEMORY_MERGE_PROMPT = """You manage a persistent memory list for a student's subject profile.
These are AI-curated facts about the student that should inform future tutoring.

Existing memory entries:
{existing_memory}

New observation from this session (teacher's remark):
{remark}

New conversation context:
{context}

Task: Merge these into an updated memory list. Keep entries that are still relevant.
Add 1-2 new specific, useful facts about the student if observed.
Remove or merge duplicates. Keep the total under 8 bullet points.
Output ONLY a JSON array of strings (the memory entries).

Example:
["Student prefers step-by-step explanations.", "Struggles with pH calculations.", "Shows strong recall."]"""


# ── Session management ────────────────────────────────────────────────────────

def get_or_create_session(
    student_id: str,
    session_id: str = "",
    class_num: int | None = None,
    subject: str | None = None,
) -> str:
    """Returns existing session_id or creates a new one."""
    with managed_session() as db:
        if not session_id:
            session_id = str(uuid.uuid4())

        existing = db.query(ConversationSession).filter(
            ConversationSession.id == session_id
        ).first()

        if not existing:
            db.add(ConversationSession(
                id=session_id,
                student_id=student_id,
                class_num=class_num,
                subject=subject,
            ))

    return session_id


def is_new_session(session_id: str) -> bool:
    with managed_session() as db:
        msg = db.query(ConversationMessage).filter(
            ConversationMessage.session_id == session_id
        ).first()
        return msg is None


def save_turn(
    session_id: str,
    student_msg: str,
    tutor_msg: str,
    response_time_ms: int | None = None,
    student_sentiment: str | None = None,
    student_bloom: str | None = None,
    student_contains_question: bool | None = None,
    routed_topic: str | None = None,
    topic_id: int | None = None,
) -> None:
    """
    Appends one student+tutor message pair to the session.
    Enhanced to save per-message analytics.
    """
    with managed_session() as db:
        # Student message
        student_token_count = len(student_msg) // 4  # rough estimate
        db.add(ConversationMessage(
            session_id=session_id,
            role="student",
            content=student_msg,
            sentiment=student_sentiment,
            bloom_level=student_bloom,
            contains_question=student_contains_question,
            token_count=student_token_count,
            topic_id=topic_id,
        ))

        # Tutor message
        tutor_token_count = len(tutor_msg) // 4
        db.add(ConversationMessage(
            session_id=session_id,
            role="tutor",
            content=tutor_msg,
            response_time_ms=response_time_ms,
            routed_topic=routed_topic,
            token_count=tutor_token_count,
            topic_id=topic_id,
        ))

        # Update session-level analytics
        session = db.query(ConversationSession).filter(
            ConversationSession.id == session_id
        ).first()
        if session:
            session.total_student_msgs = (session.total_student_msgs or 0) + 1
            session.total_tutor_msgs = (session.total_tutor_msgs or 0) + 1

            # Running average of student message length
            total = session.total_student_msgs
            old_avg = session.avg_student_msg_len or 0
            session.avg_student_msg_len = round(
                ((old_avg * (total - 1)) + len(student_msg)) / total, 1
            )

            # Running average of response time
            if response_time_ms is not None:
                old_rt = session.avg_response_time_ms or 0
                session.avg_response_time_ms = round(
                    ((old_rt * (total - 1)) + response_time_ms) / total, 1
                )


def get_history(session_id: str) -> tuple[str, list]:
    """
    Returns (memory_summary, recent_messages).
    recent_messages = last 4 messages (2 turns) verbatim — used as LLM context.
    For the full display history (all messages), use get_full_history().
    """
    from app.schemas import ChatMessage

    with managed_session() as db:
        session = db.query(ConversationSession).filter(
            ConversationSession.id == session_id
        ).first()
        memory_summary = session.memory_summary or "" if session else ""

        messages = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.session_id == session_id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(4)
            .all()
        )
        recent = [ChatMessage(role=m.role, content=m.content) for m in reversed(messages)]

    return memory_summary, recent


def get_full_history(session_id: str) -> list:
    """
    Returns ALL messages in a session — used by the session detail API
    so the frontend can display the complete conversation on load.
    Unlike get_history(), this is not limited to 4 messages.
    """
    from app.schemas import ChatMessage

    with managed_session() as db:
        messages = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.session_id == session_id)
            .order_by(ConversationMessage.created_at.asc())
            .all()
        )
        return [ChatMessage(role=m.role, content=m.content) for m in messages]


def get_session_message_count(session_id: str) -> int:
    with managed_session() as db:
        return db.query(ConversationMessage).filter(
            ConversationMessage.session_id == session_id
        ).count()


def get_student_sessions(student_id: str, subject: str) -> list[dict]:
    """
    Returns all sessions for a student, most recent first.
    Uses a single GROUP BY query for message counts (eliminates N+1).
    """
    with managed_session() as db:
        # Single query: sessions + message counts via LEFT JOIN + GROUP BY
        rows = (
            db.query(
                ConversationSession,
                sqla_func.count(ConversationMessage.id).label("message_count"),
            )
            .outerjoin(
                ConversationMessage,
                ConversationMessage.session_id == ConversationSession.id,
            )
            .filter(
                ConversationSession.student_id == student_id,
                ConversationSession.subject == subject,
            )
            .group_by(ConversationSession.id)
            .order_by(ConversationSession.updated_at.desc())
            .limit(50)
            .all()
        )
        return [
            {
                "id": s.id,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                "message_count": count,
                "session_mood": s.session_mood,
                "session_duration_sec": s.session_duration_sec,
                "last_topic_name": s.last_topic_name,
                "chat_title": s.chat_title,
                "subject": s.subject,
            }
            for s, count in rows
        ]

def update_session_title(session_id: str, title: str):
    with managed_session() as db:
        session = db.query(ConversationSession).filter(ConversationSession.id == session_id).first()
        if session:
            session.chat_title = title
            db.commit()


def get_session_remark(session_id: str) -> str:
    with managed_session() as db:
        session = db.query(ConversationSession).filter(
            ConversationSession.id == session_id
        ).first()
        return session.last_remark or "" if session else ""


def update_session_remark(session_id: str, remark: str) -> None:
    with managed_session() as db:
        session = db.query(ConversationSession).filter(
            ConversationSession.id == session_id
        ).first()
        if session:
            session.last_remark = remark
            turn_count = db.query(ConversationMessage).filter(
                ConversationMessage.session_id == session_id
            ).count()
            session.last_remark_turn = turn_count


def update_session_mood(session_id: str, mood: str) -> None:
    """Updates the session-level mood indicator."""
    with managed_session() as db:
        session = db.query(ConversationSession).filter(
            ConversationSession.id == session_id
        ).first()
        if session:
            session.session_mood = mood


def end_session(session_id: str) -> None:
    """
    Marks a session as ended and computes its duration.
    Called when a new session starts or after a long idle period.
    """
    with managed_session() as db:
        session = db.query(ConversationSession).filter(
            ConversationSession.id == session_id
        ).first()
        if session and not session.ended_at:
            session.ended_at = datetime.now(timezone.utc)
            if session.created_at:
                delta = session.ended_at - session.created_at
                session.session_duration_sec = int(delta.total_seconds())


# ── Student memory (persistent cross-session facts) ───────────────────────────

def get_student_memory(student_id: str, subject: str) -> list[str]:
    with managed_session() as db:
        record = db.query(StudentMemory).filter(
            StudentMemory.student_id == student_id,
            StudentMemory.subject == subject,
        ).first()
        if not record or not record.memory:
            return []
        try:
            return json.loads(record.memory)
        except Exception:
            return []


def update_student_memory(
    student_id: str,
    subject: str,
    remark: str,
    context: str,
) -> None:
    """Uses an LLM to merge new observations into the persistent memory list."""
    existing = get_student_memory(student_id, subject)
    existing_str = "\n".join(f"- {m}" for m in existing) if existing else "(none yet)"

    try:
        client = get_openai()
        resp = client.chat.completions.create(
            messages=[{
                "role": "user",
                "content": MEMORY_MERGE_PROMPT.format(
                    existing_memory=existing_str,
                    remark=remark,
                    context=context[:500],
                ),
            }],
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            temperature=0.2,
            max_completion_tokens=300,
        )
        raw = resp.choices[0].message.content.strip()
        # Extract JSON array
        start, end = raw.find("["), raw.rfind("]")
        new_memory = json.loads(raw[start:end + 1]) if start != -1 else existing
    except Exception as exc:
        logger.warning(f"Memory merge failed: {exc}")
        new_memory = existing

    with managed_session() as db:
        record = db.query(StudentMemory).filter(
            StudentMemory.student_id == student_id,
            StudentMemory.subject == subject,
        ).first()
        if record:
            record.memory = json.dumps(new_memory)
        else:
            db.add(StudentMemory(
                student_id=student_id,
                subject=subject,
                memory=json.dumps(new_memory),
            ))


# ── Diagnostic state (Socratic mode) ─────────────────────────────────────────

def get_diagnostic_state(session_id: str) -> dict | None:
    with managed_session() as db:
        state = db.query(DiagnosticState).filter(
            DiagnosticState.session_id == session_id
        ).first()
        if state:
            try:
                return json.loads(state.state_json)
            except Exception:
                return None
        return None


def set_diagnostic_state(session_id: str, state: dict) -> None:
    with managed_session() as db:
        existing = db.query(DiagnosticState).filter(
            DiagnosticState.session_id == session_id
        ).first()
        if existing:
            existing.state_json = json.dumps(state)
        else:
            db.add(DiagnosticState(
                session_id=session_id,
                state_json=json.dumps(state),
            ))


# ── Student tasks ─────────────────────────────────────────────────────────────

def get_student_tasks(student_id: str, subject: str) -> list[str]:
    with managed_session() as db:
        tasks = db.query(StudentTask).filter(
            StudentTask.student_id == student_id,
            StudentTask.subject == subject,
            StudentTask.done == False,
        ).order_by(StudentTask.created_at.desc()).limit(5).all()
        return [t.task for t in tasks]


# ── Prompt log cleanup ────────────────────────────────────────────────────────

def cleanup_old_prompt_logs(days: int = 5) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with managed_session() as db:
        deleted = db.query(PromptLog).filter(PromptLog.created_at < cutoff).delete()
        logger.info(f"Cleaned up {deleted} prompt logs older than {days} days.")
        return deleted
