"""
db/memory.py
────────────
Conversation memory management.

Strategy (as per user requirement):
  - Last 2 turns (student + tutor pairs)  → sent verbatim to the LLM
  - Older turns                            → summarised by a small LLM call
                                              and stored on the session row

This balances quality (recent context is exact) with cost/space
(old context is compressed into a short summary paragraph).
"""

import os
import json
import uuid
import logging
from datetime import datetime, timedelta
from groq import Groq
from db.database import SessionLocal
from db.models import ConversationSession, ConversationMessage
from schemas import ChatMessage

logger = logging.getLogger(__name__)

# ── LLM client for summarisation (reuses the same Groq key) ──────────────────
_groq_client: Groq | None = None


def _get_groq() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    return _groq_client


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create_session(
    student_id: str,
    session_id: str = "",
    class_num: int | None = None,
    subject: str | None = None,
) -> str:
    """
    Returns an existing session_id or creates a new session linked to a student.
    If session_id is empty/None, generates a new UUID.
    """
    db = SessionLocal()
    try:
        if not session_id:
            session_id = str(uuid.uuid4())

        existing = db.query(ConversationSession).filter(
            ConversationSession.id == session_id
        ).first()

        if not existing:
            session = ConversationSession(
                id=session_id,
                student_id=student_id,
                class_num=class_num,
                subject=subject,
            )
            db.add(session)
            db.commit()
            logger.info(f"Created new session: {session_id} for student {student_id}")
        else:
            logger.info(f"Resuming session: {session_id}")

        return session_id
    finally:
        db.close()


def get_history(session_id: str) -> tuple[str, list[ChatMessage]]:
    """
    Returns (memory_summary, recent_messages).

    - memory_summary: compressed summary of older turns (may be empty)
    - recent_messages: last 2 full turn pairs (up to 4 messages) sent verbatim

    The caller should prepend the memory_summary to the LLM prompt as context,
    followed by the recent messages as actual conversation turns.
    """
    db = SessionLocal()
    try:
        session = db.query(ConversationSession).filter(
            ConversationSession.id == session_id
        ).first()

        if not session:
            return "", []

        # Filter out archived messages and sort
        messages = sorted([m for m in session.messages if not m.is_archived], key=lambda x: x.created_at)

        # Last 2 turn pairs = last 4 messages (student, tutor, student, tutor)
        recent_cutoff = 4
        recent_msgs = [
            ChatMessage(role=m.role, content=m.content)
            for m in messages[-recent_cutoff:]
        ]

        memory_summary = session.summary or ""

        return memory_summary, recent_msgs
    finally:
        db.close()


def get_full_session_messages(session_id: str) -> list[dict]:
    """
    Returns all messages for a session formatted for Streamlit UI.
    """
    db = SessionLocal()
    try:
        session = db.query(ConversationSession).filter(
            ConversationSession.id == session_id
        ).first()
        if not session:
            return []
        
        messages = sorted([m for m in session.messages if not m.is_archived], key=lambda x: x.created_at)
        return [
            {
                "role": "user" if m.role == "student" else "assistant",
                "content": m.content,
                "sources": [],
                "chunks": [],
                "chapter": "",
                "topic": m.routed_topic or ""
            }
            for m in messages
        ]
    finally:
        db.close()


def get_student_sessions(student_id: str, subject: str) -> list[dict]:
    """
    Returns a list of past sessions for a student and subject, ordered by most recent first.
    """
    db = SessionLocal()
    try:
        sessions = db.query(ConversationSession).filter(
            ConversationSession.student_id == student_id,
            ConversationSession.subject == subject
        ).order_by(ConversationSession.updated_at.desc()).all()
        
        return [
            {
                "id": s.id,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "message_count": len(s.messages)
            }
            for s in sessions
        ]
    finally:
        db.close()


def save_turn(
    session_id: str,
    question: str,
    answer: str,
    context_used: str = "",
    routed_topic: str = "",
) -> int:
    """
    Saves a student→tutor turn pair and triggers memory compression
    if there are enough old messages.

    Returns the total message count for this session.
    """
    db = SessionLocal()
    try:
        # Save student message
        db.add(ConversationMessage(
            session_id=session_id,
            role="student",
            content=question,
            context_used=context_used,
            routed_topic=routed_topic,
        ))

        # Save tutor message
        db.add(ConversationMessage(
            session_id=session_id,
            role="tutor",
            content=answer,
        ))

        db.commit()

        # Count total messages
        total = db.query(ConversationMessage).filter(
            ConversationMessage.session_id == session_id
        ).count()

        # Trigger summarisation if we have enough old messages
        # (more than 4 messages means there are turns beyond the recent 2 pairs)
        if total > 6:
            _compress_old_memory(db, session_id)

        return total
    finally:
        db.close()


def archive_old_messages(days: int = 5) -> int:
    """
    Marks messages older than the specified number of days as archived.
    Returns the number of messages archived.
    """
    db = SessionLocal()
    try:
        cutoff = datetime.now() - timedelta(days=days)
        # We can do a bulk update
        archived_count = db.query(ConversationMessage).filter(
            ConversationMessage.created_at < cutoff,
            ConversationMessage.is_archived == False
        ).update({"is_archived": True})
        
        db.commit()
        if archived_count > 0:
            logger.info(f"Archived {archived_count} messages older than {days} days.")
        return archived_count
    finally:
        db.close()


def get_session_message_count(session_id: str) -> int:
    """Returns the total number of messages in a session."""
    db = SessionLocal()
    try:
        return db.query(ConversationMessage).filter(
            ConversationMessage.session_id == session_id
        ).count()
    finally:
        db.close()



# ─────────────────────────────────────────────────────────────────────────────
# Internal: Memory Compression
# ─────────────────────────────────────────────────────────────────────────────

def _compress_old_memory(db, session_id: str) -> None:
    """
    Summarises all messages EXCEPT the last 4 (recent 2 turns) into a
    compact memory string, and saves it on the session row.

    This runs inside the caller's DB session to avoid extra connections.
    """
    session = db.query(ConversationSession).filter(
        ConversationSession.id == session_id
    ).first()
    if not session:
        return

    messages = session.messages  # ordered by created_at
    if len(messages) <= 4:
        return  # nothing to compress

    # Messages to summarise (everything except the last 4)
    old_messages = messages[:-4]

    existing_summary = session.summary or ""

    if existing_summary:
        # We only need to incorporate the messages that just fell out of the recent window.
        # Cap it to the last 4 old messages to avoid token blowups if compression was skipped.
        old_messages = old_messages[-4:]

    # Build the conversation text to summarise
    convo_text = "\n".join(
        f"{m.role.capitalize()}: {m.content}" for m in old_messages
    )

    # Force truncate raw text just in case (e.g. max 4000 characters)
    if len(convo_text) > 4000:
        convo_text = convo_text[-4000:]

    # Include previous summary if it exists (rolling summarisation)
    if existing_summary:
        convo_text = (
            f"Previous session summary:\n{existing_summary}\n\n"
            f"New messages to incorporate:\n{convo_text}"
        )

    # Call LLM to summarise — use a cheap, fast prompt
    try:
        client = _get_groq()
        model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

        response = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a memory compression assistant. "
                        "Summarise the following tutoring conversation into a concise paragraph. "
                        "Keep key facts: what topics were discussed, what the student understood, "
                        "what they struggled with, and any important context for future questions. "
                        "Be brief — max 150 words."
                    ),
                },
                {"role": "user", "content": convo_text},
            ],
            model=model,
            temperature=0.1,
            max_tokens=300,
        )

        summary = response.choices[0].message.content.strip()
        session.summary = summary
        db.commit()

        logger.info(
            f"Compressed {len(old_messages)} old messages into "
            f"{len(summary)} char summary for session {session_id}"
        )

    except Exception as e:
        logger.warning(f"Memory compression failed (non-critical): {e}")
        # Non-critical — the system works fine without summary,
        # it just sends fewer history messages


# ─────────────────────────────────────────────────────────────────────────────
# Session Remarks & Student Memory
# ─────────────────────────────────────────────────────────────────────────────

def update_session_remark(session_id: str, remark: str) -> None:
    """
    Saves the latest batch remark to the session row.
    The remark is a teacher-style performance note generated after every 4 turns.
    """
    if not remark:
        return
    db = SessionLocal()
    try:
        session = db.query(ConversationSession).filter(
            ConversationSession.id == session_id
        ).first()
        if session:
            session.session_remark = remark
            db.commit()
            logger.info(f"Updated session remark for {session_id}.")
    except Exception as e:
        logger.warning(f"update_session_remark failed: {e}")
    finally:
        db.close()


MEMORY_MERGE_SYSTEM_PROMPT = """You manage a persistent memory list for a student's subject profile.
These are facts learned about the student that should inform future tutoring.

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
["Student prefers step-by-step explanations.", "Struggles with application-level pH problems.", "Shows strong recall ability."]"""


def update_student_memory(
    student_id: str,
    subject: str,
    remark: str,
    recent_turns_text: str,
) -> None:
    """
    Updates the persistent student_memory JSON on the StudentSubjectProfile.
    Called after each batch update to extract and merge long-term facts.
    """
    if not remark:
        return
    db = SessionLocal()
    try:
        from db.models import StudentSubjectProfile
        profile = db.query(StudentSubjectProfile).filter(
            StudentSubjectProfile.student_id == student_id,
            StudentSubjectProfile.subject == subject,
        ).first()

        if not profile:
            return

        existing_memory: list[str] = json.loads(profile.student_memory or "[]")
        existing_str = "\n".join(f"- {m}" for m in existing_memory) if existing_memory else "(none yet)"

        prompt = MEMORY_MERGE_SYSTEM_PROMPT.format(
            existing_memory=existing_str,
            remark=remark,
            context=recent_turns_text[:600],
        )

        client = _get_groq()
        model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.1,
            max_tokens=300,
        )

        raw = response.choices[0].message.content.strip()
        # Parse the JSON array
        if "[" in raw:
            raw = raw[raw.find("["):raw.rfind("]")+1]
        new_memory: list[str] = json.loads(raw)

        profile.student_memory = json.dumps(new_memory[:8])  # cap at 8 entries
        db.commit()
        logger.info(f"Updated student memory for {student_id}/{subject}: {len(new_memory)} entries.")

    except Exception as e:
        logger.warning(f"update_student_memory failed (non-critical): {e}")
    finally:
        db.close()


def get_session_remark(session_id: str) -> str:
    """Returns the current session remark text."""
    db = SessionLocal()
    try:
        session = db.query(ConversationSession).filter(
            ConversationSession.id == session_id
        ).first()
        return (session.session_remark or "") if session else ""
    finally:
        db.close()


def get_student_memory(student_id: str, subject: str) -> list[str]:
    """Returns the persistent memory list for a student in a subject."""
    db = SessionLocal()
    try:
        from db.models import StudentSubjectProfile
        profile = db.query(StudentSubjectProfile).filter(
            StudentSubjectProfile.student_id == student_id,
            StudentSubjectProfile.subject == subject,
        ).first()
        if not profile or not profile.student_memory:
            return []
        return json.loads(profile.student_memory)
    except Exception:
        return []
    finally:
        db.close()

