"""
db/profile.py
─────────────
Functions for managing and updating student cognitive profiles.
"""
import uuid
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from db.models import StudentSubjectProfile, OverallCognitiveProfile
import logging

logger = logging.getLogger(__name__)

CHAT_METRIC_WEIGHT = 1.0
BATCH_METRIC_WEIGHT = 1.0

METRICS_KEYS = [
    "concept_master_score", "error_repetition_rate", "attempt_persistence",
    "struggle_recovery_rate", "practice_intensity", "learning_velocity",
    "knowledge_retention", "cognitive_thinking_level", "engagement_frequency",
    "assessment_accuracy"
]

def _clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamps a value between a minimum and maximum bound."""
    return max(min_val, min(max_val, value))

def get_or_create_subject_profile(db: Session, student_id: str, subject: str) -> StudentSubjectProfile:
    """Fetches a subject profile, creating it if it doesn't exist."""
    profile = db.query(StudentSubjectProfile).filter(
        StudentSubjectProfile.student_id == student_id,
        StudentSubjectProfile.subject == subject
    ).first()
    
    if not profile:
        profile = StudentSubjectProfile(
            id=str(uuid.uuid4()),
            student_id=student_id,
            subject=subject
        )
        db.add(profile)
        db.flush()
        
    return profile

def update_subject_profile(db: Session, student_id: str, subject: str, raw_adjustments: dict, source: str = "chat") -> dict:
    """
    Applies adjustments to a subject profile.
    source can be "chat", "batch", "assignment", or "manual".
    Does NOT call db.commit() — the caller owns the transaction.
    """
    profile = get_or_create_subject_profile(db, student_id, subject)
    weight = CHAT_METRIC_WEIGHT if source in ("chat", "batch") else 1.0
    
    applied_adjustments = {}
    
    for key in METRICS_KEYS:
        if key in raw_adjustments:
            adj_data = raw_adjustments[key]
            if isinstance(adj_data, dict):
                raw_delta = float(adj_data.get("delta", 0.0))
            else:
                raw_delta = float(adj_data) - getattr(profile, key)
                
            effective_delta = raw_delta * weight
            old_val = getattr(profile, key)
            new_val = old_val + effective_delta
            
            min_val = 0.0
            max_val = 1.0 if key == "error_repetition_rate" else 100.0
            new_val = _clamp(new_val, min_val, max_val)
            
            setattr(profile, key, new_val)
            
            adj_type = "constant"
            if effective_delta > 0.01:
                adj_type = "increase"
            elif effective_delta < -0.01:
                adj_type = "decrease"
                
            applied_adjustments[key] = {
                "old_value": old_val,
                "delta": effective_delta,
                "new_value": new_val,
                "adjustment": adj_type,
                "reason": "Updated based on recent conversation."
            }

            logger.info(f"  Metric {key}: {old_val:.2f} → {new_val:.2f} (Δ {effective_delta:+.2f})")
            
    if source == "chat":
        profile.chat_turns_count += 1
    elif source == "assignment":
        profile.assignment_count += 1

    recompute_overall_profile(db, student_id)
    
    return applied_adjustments

def recompute_overall_profile(db: Session, student_id: str):
    """
    Averages all subject profiles and updates the overall profile.
    Does NOT call db.commit() — the caller owns the transaction.
    """
    profiles = db.query(StudentSubjectProfile).filter(StudentSubjectProfile.student_id == student_id).all()
    overall = db.query(OverallCognitiveProfile).filter(OverallCognitiveProfile.student_id == student_id).first()
    
    if not profiles or not overall:
        return
        
    num_profiles = len(profiles)
    for key in METRICS_KEYS:
        avg_val = sum(getattr(p, key) for p in profiles) / num_profiles
        setattr(overall, key, avg_val)

def get_subject_metrics(db: Session, student_id: str, subject: str) -> dict:
    """Returns the 10 raw metrics as a dictionary for a given subject."""
    profile = get_or_create_subject_profile(db, student_id, subject)
    return {k: getattr(profile, k) for k in METRICS_KEYS}

def get_overall_metrics(db: Session, student_id: str) -> dict:
    """Returns the 10 raw metrics as a dictionary for the overall profile."""
    overall = db.query(OverallCognitiveProfile).filter(OverallCognitiveProfile.student_id == student_id).first()
    if not overall:
        return {k: (0.0 if k == "error_repetition_rate" else 50.0) for k in METRICS_KEYS}
    return {k: getattr(overall, k) for k in METRICS_KEYS}
