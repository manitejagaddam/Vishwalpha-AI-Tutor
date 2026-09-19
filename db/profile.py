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


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — Topic Mastery CRUD
# ─────────────────────────────────────────────────────────────────────────────

def update_topic_mastery(
    db: Session,
    student_id: str,
    topic_id: int,
    understanding_score: float,
    was_backtracked: bool = False,
    backtrack_depth: int = 0,
    backtrack_class: int | None = None,
    understood_concepts: list[str] | None = None,
    confused_concepts: list[str] | None = None,
):
    """
    Creates or updates a StudentTopicMastery record.
    Uses a weighted moving average (new score weighted 30%) to avoid wild swings.
    Does NOT call db.commit() — the caller owns the transaction.
    """
    import json
    from db.models import StudentTopicMastery

    mastery = db.query(StudentTopicMastery).filter(
        StudentTopicMastery.student_id == student_id,
        StudentTopicMastery.topic_id == topic_id,
    ).first()

    if not mastery:
        mastery = StudentTopicMastery(student_id=student_id, topic_id=topic_id)
        db.add(mastery)

    # Weighted moving average: new score weighted 30%
    delta = (understanding_score * 100.0 - mastery.mastery_level) * 0.30
    mastery.mastery_level = max(0.0, min(100.0, mastery.mastery_level + delta))
    mastery.times_visited += 1

    if understood_concepts:
        existing = json.loads(mastery.understood_concepts or "[]")
        mastery.understood_concepts = json.dumps(list(set(existing + understood_concepts))[:20])

    if confused_concepts:
        existing = json.loads(mastery.confused_concepts or "[]")
        mastery.confused_concepts = json.dumps(list(set(existing + confused_concepts))[:20])

    if was_backtracked:
        mastery.required_backtrack = True
        mastery.backtrack_depth = max(mastery.backtrack_depth, backtrack_depth)
        if backtrack_class is not None:
            mastery.backtrack_class = backtrack_class

    logger.info(
        f"Mastery updated: student={student_id} topic_id={topic_id} "
        f"level={mastery.mastery_level:.1f} visits={mastery.times_visited}"
    )
    return mastery


def apply_mastery_decay(db: Session, student_id: str, subject: str) -> None:
    """
    Reduces mastery_level for topics the student hasn't revisited recently.
    Decay interval and rate are controlled by .env variables:
      MASTERY_DECAY_DAYS  (default: 30) — days without revisit before decay
      MASTERY_DECAY_RATE  (default: 0.05) — fractional reduction per interval
    """
    import os
    import json
    from datetime import datetime, timezone, timedelta
    from db.models import StudentTopicMastery, Topic, Chapter, Subject as DBSubject
    from sqlalchemy import func

    DECAY_DAYS = int(os.getenv("MASTERY_DECAY_DAYS", 30))
    DECAY_RATE = float(os.getenv("MASTERY_DECAY_RATE", 0.05))
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=DECAY_DAYS)

    stale_topics = (
        db.query(StudentTopicMastery)
        .join(Topic, StudentTopicMastery.topic_id == Topic.id)
        .join(Chapter, Topic.chapter_id == Chapter.id)
        .join(DBSubject, Chapter.subject_id == DBSubject.id)
        .filter(
            StudentTopicMastery.student_id == student_id,
            func.lower(DBSubject.name) == subject.lower(),
            StudentTopicMastery.last_visited < cutoff_date,
            StudentTopicMastery.mastery_level > 0.0,
        ).all()
    )

    for m in stale_topics:
        m.mastery_level = max(0.0, m.mastery_level * (1.0 - DECAY_RATE))

    if stale_topics:
        db.commit()
        logger.info(
            f"Mastery decay applied to {len(stale_topics)} stale topics "
            f"for student {student_id} / {subject}"
        )


def get_relevant_topic_memories(
    db: Session,
    student_id: str,
    topic_id: int,
    prereq_topic_ids: list[int] | None = None,
) -> dict:
    """
    Returns mastery memories ONLY for the current topic and its immediate prerequisites.
    Maximum 3 topics — keeps prompt injection focused.
    """
    import json
    from datetime import datetime, timezone
    from db.models import StudentTopicMastery

    target_ids = [topic_id] + (prereq_topic_ids or [])
    masteries = db.query(StudentTopicMastery).filter(
        StudentTopicMastery.student_id == student_id,
        StudentTopicMastery.topic_id.in_(target_ids[:3]),
    ).all()

    result = {}
    for m in masteries:
        days_stale = 0
        if m.last_visited:
            days_stale = (datetime.now(timezone.utc) - m.last_visited).days
        result[m.topic_id] = {
            "mastery_level": round(m.mastery_level, 1),
            "times_visited": m.times_visited,
            "understood": json.loads(m.understood_concepts or "[]")[:5],
            "confused": json.loads(m.confused_concepts or "[]")[:5],
            "required_backtrack": m.required_backtrack,
            "knowledge_stale": days_stale > 30,
            "days_since_visit": days_stale,
        }
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4 — Deterministic Metric Recompute (Pure Math, No LLM)
# ─────────────────────────────────────────────────────────────────────────────

def recompute_subject_metrics_from_mastery(db: Session, student_id: str, subject: str) -> dict:
    """
    Derives all subject metrics from StudentTopicMastery records.
    Zero LLM calls — pure math.

    Replaces the LLM batch metric update for the 5 measurable metrics:
      concept_master_score   = avg mastery level across all visited topics
      knowledge_retention    = % of revisited topics where score improved > 50
      struggle_recovery_rate = % of topics that did NOT require backtracking
      learning_velocity      = % of topics mastered in <= 2 visits
      error_repetition_rate  = % of topics with repeat backtracking (backtracked + visited > 2x)
    """
    from db.models import StudentTopicMastery, Topic, Chapter, Subject as DBSubject
    from sqlalchemy import func

    masteries = (
        db.query(StudentTopicMastery)
        .join(Topic, StudentTopicMastery.topic_id == Topic.id)
        .join(Chapter, Topic.chapter_id == Chapter.id)
        .join(DBSubject, Chapter.subject_id == DBSubject.id)
        .filter(
            StudentTopicMastery.student_id == student_id,
            func.lower(DBSubject.name) == subject.lower(),
        ).all()
    )

    if not masteries:
        logger.debug(
            f"recompute_subject_metrics_from_mastery: no mastery records for "
            f"student={student_id} subject={subject}. Skipping."
        )
        return {}

    n                 = len(masteries)
    total_mastery     = sum(m.mastery_level for m in masteries)
    visited_more      = [m for m in masteries if m.times_visited > 1]
    backtracks        = [m for m in masteries if m.required_backtrack]
    revisit_improved  = [m for m in visited_more if m.mastery_level > 50]
    fast_mastered     = [m for m in masteries if m.mastery_level > 60 and m.times_visited <= 2]
    repeat_struggles  = [m for m in masteries if m.required_backtrack and m.times_visited > 2]

    profile = get_or_create_subject_profile(db, student_id, subject)

    profile.concept_master_score   = total_mastery / n
    profile.knowledge_retention    = (len(revisit_improved) / max(1, len(visited_more))) * 100.0
    profile.struggle_recovery_rate = (1.0 - len(backtracks) / n) * 100.0
    profile.learning_velocity      = (len(fast_mastered) / n) * 100.0
    profile.error_repetition_rate  = len(repeat_struggles) / n   # 0.0 – 1.0

    db.commit()
    logger.info(
        f"Metrics recomputed from mastery for student={student_id} subject={subject}: "
        f"concept={profile.concept_master_score:.1f} retention={profile.knowledge_retention:.1f}"
    )
    return get_subject_metrics(db, student_id, subject)
