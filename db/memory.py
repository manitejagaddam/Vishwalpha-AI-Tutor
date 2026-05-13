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
import uuid
import logging
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
    session_id: str = "",
    class_num: int | None = None,
    subject: str | None = None,
) -> str:
    """
    Returns an existing session_id or creates a new session.
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
                class_num=class_num,
                subject=subject,
            )
            db.add(session)
            db.commit()
            logger.info(f"Created new session: {session_id}")
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

        messages = session.messages  # already ordered by created_at (relationship)

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

    # Build the conversation text to summarise
    convo_text = "\n".join(
        f"{m.role.capitalize()}: {m.content}" for m in old_messages
    )

    # Include previous summary if it exists (rolling summarisation)
    existing_summary = session.summary or ""
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
