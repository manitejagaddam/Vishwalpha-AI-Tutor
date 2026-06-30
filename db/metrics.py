"""
db/metrics.py
─────────────
Cognitive profile update logic.

Strategy:
  1. After each turn → collect_turn_signals() runs algorithmically (no LLM, no latency).
     Signals are accumulated on the StudentSubjectProfile.pending_signals JSON field.
  2. Every BATCH_TURN_INTERVAL (4) turns → batch_update_cognitive_profile() is called.
     This sends the full 4-turn window + signals to the LLM for a holistic, accurate update.
  3. The LLM response is applied via update_subject_profile() with 0.3× chat dampening.
"""

import os
import re
import json
import logging
from groq import Groq

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
BATCH_TURN_INTERVAL = 4   # Run cognitive LLM update every N chat turns

# Followup question patterns (signal: Attempt Persistence)
_FOLLOWUP_PATTERNS = re.compile(
    r"\b(why|how|what if|can you|could you|explain|clarify|tell me more|does that mean|"
    r"so (does|is|are|can)|but (why|how|what)|what about|elaborate|isn't it|wouldn't)\b",
    re.IGNORECASE
)

# Analytical/evaluative keywords (signal: Cognitive Depth)
_ANALYTICAL_PATTERNS = re.compile(
    r"\b(compare|contrast|analyze|evaluate|differentiate|relationship between|"
    r"effect of|cause|because|therefore|conclude|prove|argue|difference between|"
    r"justify|implications|significance)\b",
    re.IGNORECASE
)

_groq_client: Groq | None = None

def _get_groq() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    return _groq_client


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Algorithmic Signal Collection (called after every turn, no LLM)
# ─────────────────────────────────────────────────────────────────────────────

def collect_turn_signals(
    question: str,
    answer: str,
    history: list,  # list of ChatMessage
    turn_number: int,
) -> dict:
    """
    Pure algorithm — no LLM, no latency.
    Analyzes one turn and returns a signal dict to be accumulated.

    Signals are stored in pending_signals on the subject profile
    and consumed by batch_update_cognitive_profile() every N turns.
    """
    words = question.split()
    word_count = len(words)

    # 1. Practice Intensity — question length as a proxy
    if word_count >= 30:
        practice_signal = "high"
    elif word_count >= 10:
        practice_signal = "medium"
    else:
        practice_signal = "low"

    # 2. Attempt Persistence — followup patterns
    is_followup = bool(_FOLLOWUP_PATTERNS.search(question))

    # 3. Cognitive Depth — analytical keywords
    is_analytical = bool(_ANALYTICAL_PATTERNS.search(question))
    has_multiple_concepts = question.count("?") >= 2 or " and " in question.lower()

    if is_analytical:
        depth_signal = "high"
    elif has_multiple_concepts:
        depth_signal = "medium"
    else:
        depth_signal = "low"

    # 4. Knowledge Retention — did question reference any recent keywords?
    recent_keywords: set[str] = set()
    if history:
        for msg in history[-6:]:  # last 3 pairs
            for w in msg.content.lower().split():
                if len(w) > 5:  # skip filler words
                    recent_keywords.add(w.rstrip(".,?!"))
    question_words = set(w.lower().rstrip(".,?!") for w in words if len(w) > 5)
    retention_overlap = len(question_words & recent_keywords)
    references_prior = retention_overlap >= 2

    # 5. Average word length — vocabulary richness → engagement proxy
    avg_word_len = sum(len(w) for w in words) / max(1, len(words))
    is_rich_vocabulary = avg_word_len >= 6.0

    # 6. Gave up / disengaged signals
    gave_up = bool(re.search(
        r"\b(skip|don't care|forget it|never mind|doesn't matter|just give|just tell)\b",
        question, re.IGNORECASE
    ))

    return {
        "turn": turn_number,
        "word_count": word_count,
        "practice_signal": practice_signal,      # "low" / "medium" / "high"
        "is_followup": is_followup,              # bool
        "depth_signal": depth_signal,            # "low" / "medium" / "high"
        "references_prior": references_prior,    # bool
        "is_rich_vocabulary": is_rich_vocabulary,# bool
        "gave_up": gave_up,                      # bool
        "question_preview": question[:200],      # for LLM context
        "answer_preview": answer[:200],          # for LLM context
    }


def append_pending_signal(db, student_id: str, subject: str, signal: dict) -> None:
    """Appends a signal dict to the pending_signals JSON on the subject profile."""
    from db.profile import get_or_create_subject_profile
    profile = get_or_create_subject_profile(db, student_id, subject)
    existing = json.loads(profile.pending_signals or "[]")
    existing.append(signal)
    profile.pending_signals = json.dumps(existing)
    db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Batch LLM Cognitive Update (called every BATCH_TURN_INTERVAL turns)
# ─────────────────────────────────────────────────────────────────────────────

BATCH_UPDATE_SYSTEM_PROMPT = """You are an expert educational analytics AI for an AI Tutor platform.
You have observed a student over the last {n_turns} conversation turns and collected the following signals:

ACCUMULATED ALGORITHMIC SIGNALS:
{signals_summary}

RECENT CONVERSATION TURNS (last {n_turns}):
{turns_text}

CURRENT METRIC VALUES:
{current_metrics}

Your task: Holistically update the 10 cognitive metrics based on this evidence.
Each metric is on a scale of 0-100 (except error_repetition_rate: 0.0-1.0).
Apply incremental changes — typically ±3 to ±10 points per batch. Do NOT make large jumps.

Metric definitions:
1. concept_master_score: Overall conceptual understanding quality in their questions/answers.
2. error_repetition_rate (0-1): Rate of repeating the same mistakes. High signals = bad. 
3. attempt_persistence: Persistence shown — followup questions, re-asking, clarifying.
4. struggle_recovery_rate: Speed of correcting understanding after being guided.
5. practice_intensity: Depth/effort of questions (length, complexity, follow-ups).
6. learning_velocity: Speed of moving to new topics vs. staying stuck.
7. knowledge_retention: Referencing prior discussion correctly.
8. cognitive_thinking_level: Bloom's taxonomy level (0-20: Recall, 20-40: Understand, 40-60: Apply, 60-80: Analyze, 80-100: Evaluate/Create).
9. engagement_frequency: Active and detailed participation level.
10. assessment_accuracy: Correctness when answering direct tutor questions.

Output ONLY a JSON object with all 10 metric keys as floats, plus a "remark" string (1-2 sentences: teacher-style note on performance this batch).

Example:
{{
  "concept_master_score": 55.0,
  "error_repetition_rate": 0.1,
  "attempt_persistence": 70.0,
  "struggle_recovery_rate": 60.0,
  "practice_intensity": 65.0,
  "learning_velocity": 55.0,
  "knowledge_retention": 60.0,
  "cognitive_thinking_level": 45.0,
  "engagement_frequency": 75.0,
  "assessment_accuracy": 50.0,
  "remark": "Student showed strong engagement and referenced prior concepts well. Encourage deeper analysis-level questions next."
}}"""


def batch_update_cognitive_profile(
    student_id: str,
    subject: str,
    db,
) -> tuple[dict, str]:
    """
    Called every BATCH_TURN_INTERVAL turns.
    Reads pending_signals from the profile, calls LLM with full context,
    and applies the updates via profile layer with 0.3× chat dampening.

    Returns (adjustments_dict, remark_string).
    """
    from db.profile import get_or_create_subject_profile, get_subject_metrics, update_subject_profile

    try:
        profile = get_or_create_subject_profile(db, student_id, subject)
        current_metrics = get_subject_metrics(db, student_id, subject)
        signals: list[dict] = json.loads(profile.pending_signals or "[]")

        if not signals:
            logger.info(f"No pending signals for {student_id}/{subject}, skipping batch update.")
            return {}, ""

        # Build signals summary for the prompt
        signals_summary_lines = []
        for s in signals:
            lines = [
                f"Turn {s.get('turn', '?')}:",
                f"  - Words: {s.get('word_count', 0)} | Practice: {s.get('practice_signal', '?')} | Depth: {s.get('depth_signal', '?')}",
                f"  - Followup: {s.get('is_followup', False)} | References prior: {s.get('references_prior', False)} | Rich vocabulary: {s.get('is_rich_vocabulary', False)} | Gave up: {s.get('gave_up', False)}",
            ]
            signals_summary_lines.extend(lines)
        signals_summary = "\n".join(signals_summary_lines)

        # Build turns text
        turns_lines = []
        for s in signals:
            turns_lines.append(f"Student: {s.get('question_preview', '')}")
            turns_lines.append(f"Tutor: {s.get('answer_preview', '')}")
            turns_lines.append("")
        turns_text = "\n".join(turns_lines)

        prompt = BATCH_UPDATE_SYSTEM_PROMPT.format(
            n_turns=len(signals),
            signals_summary=signals_summary,
            turns_text=turns_text,
            current_metrics=json.dumps(current_metrics, indent=2),
        )

        client = _get_groq()
        model = os.environ.get("GROQ_MIDDLEWARE_MODEL", "llama-3.1-8b-instant")

        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.1,
            max_tokens=400,
            response_format={"type": "json_object"},
        )

        output = json.loads(response.choices[0].message.content.strip())

        # Extract remark before passing metrics to profile update
        remark = output.pop("remark", "")

        # Apply updates with chat dampening (0.3×) through profile layer
        # Convert absolute values to deltas for the profile layer
        raw_adjustments = {}
        for key, new_val in output.items():
            if key in current_metrics:
                raw_adjustments[key] = {"delta": float(new_val) - float(current_metrics[key])}

        adjustments = update_subject_profile(db, student_id, subject, raw_adjustments, source="chat")

        # Clear pending signals after successful batch update
        profile = get_or_create_subject_profile(db, student_id, subject)
        profile.pending_signals = "[]"
        db.commit()

        logger.info(f"Batch cognitive update complete for {student_id}/{subject}. Remark: {remark[:80]}...")
        return adjustments, remark

    except Exception as e:
        logger.warning(f"Batch cognitive update failed (non-critical): {e}")
        return {}, ""


# ─────────────────────────────────────────────────────────────────────────────
# Profile Preset Application
# ─────────────────────────────────────────────────────────────────────────────

def apply_profile_metrics(student_id: str, subject: str, profile_name: str, db) -> dict:
    """
    Applies a predefined profile preset to the subject profile metrics.
    """
    from db.profile import get_or_create_subject_profile, recompute_overall_profile

    profile = get_or_create_subject_profile(db, student_id, subject)

    profiles = {
        "Standard": {
            "concept_master_score": 50.0, "error_repetition_rate": 0.0,
            "attempt_persistence": 50.0, "struggle_recovery_rate": 50.0,
            "practice_intensity": 50.0, "learning_velocity": 50.0,
            "knowledge_retention": 50.0, "cognitive_thinking_level": 50.0,
            "engagement_frequency": 50.0, "assessment_accuracy": 50.0,
        },
        "Struggling but Persistent": {
            "concept_master_score": 30.0, "error_repetition_rate": 0.15,
            "attempt_persistence": 85.0, "struggle_recovery_rate": 40.0,
            "practice_intensity": 70.0, "learning_velocity": 25.0,
            "knowledge_retention": 45.0, "cognitive_thinking_level": 40.0,
            "engagement_frequency": 80.0, "assessment_accuracy": 35.0,
        },
        "Fast Learner": {
            "concept_master_score": 85.0, "error_repetition_rate": 0.05,
            "attempt_persistence": 60.0, "struggle_recovery_rate": 80.0,
            "practice_intensity": 75.0, "learning_velocity": 90.0,
            "knowledge_retention": 80.0, "cognitive_thinking_level": 70.0,
            "engagement_frequency": 85.0, "assessment_accuracy": 80.0,
        },
        "Casual": {
            "concept_master_score": 45.0, "error_repetition_rate": 0.3,
            "attempt_persistence": 30.0, "struggle_recovery_rate": 40.0,
            "practice_intensity": 35.0, "learning_velocity": 40.0,
            "knowledge_retention": 40.0, "cognitive_thinking_level": 35.0,
            "engagement_frequency": 25.0, "assessment_accuracy": 45.0,
        },
    }

    preset = profiles.get(profile_name, profiles["Standard"])
    for key, val in preset.items():
        setattr(profile, key, val)

    db.commit()
    recompute_overall_profile(db, student_id)
    logger.info(f"Applied profile '{profile_name}' to student {student_id}, subject {subject}.")
    return preset


# ─────────────────────────────────────────────────────────────────────────────
# Cognitive Skills Computation
# ─────────────────────────────────────────────────────────────────────────────

def compute_cognitive_skills(metrics: dict) -> dict:
    """
    Computes 5 high-level cognitive skills from 10 raw metrics.
    All returned values are percentages (0.0 to 100.0).
    """
    concept_master = metrics.get("concept_master_score", 50.0)
    assess_accuracy = metrics.get("assessment_accuracy", 50.0)
    practice_int = metrics.get("practice_intensity", 50.0)
    persistence = metrics.get("attempt_persistence", 50.0)
    engagement = metrics.get("engagement_frequency", 50.0)
    recovery = metrics.get("struggle_recovery_rate", 50.0)
    err_rep = metrics.get("error_repetition_rate", 0.0)
    retention = metrics.get("knowledge_retention", 50.0)
    velocity = metrics.get("learning_velocity", 50.0)
    cog_thinking = metrics.get("cognitive_thinking_level", 50.0)

    return {
        "concept_understanding": round((concept_master + assess_accuracy) / 2.0, 1),
        "learning_effort": round((practice_int + persistence + engagement) / 3.0, 1),
        "learning_adaptability": round((recovery + (1.0 - err_rep) * 100.0) / 2.0, 1),
        "knowledge_stability": round((retention + velocity) / 2.0, 1),
        "cognitive_depth": round(cog_thinking, 1),
    }
