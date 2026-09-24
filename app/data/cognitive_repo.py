"""
app/data/cognitive_repo.py
───────────────────────────
All cognitive profile operations consolidated into one place.

Responsibilities:
  - CRUD for StudentSubjectProfile and OverallCognitiveProfile
  - Per-turn signal collection (regex-based, zero LLM)
  - Batched profile updates (fired every BATCH_TURN_INTERVAL turns)
  - Preset profile application (for teachers/testing)
  - Cognitive skill derivation (Bloom's Taxonomy mapping)
  - Topic mastery tracking (update, query weak/strong)
  - Student streak management
  - Learning preference detection
  - Spaced repetition scheduling
"""
import re
import uuid
import json
import logging
from datetime import date, timedelta, datetime, timezone

from sqlalchemy.orm import Session

from app.data.database import managed_session
from app.data.models.learning import (
    StudentSubjectProfile,
    OverallCognitiveProfile,
    PendingMetricSignal,
    TopicMastery,
    MasteryEvent,
    StudentStreak,
    LearningPreference,
)
from app.data.models.platform import User
from app.data.models.content import Topic, Chapter, Subject

logger = logging.getLogger(__name__)

BATCH_TURN_INTERVAL = 4  # Batch-update metrics every N turns

METRICS_KEYS = [
    "concept_master_score", "error_repetition_rate", "attempt_persistence",
    "struggle_recovery_rate", "practice_intensity", "learning_velocity",
    "knowledge_retention", "cognitive_thinking_level", "engagement_frequency",
    "assessment_accuracy",
]

# ── Preset profiles (for teacher overrides) ───────────────────────────────────

PROFILE_PRESETS: dict[str, dict] = {
    "Standard": {k: (0.0 if k == "error_repetition_rate" else 50.0) for k in METRICS_KEYS},
    "Fast Learner": {
        "concept_master_score": 85.0, "error_repetition_rate": 0.05,
        "attempt_persistence": 90.0, "struggle_recovery_rate": 85.0,
        "practice_intensity": 80.0, "learning_velocity": 90.0,
        "knowledge_retention": 85.0, "cognitive_thinking_level": 75.0,
        "engagement_frequency": 85.0, "assessment_accuracy": 88.0,
    },
    "Struggling but Persistent": {
        "concept_master_score": 30.0, "error_repetition_rate": 0.4,
        "attempt_persistence": 80.0, "struggle_recovery_rate": 35.0,
        "practice_intensity": 45.0, "learning_velocity": 30.0,
        "knowledge_retention": 35.0, "cognitive_thinking_level": 25.0,
        "engagement_frequency": 70.0, "assessment_accuracy": 30.0,
    },
    "Casual": {
        "concept_master_score": 48.0, "error_repetition_rate": 0.2,
        "attempt_persistence": 40.0, "struggle_recovery_rate": 45.0,
        "practice_intensity": 30.0, "learning_velocity": 50.0,
        "knowledge_retention": 45.0, "cognitive_thinking_level": 35.0,
        "engagement_frequency": 30.0, "assessment_accuracy": 50.0,
    },
}

# ── Regex pattern detectors (zero LLM) ───────────────────────────────────────

_FOLLOWUP = re.compile(
    r"\b(why|how|what if|can you|could you|explain|clarify|tell me more|"
    r"does that mean|so (does|is|are|can)|but (why|how|what)|what about|"
    r"elaborate|isn't it|wouldn't)\b", re.IGNORECASE
)
_ANALYTICAL = re.compile(
    r"\b(compare|contrast|analyze|evaluate|differentiate|relationship between|"
    r"effect of|cause|because|therefore|conclude|prove|argue|difference between|"
    r"justify|implications|significance)\b", re.IGNORECASE
)
_SELF_CORRECTION = re.compile(
    r"\b(actually|wait|i mean|let me correct|i think i was wrong|no wait|"
    r"correction|i made a mistake|scratch that)\b", re.IGNORECASE
)
_FRUSTRATION = re.compile(
    r"\b(i don'?t understand|this is confusing|too hard|too difficult|"
    r"makes no sense|i'?m lost|help me|i give up|frustrated|ugh|argh|"
    r"this is stupid|i can'?t|impossible)\b", re.IGNORECASE
)
_CONFIDENCE = re.compile(
    r"\b(i think i understand|i got it|makes sense|easy|simple|"
    r"of course|obviously|clearly|i know|i remember|let me try)\b", re.IGNORECASE
)
_BLOOM_HIGHER = re.compile(
    r"\b(compare|contrast|evaluate|justify|create|design|propose|"
    r"argue|defend|judge|critique|hypothesi[sz]e|synthesize|construct)\b", re.IGNORECASE
)
_BLOOM_APPLY = re.compile(
    r"\b(apply|solve|calculate|use|demonstrate|show|implement|"
    r"compute|determine|find|work out)\b", re.IGNORECASE
)

# ── Real-time memory & preference detectors (zero LLM, per-turn) ───────────────
_EXAM_TIMELINE = re.compile(
    r"\b(?:my\s+)?(?:unit\s+test|board\s+exam|term\s+exam|preboard|exam|test|assessment|quiz)\s+"
    r"(?:is\s+)?(?:on|this|next|tomorrow|coming\s+up|in\s+\d+\s+days?)\s+([a-zA-Z0-9\s]{2,20})",
    re.IGNORECASE,
)
_CLASS_BOARD = re.compile(
    r"\b(?:i\s*(?:am|'m)\s*(?:in\s*)?)?(?:class|grade)\s*(\d{1,2})(?:\s*(?:th|st|nd|rd))?\s*(cbse|icse|state\s*board|ncert)?\b",
    re.IGNORECASE,
)
_PREF_BULLETS_SHORT = re.compile(
    r"\b(?:keep\s+it\s+(?:short|brief|concise)|in\s+bullets?|use\s+bullet\s+points?|too\s+long|don'?t\s+write\s+(?:too\s+much|long\s+paragraphs?))\b",
    re.IGNORECASE,
)
_PREF_DETAILED = re.compile(
    r"\b(?:explain\s+in\s+detail|give\s+(?:full|detailed)\s+explanations?|in-depth|step\s*by\s*step|elaborate\s+more)\b",
    re.IGNORECASE,
)
_PREF_EXAMPLES = re.compile(
    r"\b(?:give\s+(?:an?\s+)?examples?|more\s+examples?|real\s*life\s+examples?|practical\s+examples?)\b",
    re.IGNORECASE,
)
_PREF_ANALOGY = re.compile(
    r"\b(?:explain\s+like\s+i'?m\s+\d+|use\s+an?\s+analog(?:y|ies)|simple\s+analog(?:y|ies)|relate\s+to\s+daily\s+life)\b",
    re.IGNORECASE,
)
_PREF_VISUAL = re.compile(
    r"\b(?:diagrams?|visuals?|draw(?:ings?)?|charts?|sketch(?:es)?|illustrations?|mind\s*maps?)\b",
    re.IGNORECASE,
)
_LANG_PREF = re.compile(
    r"\b(?:don'?t\s+use\s+hindi|only\s+in\s+english|explain\s+in\s+english|in\s+hindi\s+please|hinglish)\b",
    re.IGNORECASE,
)
_GOAL_TARGET = re.compile(
    r"\b(?:target|aiming\s+for|want\s+to\s+score)\s+(\d{1,3}%?)\b",
    re.IGNORECASE,
)

# ── Internal helpers ──────────────────────────────────────────────────────────

def _clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))


def _get_or_create_profile(
    db: Session, user_id: str, subject_id: int
) -> StudentSubjectProfile:
    # Ensure subject_id is valid to prevent foreign key constraint violations
    if not subject_id or subject_id <= 0:
        first_sub = db.query(Subject).first()
        if first_sub:
            subject_id = first_sub.id
        else:
            logger.warning("[CognitiveRepo] No subjects found in DB when creating student profile.")

    profile = db.query(StudentSubjectProfile).filter(
        StudentSubjectProfile.user_id == user_id,
        StudentSubjectProfile.subject_id == subject_id,
    ).first()
    if not profile:
        profile = StudentSubjectProfile(
            id=str(uuid.uuid4()),
            user_id=user_id,
            subject_id=subject_id,
        )
        db.add(profile)
        db.flush()
    return profile

def _update_overall_profile(db: Session, user_id: str) -> None:
    """Averages all subject profiles to update the OverallCognitiveProfile."""
    profiles = db.query(StudentSubjectProfile).filter(StudentSubjectProfile.user_id == user_id).all()
    if not profiles:
        return
    
    overall = db.query(OverallCognitiveProfile).filter(OverallCognitiveProfile.user_id == user_id).first()
    if not overall:
        overall = OverallCognitiveProfile(user_id=user_id)
        db.add(overall)
        
    for key in METRICS_KEYS:
        avg_val = sum(getattr(p, key, 50.0) for p in profiles) / len(profiles)
        setattr(overall, key, avg_val)
    db.flush()

# ── Public API: Metrics ───────────────────────────────────────────────────────

def get_subject_metrics(db: Session, user_id: str, subject_id: int) -> dict:
    """Returns all 10 cognitive metrics for a student/subject."""
    profile = _get_or_create_profile(db, user_id, subject_id)
    return {k: getattr(profile, k, 50.0) for k in METRICS_KEYS}


def get_full_subject_profile(db: Session, user_id: str, subject_id: int) -> dict:
    """Returns all cognitive metrics + enhanced tracking fields."""
    profile = _get_or_create_profile(db, user_id, subject_id)
    base = {k: getattr(profile, k, 50.0) for k in METRICS_KEYS}
    base.update({
        "bloom_level_avg": profile.bloom_level_avg or 1.0,
        "avg_session_duration_min": profile.avg_session_duration_min or 0.0,
        "total_chat_turns": profile.total_chat_turns or 0,
        "total_quizzes": profile.total_quizzes or 0,
        "frustration_index": profile.frustration_index or 0.0,
        "confidence_index": profile.confidence_index or 50.0,
    })
    return base


def compute_cognitive_skills(metrics: dict) -> dict:
    """
    Derives 5 high-level cognitive skills from the 10 raw metrics.
    These are what the frontend displays as radar/bar charts.
    """
    err_rate = metrics.get("error_repetition_rate", 0.0)
    return {
        "concept_understanding": round(
            (metrics.get("concept_master_score", 50) * 0.6 +
             metrics.get("assessment_accuracy", 50) * 0.4), 2
        ),
        "learning_effort": round(
            (metrics.get("practice_intensity", 50) * 0.4 +
             metrics.get("attempt_persistence", 50) * 0.35 +
             metrics.get("engagement_frequency", 50) * 0.25), 2
        ),
        "learning_adaptability": round(
            (metrics.get("struggle_recovery_rate", 50) * 0.6 +
             max(0, (1 - err_rate) * 100) * 0.4), 2
        ),
        "knowledge_stability": round(
            (metrics.get("knowledge_retention", 50) * 0.55 +
             metrics.get("learning_velocity", 50) * 0.45), 2
        ),
        "cognitive_depth": round(metrics.get("cognitive_thinking_level", 50), 2),
    }


def update_subject_profile(
    db: Session,
    user_id: str,
    subject_id: int,
    raw_adjustments: dict,
    source: str = "chat",
) -> dict:
    """
    Applies delta adjustments to a subject profile.
    Does NOT commit — caller owns the transaction.
    Returns applied adjustments.
    """
    profile = _get_or_create_profile(db, user_id, subject_id)
    applied = {}

    for key in METRICS_KEYS:
        if key not in raw_adjustments:
            continue
        adj = raw_adjustments[key]
        delta = adj.get("delta", 0.0) if isinstance(adj, dict) else float(adj)

        current = getattr(profile, key, 50.0) or 50.0
        if key == "error_repetition_rate":
            new_val = _clamp(current + delta, 0.0, 1.0)
        else:
            new_val = _clamp(current + delta)

        setattr(profile, key, new_val)
        applied[key] = {"old": current, "new": new_val, "delta": delta}

    return applied


def apply_profile_preset(
    db: Session, user_id: str, subject_id: int, profile_name: str
) -> dict:
    """Overwrites all metrics using a named preset."""
    preset = PROFILE_PRESETS.get(profile_name)
    if not preset:
        raise ValueError(f"Unknown profile preset: '{profile_name}'")

    profile = _get_or_create_profile(db, user_id, subject_id)
    for key, val in preset.items():
        setattr(profile, key, val)
        
    _update_overall_profile(db, user_id)
    db.commit()
    return get_subject_metrics(db, user_id, subject_id)


def increment_chat_turns(user_id: str, subject_id: int) -> None:
    """Increments total_chat_turns on the subject profile. Called on every chat turn."""
    with managed_session() as db:
        profile = _get_or_create_profile(db, user_id, subject_id)
        profile.total_chat_turns = (profile.total_chat_turns or 0) + 1


def batch_increment_chat_counters(user_id: str, subject_id: int) -> dict:
    """
    Coalesces increment_chat_turns, increment_streak_questions, and update_student_streak
    into a single DB session/transaction, saving 2 round-trip DB calls per chat turn.
    """
    today = date.today()
    yesterday = today - timedelta(days=1)

    with managed_session() as db:
        # 1. Subject profile chat turn increment
        profile = _get_or_create_profile(db, user_id, subject_id)
        profile.total_chat_turns = (profile.total_chat_turns or 0) + 1

        # 2. Student streak & question counter
        streak = db.query(StudentStreak).filter(
            StudentStreak.user_id == user_id,
        ).first()

        if not streak:
            streak = StudentStreak(
                user_id=user_id,
                current_streak_days=1,
                longest_streak_days=1,
                last_active_date=today,
                total_active_days=1,
                total_sessions=1,
                total_questions_asked=1,
            )
            db.add(streak)
            streak_info = {
                "current_streak": 1,
                "longest_streak": 1,
                "total_active_days": 1,
            }
        else:
            streak.total_questions_asked = (streak.total_questions_asked or 0) + 1
            if streak.last_active_date == today:
                streak.total_sessions = (streak.total_sessions or 0) + 1
            else:
                if streak.last_active_date == yesterday:
                    streak.current_streak_days = (streak.current_streak_days or 0) + 1
                else:
                    streak.current_streak_days = 1

                streak.longest_streak_days = max(
                    streak.longest_streak_days or 0, streak.current_streak_days
                )
                streak.last_active_date = today
                streak.total_active_days = (streak.total_active_days or 0) + 1
                streak.total_sessions = (streak.total_sessions or 0) + 1

            streak_info = {
                "current_streak": streak.current_streak_days,
                "longest_streak": streak.longest_streak_days,
                "total_active_days": streak.total_active_days,
            }

        # 3. User last_active_at
        student = db.query(User).filter(User.id == user_id).first()
        if student:
            student.last_active_at = datetime.now(timezone.utc)

        return streak_info


def increment_quiz_count(user_id: str, subject_id: int) -> None:
    """Increments total_quizzes on the subject profile. Called when a quiz is finished."""
    with managed_session() as db:
        profile = _get_or_create_profile(db, user_id, subject_id)
        profile.total_quizzes = (profile.total_quizzes or 0) + 1


def update_emotional_indicators(
    user_id: str, subject_id: int, frustration_delta: float, confidence_delta: float
) -> None:
    """Updates frustration_index and confidence_index with deltas."""
    with managed_session() as db:
        profile = _get_or_create_profile(db, user_id, subject_id)
        profile.frustration_index = _clamp(
            (profile.frustration_index or 0.0) + frustration_delta
        )
        profile.confidence_index = _clamp(
            (profile.confidence_index or 50.0) + confidence_delta
        )


# ── Per-turn signal collection (called during chat, zero LLM) ─────────────────

def collect_turn_signals(
    question: str,
    answer: str,
    question_type: str,
    metrics: dict,
) -> dict:
    """
    Analyses a single student question using pure regex to produce metric signals.
    Returns a dict of metric keys → delta values.
    Also includes frustration/confidence signals.
    """
    signals: dict[str, float] = {}

    # Engagement
    if question_type in ("curriculum", "open_curriculum"):
        signals["engagement_frequency"] = 1.0
        signals["practice_intensity"] = 0.5

    # Analytical thinking (Bloom's higher-order)
    if _ANALYTICAL.search(question):
        signals["cognitive_thinking_level"] = 2.0
        signals["concept_master_score"] = 0.5

    # Even higher-order Bloom's keywords
    if _BLOOM_HIGHER.search(question):
        signals["cognitive_thinking_level"] = 3.0

    # Application-level keywords
    if _BLOOM_APPLY.search(question):
        signals["cognitive_thinking_level"] = 1.5
        signals["concept_master_score"] = 0.3

    # Curiosity/follow-up
    if _FOLLOWUP.search(question):
        signals["attempt_persistence"] = 1.0
        signals["engagement_frequency"] = 0.5

    # Self-correction detected
    if _SELF_CORRECTION.search(question):
        signals["struggle_recovery_rate"] = 2.0
        signals["error_repetition_rate"] = -0.01

    # Frustration detection
    frustration_delta = 0.0
    confidence_delta = 0.0
    if _FRUSTRATION.search(question):
        frustration_delta = 5.0
        confidence_delta = -3.0
        signals["struggle_recovery_rate"] = -1.0

    if _CONFIDENCE.search(question):
        confidence_delta += 2.0
        frustration_delta -= 2.0

    # Store emotional signals as special keys (processed separately)
    if frustration_delta != 0:
        signals["_frustration_delta"] = frustration_delta
    if confidence_delta != 0:
        signals["_confidence_delta"] = confidence_delta

    return signals


def detect_bloom_level(question: str) -> str:
    """Detects the Bloom's taxonomy level of a student question using regex."""
    if _BLOOM_HIGHER.search(question):
        # Check for specific levels
        q_lower = question.lower()
        if any(w in q_lower for w in ["create", "design", "propose", "construct"]):
            return "create"
        if any(w in q_lower for w in ["evaluate", "judge", "critique", "justify", "defend"]):
            return "evaluate"
        return "analyze"
    if _BLOOM_APPLY.search(question):
        return "apply"
    if _ANALYTICAL.search(question):
        return "analyze"
    if _FOLLOWUP.search(question):
        return "understand"
    return "remember"


def detect_sentiment(question: str) -> str:
    """Detects basic sentiment of a student message using regex."""
    if _FRUSTRATION.search(question):
        return "frustrated"
    if re.search(r"\b(confused|don'?t understand|unclear|not sure)\b", question, re.IGNORECASE):
        return "confused"
    if _CONFIDENCE.search(question):
        return "positive"
    if re.search(r"\b(thanks|thank|great|awesome|cool|nice|amazing)\b", question, re.IGNORECASE):
        return "positive"
    return "neutral"


def extract_realtime_memory_and_nudges(question: str) -> dict:
    """
    Fast regex scanner on student input (runs in <1ms on every turn).
    Returns discovered durable facts and preference adjustments.
    """
    facts = []
    nudges = {}
    pref_field = {}

    m_exam = _EXAM_TIMELINE.search(question)
    if m_exam:
        facts.append(f"Upcoming assessment: {m_exam.group(0).strip()}")

    m_cb = _CLASS_BOARD.search(question)
    if m_cb and (m_cb.group(1) or m_cb.group(2)):
        cls = m_cb.group(1) or ""
        brd = m_cb.group(2) or ""
        desc = f"Student mentions: Class {cls} {brd}".strip()
        facts.append(desc)

    m_goal = _GOAL_TARGET.search(question)
    if m_goal:
        facts.append(f"Score target: {m_goal.group(0).strip()}")

    if _PREF_BULLETS_SHORT.search(question):
        facts.append("Prefers concise bullet-point answers")
        pref_field["preferred_length"] = "short"

    if _PREF_DETAILED.search(question):
        nudges["prefers_step_by_step"] = 0.15
        pref_field["preferred_length"] = "detailed"

    if _PREF_EXAMPLES.search(question):
        nudges["prefers_examples"] = 0.15

    if _PREF_ANALOGY.search(question):
        nudges["prefers_analogies"] = 0.15

    if _PREF_VISUAL.search(question):
        nudges["prefers_visuals"] = 0.15

    m_lang = _LANG_PREF.search(question)
    if m_lang:
        facts.append(f"Language preference: {m_lang.group(0).strip()}")

    return {
        "facts": facts,
        "nudges": nudges,
        "pref_field": pref_field,
    }


def append_pending_signal(
    user_id, subject_id: int, conversation_id, signals: dict
) -> None:
    """Queues a signal dict for the next batch update."""
    if not signals:
        return

    # Handle emotional indicators separately (they bypass the batch queue)
    frustration_delta = signals.pop("_frustration_delta", 0.0)
    confidence_delta = signals.pop("_confidence_delta", 0.0)
    if frustration_delta or confidence_delta:
        try:
            update_emotional_indicators(user_id, subject_id, frustration_delta, confidence_delta)
        except Exception as e:
            logger.warning(f"Emotional indicator update failed: {e}")

    if not signals:
        return

    # Sanitize conversation_id into a valid UUID object or None (never empty string!)
    conv_uuid = None
    if conversation_id:
        if isinstance(conversation_id, uuid.UUID):
            conv_uuid = conversation_id
        else:
            cid_str = str(conversation_id).strip()
            if cid_str:
                try:
                    conv_uuid = uuid.UUID(cid_str)
                except (ValueError, TypeError):
                    conv_uuid = None

    user_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))

    with managed_session() as db:
        db.add(PendingMetricSignal(
            user_id=user_uuid,
            subject_id=subject_id,
            conversation_id=conv_uuid,
            signals=signals,
        ))


def batch_update_cognitive_profile(
    user_id: str, subject_id: int, conversation_id: str
) -> dict:
    """
    Drains all pending signals for this student/subject and applies them.
    Called every BATCH_TURN_INTERVAL turns.
    Returns the adjustments dict.
    """
    with managed_session() as db:
        pending = db.query(PendingMetricSignal).filter(
            PendingMetricSignal.user_id == user_id,
            PendingMetricSignal.subject_id == subject_id,
        ).all()

        if not pending:
            return {}

        merged: dict[str, float] = {}
        for record in pending:
            try:
                sigs = record.signals
                if isinstance(sigs, str):
                    sigs = json.loads(sigs)
                for k, v in sigs.items():
                    merged[k] = merged.get(k, 0.0) + float(v)
            except Exception:
                pass

        # Convert to delta format
        adjustments = {k: {"delta": v} for k, v in merged.items()}
        applied = update_subject_profile(db, user_id, subject_id, adjustments, source="batch")

        _update_overall_profile(db, user_id)

        # Delete processed signals
        for record in pending:
            db.delete(record)

        return applied


# ── Topic Mastery ─────────────────────────────────────────────────────────────

def get_or_create_topic_mastery(
    db: Session, user_id: str, topic_id: int
) -> TopicMastery:
    """Gets or creates a topic mastery record."""
    mastery = db.query(TopicMastery).filter(
        TopicMastery.user_id == user_id,
        TopicMastery.topic_id == topic_id,
    ).first()
    if not mastery:
        mastery = TopicMastery(
            user_id=user_id,
            topic_id=topic_id,
            first_visited=datetime.now(timezone.utc),
        )
        db.add(mastery)
        db.flush()
    return mastery


def update_topic_mastery_from_chat(
    user_id: str, topic_id: int, bloom_level: str
) -> None:
    """
    Updates topic mastery after a chat turn about this topic.
    Increments visit count, updates bloom level, and adjusts mastery.
    Appends a MasteryEvent for audit trail and sparkline charts.
    """
    bloom_map = {
        "remember": 1, "understand": 2, "apply": 3,
        "analyze": 4, "evaluate": 5, "create": 6,
    }
    bloom_num = bloom_map.get(bloom_level, 1)

    with managed_session() as db:
        mastery = get_or_create_topic_mastery(db, user_id, topic_id)
        mastery.times_visited = (mastery.times_visited or 0) + 1
        mastery.last_visited = datetime.now(timezone.utc)

        # Update bloom level (only goes up)
        if bloom_num > (mastery.bloom_level_reached or 1):
            mastery.bloom_level_reached = bloom_num

        # Nudge mastery up based on engagement (small increments per chat turn)
        mastery_boost = min(3.0, bloom_num * 0.8)
        old_mastery = mastery.mastery_level or 0
        mastery.mastery_level = _clamp(old_mastery + mastery_boost)

        # ── Append MasteryEvent for audit trail ───────────────────────────────
        db.flush()  # ensure mastery.id exists
        user_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        db.add(MasteryEvent(
            mastery_id=mastery.id,
            user_id=user_uuid,
            topic_id=topic_id,
            source="chat",
            delta=mastery_boost,
            new_value=mastery.mastery_level,
        ))


def update_topic_mastery_from_quiz(
    user_id: str, topic_id: int, quiz_score: float, passed: bool
) -> None:
    """
    Updates topic mastery after a quiz on this topic.
    Quiz results have a stronger impact than chat signals.
    Also bumps knowledge_retention and learning_velocity on the subject profile.
    Appends a MasteryEvent for audit trail and sparkline charts.
    """
    with managed_session() as db:
        mastery = get_or_create_topic_mastery(db, user_id, topic_id)
        mastery.last_quiz_score = quiz_score
        mastery.times_visited = (mastery.times_visited or 0) + 1
        mastery.last_visited = datetime.now(timezone.utc)

        # Quiz score has strong influence on mastery
        # Weighted average: 40% existing mastery + 60% quiz score
        current = mastery.mastery_level or 0
        old_mastery = current
        mastery.mastery_level = _clamp(current * 0.4 + quiz_score * 0.6)

        # Update bloom level based on score
        if quiz_score >= 85:
            mastery.bloom_level_reached = max(mastery.bloom_level_reached or 1, 4)
        elif quiz_score >= 70:
            mastery.bloom_level_reached = max(mastery.bloom_level_reached or 1, 3)
        elif quiz_score >= 50:
            mastery.bloom_level_reached = max(mastery.bloom_level_reached or 1, 2)

        # Schedule next review using spaced repetition
        _schedule_spaced_review(mastery, quiz_score, passed)

        # ── Append MasteryEvent for audit trail ───────────────────────────────
        db.flush()  # ensure mastery.id exists
        delta = mastery.mastery_level - old_mastery
        user_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        db.add(MasteryEvent(
            mastery_id=mastery.id,
            user_id=user_uuid,
            topic_id=topic_id,
            source="quiz",
            delta=delta,
            new_value=mastery.mastery_level,
        ))

        # ── Update knowledge_retention and learning_velocity via subject profile ─
        # We need the topic's subject_id to find the right subject profile
        from app.data.models.content import Topic as TopicModel, Chapter, Book
        topic_obj = db.query(TopicModel).filter(TopicModel.id == topic_id).first()
        if topic_obj:
            chapter = db.query(Chapter).filter(Chapter.id == topic_obj.chapter_id).first()
            if chapter:
                book = db.query(Book).filter(Book.id == chapter.book_id).first()
                if book and book.subject_id:
                    subject_id = book.subject_id
                    # knowledge_retention: proportional to quiz score (0-100)
                    # delta is bounded to prevent wild swings
                    kr_delta = _clamp((quiz_score - 50) * 0.1, -3.0, 5.0)  # -3 to +5 per quiz
                    # learning_velocity: based on mastery gain speed (delta / visits)
                    visits = mastery.times_visited or 1
                    lv_delta = _clamp(delta / visits * 10, -2.0, 5.0)
                    profile = _get_or_create_profile(db, user_id, subject_id)
                    profile.knowledge_retention = _clamp(
                        (profile.knowledge_retention or 50.0) + kr_delta
                    )
                    profile.learning_velocity = _clamp(
                        (profile.learning_velocity or 50.0) + lv_delta
                    )


def _schedule_spaced_review(
    mastery: TopicMastery, score: float, passed: bool
) -> None:
    """
    Implements a simplified SM-2 spaced repetition algorithm.
    Higher scores → longer intervals between reviews.
    Lower scores → shorter intervals (review sooner).
    """
    mastery.review_count = (mastery.review_count or 0) + 1

    if passed:
        # Base interval scales with review count and score
        if mastery.review_count <= 1:
            interval_days = 1
        elif mastery.review_count == 2:
            interval_days = 3
        else:
            # Exponential backoff: interval grows with each successful review
            ease_factor = max(1.3, 2.5 - (100 - score) * 0.02)
            interval_days = int(min(90, 3 * (ease_factor ** (mastery.review_count - 2))))

        mastery.decay_rate = _clamp(
            max(0, (mastery.decay_rate or 0.5) - 0.05), 0.0, 1.0
        )
    else:
        # Failed → review in 1 day, reset review count
        interval_days = 1
        mastery.review_count = 0
        mastery.decay_rate = _clamp(
            (mastery.decay_rate or 0.5) + 0.1, 0.0, 1.0
        )

    mastery.next_review_date = date.today() + timedelta(days=interval_days)


def get_student_weak_topics(user_id: str, subject_id: int | None = None) -> list[dict]:
    """Returns topics where student mastery is below 40% — these need attention."""
    from app.data.models.content import Book
    with managed_session() as db:
        query = (
            db.query(TopicMastery, Topic)
            .join(Topic, TopicMastery.topic_id == Topic.id)
            .filter(
                TopicMastery.user_id == user_id,
                TopicMastery.mastery_level < 40,
            )
        )
        if subject_id:
            query = query.join(Chapter, Topic.chapter_id == Chapter.id)\
                         .join(Book, Chapter.book_id == Book.id)\
                         .filter(Book.subject_id == subject_id)

        results = query.order_by(TopicMastery.mastery_level.asc()).limit(10).all()
        return [
            {
                "topic_id": m.TopicMastery.topic_id,
                "topic_title": m.Topic.title,
                "mastery_level": m.TopicMastery.mastery_level,
                "bloom_level": m.TopicMastery.bloom_level_reached,
                "times_visited": m.TopicMastery.times_visited,
            }
            for m in results
        ]


def get_student_strong_topics(user_id: str, subject_id: int | None = None) -> list[dict]:
    """Returns topics where student mastery is above 70%."""
    from app.data.models.content import Book
    with managed_session() as db:
        query = (
            db.query(TopicMastery, Topic)
            .join(Topic, TopicMastery.topic_id == Topic.id)
            .filter(
                TopicMastery.user_id == user_id,
                TopicMastery.mastery_level >= 70,
            )
        )
        if subject_id:
            query = query.join(Chapter, Topic.chapter_id == Chapter.id)\
                         .join(Book, Chapter.book_id == Book.id)\
                         .filter(Book.subject_id == subject_id)

        results = query.order_by(TopicMastery.mastery_level.desc()).limit(10).all()
        return [
            {
                "topic_id": m.TopicMastery.topic_id,
                "topic_title": m.Topic.title,
                "mastery_level": m.TopicMastery.mastery_level,
                "bloom_level": m.TopicMastery.bloom_level_reached,
            }
            for m in results
        ]


def get_topics_due_for_review(user_id: str) -> list[dict]:
    """Returns topics whose next_review_date is today or earlier — for spaced repetition."""
    today = date.today()
    with managed_session() as db:
        results = (
            db.query(TopicMastery, Topic)
            .join(Topic, TopicMastery.topic_id == Topic.id)
            .filter(
                TopicMastery.user_id == user_id,
                TopicMastery.next_review_date <= today,
            )
            .order_by(TopicMastery.next_review_date.asc())
            .limit(5)
            .all()
        )
        return [
            {
                "topic_id": m.TopicMastery.topic_id,
                "topic_title": m.Topic.title,
                "mastery_level": m.TopicMastery.mastery_level,
                "last_quiz_score": m.TopicMastery.last_quiz_score,
                "review_count": m.TopicMastery.review_count,
                "next_review_date": str(m.TopicMastery.next_review_date),
            }
            for m in results
        ]


# ── Streak Management ────────────────────────────────────────────────────────

def update_student_streak(user_id: str) -> dict:
    """
    Updates the student's streak based on today's activity.
    Returns the current streak info.
    """
    today = date.today()

    with managed_session() as db:
        streak = db.query(StudentStreak).filter(
            StudentStreak.user_id == user_id,
        ).first()

        if not streak:
            streak = StudentStreak(
                user_id=user_id,
                current_streak_days=1,
                longest_streak_days=1,
                last_active_date=today,
                total_active_days=1,
                total_sessions=1,
            )
            db.add(streak)
            return {
                "current_streak": 1,
                "longest_streak": 1,
                "total_active_days": 1,
            }

        if streak.last_active_date == today:
            # Already active today — just increment session count
            streak.total_sessions = (streak.total_sessions or 0) + 1
            return {
                "current_streak": streak.current_streak_days,
                "longest_streak": streak.longest_streak_days,
                "total_active_days": streak.total_active_days,
            }

        yesterday = today - timedelta(days=1)
        if streak.last_active_date == yesterday:
            # Consecutive day → extend streak
            streak.current_streak_days = (streak.current_streak_days or 0) + 1
        elif streak.last_active_date and streak.last_active_date < yesterday:
            # Streak broken → reset to 1
            streak.current_streak_days = 1
        else:
            streak.current_streak_days = 1

        streak.longest_streak_days = max(
            streak.longest_streak_days or 0, streak.current_streak_days
        )
        streak.last_active_date = today
        streak.total_active_days = (streak.total_active_days or 0) + 1
        streak.total_sessions = (streak.total_sessions or 0) + 1

        # Update last_active_at on the user record too
        student = db.query(User).filter(User.id == user_id).first()
        if student:
            student.last_active_at = datetime.now(timezone.utc)

        return {
            "current_streak": streak.current_streak_days,
            "longest_streak": streak.longest_streak_days,
            "total_active_days": streak.total_active_days,
        }


def increment_streak_questions(user_id: str) -> None:
    """Increments total_questions_asked counter on streak."""
    with managed_session() as db:
        streak = db.query(StudentStreak).filter(
            StudentStreak.user_id == user_id,
        ).first()
        if streak:
            streak.total_questions_asked = (streak.total_questions_asked or 0) + 1


def increment_streak_quizzes(user_id: str) -> None:
    """Increments total_quizzes_taken counter on streak."""
    with managed_session() as db:
        streak = db.query(StudentStreak).filter(
            StudentStreak.user_id == user_id,
        ).first()
        if streak:
            streak.total_quizzes_taken = (streak.total_quizzes_taken or 0) + 1


def get_student_streak(user_id: str) -> dict:
    """Returns the student's current streak data."""
    with managed_session() as db:
        streak = db.query(StudentStreak).filter(
            StudentStreak.user_id == user_id,
        ).first()
        if not streak:
            return {
                "current_streak": 0, "longest_streak": 0,
                "total_active_days": 0, "total_sessions": 0,
                "total_questions_asked": 0, "total_quizzes_taken": 0,
            }
        return {
            "current_streak": streak.current_streak_days or 0,
            "longest_streak": streak.longest_streak_days or 0,
            "total_active_days": streak.total_active_days or 0,
            "total_sessions": streak.total_sessions or 0,
            "total_questions_asked": streak.total_questions_asked or 0,
            "total_quizzes_taken": streak.total_quizzes_taken or 0,
        }


# ── Learning Preferences ─────────────────────────────────────────────────────

def get_learning_preferences(user_id: str) -> dict:
    """Returns the student's learning preferences. Returns defaults if none exist."""
    with managed_session() as db:
        pref = db.query(LearningPreference).filter(
            LearningPreference.user_id == user_id,
        ).first()
        if not pref:
            return {
                "prefers_examples": 0.5,
                "prefers_analogies": 0.5,
                "prefers_step_by_step": 0.5,
                "prefers_visuals": 0.5,
                "preferred_length": "medium",
                "attention_span_minutes": 50.0,
                "responds_to_encouragement": True,
            }
        return {
            "prefers_examples": pref.prefers_examples,
            "prefers_analogies": pref.prefers_analogies,
            "prefers_step_by_step": pref.prefers_step_by_step,
            "prefers_visuals": pref.prefers_visuals,
            "preferred_length": pref.preferred_length or "medium",
            "attention_span_minutes": pref.attention_span or 20,
            "responds_to_encouragement": bool(pref.responds_to_encouragement > 0.5),
        }


def nudge_learning_preference(user_id: str, key: str, delta: float) -> None:
    """
    Nudges a specific learning preference by a small delta.
    Called by the AI when it detects the student responds well/poorly
    to a particular explanation style.
    """
    with managed_session() as db:
        pref = db.query(LearningPreference).filter(
            LearningPreference.user_id == user_id,
        ).first()
        if not pref:
            pref = LearningPreference(
                user_id=user_id,
            )
            db.add(pref)
            db.flush()

        if hasattr(pref, key):
            current = getattr(pref, key) or 0.5
            setattr(pref, key, _clamp(current + delta, 0.0, 1.0))


def set_learning_preference_field(user_id: str, key: str, value) -> None:
    """Sets a field on LearningPreference (e.g. preferred_length)."""
    with managed_session() as db:
        pref = db.query(LearningPreference).filter(
            LearningPreference.user_id == user_id,
        ).first()
        if not pref:
            pref = LearningPreference(user_id=user_id)
            db.add(pref)
            db.flush()
        if hasattr(pref, key):
            setattr(pref, key, value)


def llm_update_cognitive_profile(user_id: str, subject_id: int, llm_signals: dict) -> dict:
    """
    Applies LLM-derived metric delta signals directly to the subject profile.
    Called during deep session sync to complement the per-turn regex batch update.
    llm_signals: dict of metric_key -> delta (float, positive or negative)
    Returns the adjustments applied.
    """
    if not llm_signals:
        return {}
    with managed_session() as db:
        adjustments = {k: {"delta": v} for k, v in llm_signals.items()}
        applied = update_subject_profile(db, user_id, subject_id, adjustments, source="llm_sync")
        _update_overall_profile(db, user_id)
        return applied
