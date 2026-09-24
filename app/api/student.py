"""
app/api/student.py
───────────────────
Student profile routes — JWT protected.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.data.database import get_db
from app.data.models.platform import User
from app.data.models.learning import StudentProfile
from app.api.deps import get_current_user

router = APIRouter(prefix="/student", tags=["Student"])


@router.get("/profile")
def get_profile(
    subject: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns the student's basic profile.
    If subject_id is provided, includes subject-specific profile info.
    """
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == current_user.id).first()
    
    # Resolve numeric subject_id for the frontend to cache and pass back
    from app.api.deps import resolve_subject
    class_num = getattr(current_user, "class_num", 10) or 10
    sub = resolve_subject(db, subject, class_num) if subject else None
    resolved_subject_id = sub.id if sub else None
    
    return {
        "student_id": current_user.id,
        "username": current_user.username,
        "class_num": current_user.class_num,
        "subject": subject,
        "subject_id": resolved_subject_id,
    }


@router.get("/memory")
def get_memory(
    subject: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns overall cognitive metrics, skills, and semantic memory.
    """
    from app.api.deps import resolve_subject
    from app.data.cognitive_repo import get_subject_metrics, compute_cognitive_skills
    from app.data.session_repo import get_student_memory

    class_num = getattr(current_user, "class_num", 10) or 10
    sub = resolve_subject(db, subject, class_num) if subject else None

    # Fallback to first available subject if no subject provided/found
    if not sub:
        from app.data.models.content import SchoolClass, Subject
        sub = (
            db.query(Subject)
            .join(SchoolClass, Subject.class_id == SchoolClass.id)
            .filter(SchoolClass.level == class_num)
            .first()
        )
        if not sub:
            sub = db.query(Subject).first()

    if not sub:
        return {"metrics": {}, "cognitive_skills": {}, "memory": ""}

    metrics = get_subject_metrics(db, str(current_user.id), sub.id)
    memory_items = get_student_memory(str(current_user.id), sub.id)  # int, not str!
    memory_str = "\n".join(f"• {m}" for m in memory_items) if memory_items else ""

    return {
        "metrics": metrics,
        "cognitive_skills": compute_cognitive_skills(metrics) if metrics else {},
        "memory": memory_str,
    }


from pydantic import BaseModel

class UpdateMemoryRequest(BaseModel):
    subject: str | None = None
    fact: str

@router.post("/memory")
def update_memory(
    request: UpdateMemoryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Manually add a memory fact for the student.
    """
    from app.api.deps import resolve_subject
    from app.data.session_repo import add_fast_memory_fact
    
    class_num = getattr(current_user, "class_num", 10) or 10
    sub = resolve_subject(db, request.subject, class_num) if request.subject else None
    subject_id = sub.id if sub else None
    
    success = add_fast_memory_fact(
        student_id=str(current_user.id),
        fact=request.fact,
        subject_id=subject_id
    )
    
    return {"status": "success", "inserted": success, "fact": request.fact}
