"""
app/api/student.py
───────────────────
Student profile and cognitive metrics routes.
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session as DBSession
from cachetools import cached, TTLCache

from app.data.database import get_db, managed_session
from app.data.session_repo import get_student_memory
from app.data.cognitive_repo import (
    get_subject_metrics,
    compute_cognitive_skills,
    update_subject_profile,
    apply_profile_preset,
)
from app.data.models import ConversationSession
from app.schemas import UpdateMetricsRequest

router = APIRouter(prefix="/student", tags=["Student Profile"])


@router.get("/profile")
@cached(cache=TTLCache(maxsize=1024, ttl=5))
def get_profile(student_id: str, subject: str = "Science"):
    """
    Returns the student's raw cognitive metrics and derived high-level skills.
    Cached for 5 seconds per (student_id, subject) to reduce DB polling load.
    """
    with managed_session() as db:
        metrics = get_subject_metrics(db, student_id, subject)
        skills  = compute_cognitive_skills(metrics)
    return {"metrics": metrics, "cognitive_skills": skills}


@router.get("/memory")
@cached(cache=TTLCache(maxsize=1024, ttl=5))
def get_memory(student_id: str, subject: str = "Science"):
    """
    Returns the student's persistent cross-session learning memory.
    Cached for 5 seconds.
    """
    return {"memory": get_student_memory(student_id, subject)}


@router.post("/session/{session_id}/metrics")
def override_metrics(
    session_id: str,
    request: UpdateMetricsRequest,
    db: DBSession = Depends(get_db),
):
    """
    Teacher/admin endpoint to manually override cognitive metrics.
    Accepts either raw metric values (delta) or a named preset profile.
    """
    session = db.query(ConversationSession).filter(
        ConversationSession.id == session_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    student_id = session.student_id
    subject    = session.subject

    try:
        if request.profile_name:
            updated = apply_profile_preset(db, student_id, subject, request.profile_name)
            return {
                "status": "success",
                "message": f"Applied profile '{request.profile_name}'",
                "metrics": updated,
            }

        if request.metrics:
            current = get_subject_metrics(db, student_id, subject)
            adjustments = {
                k: {"delta": float(v) - float(current.get(k, 50.0))}
                for k, v in request.metrics.items()
                if k in current
            }
            update_subject_profile(db, student_id, subject, adjustments, source="manual")
            db.commit()
            updated = get_subject_metrics(db, student_id, subject)
            return {"status": "success", "message": "Metrics updated", "metrics": updated}

        raise HTTPException(
            status_code=400, detail="Must provide either 'metrics' or 'profile_name'."
        )

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
