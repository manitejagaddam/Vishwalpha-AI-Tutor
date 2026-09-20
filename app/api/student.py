"""
app/api/student.py
───────────────────
Student profile and cognitive metrics routes — JWT protected.

All routes derive student_id from the verified JWT token.
"""
import threading
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session as DBSession
from cachetools import TTLCache

from app.data.database import get_db, managed_session
from app.data.session_repo import get_student_memory
from app.data.cognitive_repo import (
    get_subject_metrics,
    compute_cognitive_skills,
    update_subject_profile,
    apply_profile_preset,
)
from app.data.models import ConversationSession, Student
from app.schemas import UpdateMetricsRequest
from app.api.deps import get_current_student

router = APIRouter(prefix="/student", tags=["Student Profile"])

# Thread-safe profile cache (TTL = 5 seconds per (student_id, subject))
_profile_cache: TTLCache = TTLCache(maxsize=1024, ttl=5)
_profile_cache_lock = threading.RLock()

_memory_cache: TTLCache = TTLCache(maxsize=1024, ttl=5)
_memory_cache_lock = threading.RLock()


@router.get("/profile")
def get_profile(
    subject: str = "Science",
    student: Student = Depends(get_current_student),
):
    """
    Returns the student's raw cognitive metrics and derived high-level skills.
    Thread-safe TTL cache (5s) per (student_id, subject) to reduce DB polling.
    student_id resolved from JWT — not from query param.
    """
    cache_key = (student.id, subject)

    with _profile_cache_lock:
        cached = _profile_cache.get(cache_key)
        if cached is not None:
            return cached

    with managed_session() as db:
        metrics = get_subject_metrics(db, student.id, subject)
        skills  = compute_cognitive_skills(metrics)

    result = {"metrics": metrics, "cognitive_skills": skills}

    with _profile_cache_lock:
        _profile_cache[cache_key] = result

    return result


@router.get("/memory")
def get_memory(
    subject: str = "Science",
    student: Student = Depends(get_current_student),
):
    """
    Returns the student's persistent cross-session learning memory.
    Thread-safe TTL cache (5s).
    """
    cache_key = (student.id, subject)

    with _memory_cache_lock:
        cached = _memory_cache.get(cache_key)
        if cached is not None:
            return cached

    result = {"memory": get_student_memory(student.id, subject)}

    with _memory_cache_lock:
        _memory_cache[cache_key] = result

    return result


@router.post("/session/{session_id}/metrics")
def override_metrics(
    session_id: str,
    request: UpdateMetricsRequest,
    db: DBSession = Depends(get_db),
    student: Student = Depends(get_current_student),
):
    """
    Teacher/admin endpoint to manually override cognitive metrics.
    Accepts either raw metric values (delta) or a named preset profile.
    The session must belong to the authenticated student.
    """
    session = db.query(ConversationSession).filter(
        ConversationSession.id == session_id,
        ConversationSession.student_id == student.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    subject = session.subject or "Science"

    try:
        if request.profile_name:
            updated = apply_profile_preset(db, student.id, subject, request.profile_name)
            return {
                "status": "success",
                "message": f"Applied profile '{request.profile_name}'",
                "metrics": updated,
            }

        if request.metrics:
            current = get_subject_metrics(db, student.id, subject)
            adjustments = {
                k: {"delta": float(v) - float(current.get(k, 50.0))}
                for k, v in request.metrics.items()
                if k in current
            }
            update_subject_profile(db, student.id, subject, adjustments, source="manual")
            db.commit()
            updated = get_subject_metrics(db, student.id, subject)
            # Invalidate cache after manual update
            with _profile_cache_lock:
                _profile_cache.pop((student.id, subject), None)
            return {"status": "success", "message": "Metrics updated", "metrics": updated}

        raise HTTPException(
            status_code=400, detail="Must provide either 'metrics' or 'profile_name'."
        )

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
