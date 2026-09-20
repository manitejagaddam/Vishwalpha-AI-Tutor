"""
app/api/student.py
───────────────────
Student profile routes — JWT protected.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.data.database import get_db
from app.data.models.platform import User
from app.data.models.learning import StudentProfile, OverallCognitiveProfile
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
    
    # Future: fetch subject-specific metrics if subject is provided
    # For now, return basic profile.
    
    return {
        "student_id": current_user.id,
        "username": current_user.username,
        "class_num": current_user.class_num,
        "subject": subject,
    }


@router.get("/memory")
def get_memory(
    subject: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns overall cognitive metrics (Memory).
    """
    cog = db.query(OverallCognitiveProfile).filter(OverallCognitiveProfile.user_id == current_user.id).first()
    
    if not cog:
        return {"metrics": {}, "cognitive_skills": {}}
        
    metrics = {
        "concept_master_score": cog.concept_master_score,
        "error_repetition_rate": cog.error_repetition_rate,
        "attempt_persistence": cog.attempt_persistence,
        "struggle_recovery_rate": cog.struggle_recovery_rate,
        "practice_intensity": cog.practice_intensity,
        "learning_velocity": cog.learning_velocity,
        "knowledge_retention": cog.knowledge_retention,
        "cognitive_thinking_level": cog.cognitive_thinking_level,
        "engagement_frequency": cog.engagement_frequency,
        "assessment_accuracy": cog.assessment_accuracy,
    }
    return {"metrics": metrics, "cognitive_skills": {}}
