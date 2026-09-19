"""
app/api/sessions.py
────────────────────
Session history routes.
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session as DBSession

from app.data.database import get_db, managed_session
from app.data.session_repo import (
    get_history,
    get_session_message_count,
    get_student_sessions,
    get_session_remark,
)
from app.data.cognitive_repo import get_subject_metrics
from app.data.models import ConversationSession

router = APIRouter(tags=["Sessions"])


@router.get("/sessions")
def list_sessions(student_id: str, subject: str = "Science"):
    """Returns all past sessions for a student, most recent first."""
    return {"sessions": get_student_sessions(student_id, subject)}


@router.get("/history/{session_id}")
def get_session_history(session_id: str, db: DBSession = Depends(get_db)):
    """Returns full conversation history and metrics for a session."""
    total = get_session_message_count(session_id)
    if total == 0:
        raise HTTPException(status_code=404, detail="Session not found.")

    memory_summary, recent = get_history(session_id)

    session = db.query(ConversationSession).filter(
        ConversationSession.id == session_id
    ).first()

    metrics = {}
    if session:
        metrics = get_subject_metrics(db, session.student_id, session.subject)

    return {
        "session_id":      session_id,
        "memory_summary":  memory_summary,
        "recent_messages": [m.model_dump() for m in recent],
        "total_messages":  total,
        "metrics":         metrics,
    }


@router.get("/sessions/{session_id}/remark")
def session_remark(session_id: str):
    """Returns the latest AI-generated teacher remark for a session."""
    return {"remark": get_session_remark(session_id)}
