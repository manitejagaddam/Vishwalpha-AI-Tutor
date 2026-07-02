"""
db/metrics.py
─────────────
Cognitive profile update logic and metrics extraction from conversations.
"""
import os
import re
import json
import logging
from core.groq_client import get_groq

logger = logging.getLogger(__name__)

BATCH_TURN_INTERVAL = 4

_FOLLOWUP_PATTERNS = re.compile(
    r"\b(why|how|what if|can you|could you|explain|clarify|tell me more|does that mean|"
    r"so (does|is|are|can)|but (why|how|what)|what about|elaborate|isn't it|wouldn't)\b",
    re.IGNORECASE
)

_ANALYTICAL_PATTERNS = re.compile(
    r"\b(compare|contrast|analyze|evaluate|differentiate|relationship between|"
    r"effect of|cause|because|therefore|conclude|prove|argue|difference between|"
    r"justify|implications|significance)\b",
    re.IGNORECASE
)

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

Output ONLY a valid JSON object with all 10 metric keys as floats, plus a "remark" string (1-2 sentences: teacher-style note on performance this batch).
Do NOT include any text before or after the JSON object.

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

def _get_practice_signal(word_count: int) -> str:
    """Determines practice signal based on word count."""
    if word_count >= 30:
        return "high"
    elif word_count >= 10:
        return "medium"
    return "low"

def _get_depth_signal(question: str, is_analytical: bool) -> str:
    """Determines depth signal based on analytical patterns and complexity."""
    has_multiple_concepts = question.count("?") >= 2 or " and " in question.lower()
    if is_analytical:
        return "high"
    elif has_multiple_concepts:
        return "medium"
    return "low"

def collect_turn_signals(
    question: str,
    answer: str,
    history: list,
    turn_number: int,
) -> dict:
    """
    Analyzes one turn and returns a signal dict to be accumulated.
    No LLM used here — purely algorithmic, never fails.
    """
    words = question.split()
    word_count = len(words)

    practice_signal = _get_practice_signal(word_count)
    is_followup = bool(_FOLLOWUP_PATTERNS.search(question))
    is_analytical = bool(_ANALYTICAL_PATTERNS.search(question))
    depth_signal = _get_depth_signal(question, is_analytical)

    recent_keywords: set[str] = set()
    if history:
        for msg in history[-6:]:
            for w in msg.content.lower().split():
                if len(w) > 5:
                    recent_keywords.add(w.rstrip(".,?!"))
    question_words = set(w.lower().rstrip(".,?!") for w in words if len(w) > 5)
    retention_overlap = len(question_words & recent_keywords)
    references_prior = retention_overlap >= 2

    avg_word_len = sum(len(w) for w in words) / max(1, len(words))
    is_rich_vocabulary = avg_word_len >= 6.0

    gave_up = bool(re.search(
        r"\b(skip|don't care|forget it|never mind|doesn't matter|just give|just tell)\b",
        question, re.IGNORECASE
    ))

    return {
        "turn": turn_number,
        "word_count": word_count,
        "practice_signal": practice_signal,
        "is_followup": is_followup,
        "depth_signal": depth_signal,
        "references_prior": references_prior,
        "is_rich_vocabulary": is_rich_vocabulary,
        "gave_up": gave_up,
        "question_preview": question[:200],
        "answer_preview": answer[:200],
    }

def append_pending_signal(db, student_id: str, subject: str, signal: dict) -> None:
    """
    Appends a signal dict to the pending_signals JSON on the subject profile.
    Does NOT call db.commit() — the caller owns the transaction.
    """
    from db.profile import get_or_create_subject_profile
    profile = get_or_create_subject_profile(db, student_id, subject)
    existing: list = json.loads(profile.pending_signals or "[]")
    existing.append(signal)
    profile.pending_signals = json.dumps(existing)

def batch_update_cognitive_profile(
    student_id: str,
    subject: str,
    db,
) -> tuple[dict, str]:
    """
    Reads pending_signals from the profile, calls the LLM for a holistic update,
    applies the resulting metric changes, and clears the signal queue.

    This function deliberately does NOT silently swallow all errors — it only
    catches TPM / network errors on the LLM call and falls back to a direct
    algorithmic update in that case. DB errors are allowed to propagate.

    Returns:
        (adjustments_dict, remark_string)
    """
    from db.profile import get_or_create_subject_profile, get_subject_metrics, update_subject_profile

    profile = get_or_create_subject_profile(db, student_id, subject)
    current_metrics = get_subject_metrics(db, student_id, subject)
    signals: list[dict] = json.loads(profile.pending_signals or "[]")

    if not signals:
        logger.info(f"No pending signals for {student_id}/{subject}, skipping batch update.")
        return {}, ""

    signals_summary_lines = []
    for s in signals:
        lines = [
            f"Turn {s.get('turn', '?')}:",
            f"  - Words: {s.get('word_count', 0)} | Practice: {s.get('practice_signal', '?')} | Depth: {s.get('depth_signal', '?')}",
            f"  - Followup: {s.get('is_followup', False)} | References prior: {s.get('references_prior', False)} | Rich vocabulary: {s.get('is_rich_vocabulary', False)} | Gave up: {s.get('gave_up', False)}",
        ]
        signals_summary_lines.extend(lines)
    signals_summary = "\n".join(signals_summary_lines)

    turns_lines = []
    for s in signals:
        turns_lines.append(f"Student: {s.get('question_preview', '')}")
        turns_lines.append(f"Tutor: {s.get('answer_preview', '')}")
        turns_lines.append("")
    turns_text = "\n".join(turns_lines)

    prompt = BATCH_UPDATE_SYSTEM_PROMPT.format(
        n_turns=len(signals),
        signals_summary=signals_summary,
        turns_text=turns_text[:3000],
        current_metrics=json.dumps(current_metrics, indent=2),
    )

    adjustments = {}
    remark = ""

    try:
        client = get_groq()
        model = os.environ.get("GROQ_MIDDLEWARE_MODEL", "llama-3.1-8b-instant")

        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.1,
            max_tokens=400,
            response_format={"type": "json_object"},
        )

        raw_content = response.choices[0].message.content.strip()
        logger.info(f"LLM metrics response: {raw_content[:200]}")
        output = json.loads(raw_content)
        remark = output.pop("remark", "")

        raw_adjustments = {}
        for key, new_val in output.items():
            if key in current_metrics:
                delta = float(new_val) - float(current_metrics[key])
                raw_adjustments[key] = {"delta": delta}

        adjustments = update_subject_profile(db, student_id, subject, raw_adjustments, source="batch")
        logger.info(f"LLM batch update applied for {student_id}/{subject}: {len(raw_adjustments)} metrics updated.")

    except Exception as e:
        logger.warning(f"LLM batch update failed, applying algorithmic fallback: {e}")
        adjustments, remark = _algorithmic_fallback_update(db, student_id, subject, signals, current_metrics)

    profile = get_or_create_subject_profile(db, student_id, subject)
    profile.pending_signals = "[]"
    db.commit()

    logger.info(f"Batch cognitive update complete for {student_id}/{subject}.")
    return adjustments, remark

def _algorithmic_fallback_update(
    db,
    student_id: str,
    subject: str,
    signals: list[dict],
    current_metrics: dict,
) -> tuple[dict, str]:
    """
    Pure algorithmic fallback when the LLM call fails.
    Computes metric adjustments directly from the collected signals.
    """
    from db.profile import update_subject_profile

    n = len(signals)
    if n == 0:
        return {}, ""

    followup_rate = sum(1 for s in signals if s.get("is_followup")) / n
    high_practice_rate = sum(1 for s in signals if s.get("practice_signal") == "high") / n
    analytical_rate = sum(1 for s in signals if s.get("depth_signal") == "high") / n
    retention_rate = sum(1 for s in signals if s.get("references_prior")) / n
    vocab_rate = sum(1 for s in signals if s.get("is_rich_vocabulary")) / n
    giveup_rate = sum(1 for s in signals if s.get("gave_up")) / n

    def adj(rate: float, scale: float = 5.0) -> float:
        return round((rate - 0.5) * scale, 2)

    raw_adjustments = {
        "attempt_persistence":   {"delta": adj(followup_rate)},
        "practice_intensity":    {"delta": adj(high_practice_rate)},
        "cognitive_thinking_level": {"delta": adj(analytical_rate)},
        "knowledge_retention":   {"delta": adj(retention_rate)},
        "engagement_frequency":  {"delta": adj(vocab_rate)},
        "concept_master_score":  {"delta": adj((1.0 - giveup_rate), 3.0)},
        "error_repetition_rate": {"delta": round(giveup_rate * 0.05, 4)},
    }

    adjustments = update_subject_profile(db, student_id, subject, raw_adjustments, source="batch")
    remark = (
        f"Algorithmic update based on {n} turns: "
        f"followup rate {followup_rate:.0%}, analytical depth {analytical_rate:.0%}."
    )
    logger.info(f"Algorithmic fallback update applied for {student_id}/{subject}.")
    return adjustments, remark

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
