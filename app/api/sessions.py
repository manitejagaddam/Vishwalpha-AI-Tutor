"""
app/api/sessions.py
────────────────────
Session history routes — JWT protected.

GET /sessions                     — list all sessions for the authenticated student
GET /history/{session_id}         — full message history (all messages, not just 4)
GET /sessions/{session_id}/remark — AI-generated teacher remark for a session
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session as DBSession

from app.data.database import get_db, managed_session
from app.data.session_repo import (
    get_full_history,
    get_session_message_count,
    get_student_sessions,
    get_session_remark,
)
from app.data.cognitive_repo import get_subject_metrics
from app.data.models import ConversationSession, Student
from app.api.deps import get_current_student

router = APIRouter(tags=["Sessions"])


@router.get("/sessions")
def list_sessions(
    subject: str = "Science",
    student: Student = Depends(get_current_student),
):
    """Returns all past sessions for the authenticated student, most recent first."""
    return {"sessions": get_student_sessions(student.id, subject)}


@router.get("/history/{session_id}")
def get_session_history(
    session_id: str,
    db: DBSession = Depends(get_db),
    student: Student = Depends(get_current_student),
):
    """
    Returns FULL conversation history for a session.
    Uses get_full_history() (all messages) rather than the LLM context slice (4 msgs).
    Only accessible by the session's owning student.
    """
    # Verify ownership
    session = db.query(ConversationSession).filter(
        ConversationSession.id == session_id,
        ConversationSession.student_id == student.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    total = get_session_message_count(session_id)
    all_messages = get_full_history(session_id)
    metrics = get_subject_metrics(db, student.id, session.subject or "Science")

    return {
        "session_id":      session_id,
        "recent_messages": [m.model_dump() for m in all_messages],
        "total_messages":  total,
        "metrics":         metrics,
        "subject":         session.subject,
        "chat_title":      session.chat_title,
        "last_topic_name": session.last_topic_name,
    }


@router.get("/sessions/{session_id}/remark")
def session_remark(
    session_id: str,
    db: DBSession = Depends(get_db),
    student: Student = Depends(get_current_student),
):
    """Returns the latest AI-generated teacher remark for a session (ownership verified)."""
    session = db.query(ConversationSession).filter(
        ConversationSession.id == session_id,
        ConversationSession.student_id == student.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"remark": get_session_remark(session_id)}
