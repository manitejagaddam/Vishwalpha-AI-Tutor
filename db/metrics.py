import os
import json
import logging
from groq import Groq
from db.models import ConversationSession

logger = logging.getLogger(__name__)

_groq_client: Groq | None = None

def _get_groq() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    return _groq_client

UPDATE_METRICS_SYSTEM_PROMPT = """You are an educational analytics assistant.
Your task is to analyze the latest interaction in a tutoring session and update 10 key student learning metrics.
These metrics are stored on a scale of 0.0 to 100.0 (except error_repetition_rate which is 0.0 to 1.0).

Metrics definition:
1. Concept Master Score (0-100): How well the student demonstrates mastery of the subject concepts being discussed.
2. Error Repetition Rate (0.0-1.0): The rate at which the student repeats mistakes/misunderstandings after being corrected.
3. Attempt Persistence (0-100): The student's persistence in trying to solve a problem or understand a concept despite struggle (e.g. asking follow-ups, trying again).
4. Struggle Recovery Rate (0-100): How quickly and effectively the student corrects their understanding or solves a problem when corrected or guided.
5. Practice Intensity (0-100): The depth, length, complexity, and active effort in the student's questions/practice.
6. Learning Velocity (0-100): The speed at which the student progresses through new concepts or topics.
7. Knowledge Retention (0-100): How well the student retains and correctly applies concepts discussed earlier in the session.
8. Cognitive Thinking Level (0-100): Represents the level of Bloom's Taxonomy shown in their query (e.g. 0-20: Recall, 20-40: Understand, 40-60: Apply, 60-80: Analyze, 80-100: Evaluate/Create).
9. Engagement Frequency (0-100): Active engagement level, participation rate, and response detail.
10. Assessment Accuracy (0-100): Correctness of student's answers to tutor's questions or checks.

Current metrics values:
{current_metrics}

Latest interaction:
Student: {question}
Tutor: {answer}

Based on this interaction, output the updated values for each of the 10 metrics as a JSON object. Provide ONLY the JSON. Adjust the metrics incrementally (e.g., +/- 2 to 10 points) based on evidence in the dialogue. Keep them within their limits (0.0-100.0 or 0.0-1.0). If there is no new evidence for a metric, keep its current value.

Example JSON output format:
{{
  "concept_master_score": 65.0,
  "error_repetition_rate": 0.2,
  "attempt_persistence": 75.0,
  "struggle_recovery_rate": 70.0,
  "practice_intensity": 80.0,
  "learning_velocity": 60.0,
  "knowledge_retention": 85.0,
  "cognitive_thinking_level": 55.0,
  "engagement_frequency": 90.0,
  "assessment_accuracy": 70.0
}}"""

def update_student_metrics(
    session_id: str,
    question: str,
    answer: str,
    db
) -> None:
    """
    Analyzes the latest turn and updates the student metrics stored on the session row.
    This runs inside the caller's DB session to maintain transaction safety.
    """
    try:
        session = db.query(ConversationSession).filter(ConversationSession.id == session_id).first()
        if not session:
            logger.warning(f"Session {session_id} not found for metrics update.")
            return

        # Prepare current metrics dict
        current_metrics = {
            "concept_master_score": session.concept_master_score if session.concept_master_score is not None else 50.0,
            "error_repetition_rate": session.error_repetition_rate if session.error_repetition_rate is not None else 0.0,
            "attempt_persistence": session.attempt_persistence if session.attempt_persistence is not None else 50.0,
            "struggle_recovery_rate": session.struggle_recovery_rate if session.struggle_recovery_rate is not None else 50.0,
            "practice_intensity": session.practice_intensity if session.practice_intensity is not None else 50.0,
            "learning_velocity": session.learning_velocity if session.learning_velocity is not None else 50.0,
            "knowledge_retention": session.knowledge_retention if session.knowledge_retention is not None else 50.0,
            "cognitive_thinking_level": session.cognitive_thinking_level if session.cognitive_thinking_level is not None else 50.0,
            "engagement_frequency": session.engagement_frequency if session.engagement_frequency is not None else 50.0,
            "assessment_accuracy": session.assessment_accuracy if session.assessment_accuracy is not None else 50.0
        }

        # Build prompt
        prompt = UPDATE_METRICS_SYSTEM_PROMPT.format(
            current_metrics=json.dumps(current_metrics, indent=2),
            question=question,
            answer=answer
        )

        client = _get_groq()
        model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.1,
            max_tokens=300,
        )

        output_text = response.choices[0].message.content.strip()
        
        # Parse JSON
        try:
            if "{" in output_text and "}" in output_text:
                output_text = output_text[output_text.find("{"):output_text.rfind("}")+1]
            updates = json.loads(output_text)
        except Exception as json_err:
            logger.error(f"Failed to parse LLM metrics JSON: {json_err}. Raw: {output_text}")
            return

        # Apply updates and clip values
        def clip(val, min_val=0.0, max_val=100.0):
            try:
                f_val = float(val)
                return max(min_val, min(max_val, f_val))
            except (ValueError, TypeError):
                return None

        if "concept_master_score" in updates:
            val = clip(updates["concept_master_score"])
            if val is not None: session.concept_master_score = val

        if "error_repetition_rate" in updates:
            val = clip(updates["error_repetition_rate"], 0.0, 1.0)
            if val is not None: session.error_repetition_rate = val

        if "attempt_persistence" in updates:
            val = clip(updates["attempt_persistence"])
            if val is not None: session.attempt_persistence = val

        if "struggle_recovery_rate" in updates:
            val = clip(updates["struggle_recovery_rate"])
            if val is not None: session.struggle_recovery_rate = val

        if "practice_intensity" in updates:
            val = clip(updates["practice_intensity"])
            if val is not None: session.practice_intensity = val

        if "learning_velocity" in updates:
            val = clip(updates["learning_velocity"])
            if val is not None: session.learning_velocity = val

        if "knowledge_retention" in updates:
            val = clip(updates["knowledge_retention"])
            if val is not None: session.knowledge_retention = val

        if "cognitive_thinking_level" in updates:
            val = clip(updates["cognitive_thinking_level"])
            if val is not None: session.cognitive_thinking_level = val

        if "engagement_frequency" in updates:
            val = clip(updates["engagement_frequency"])
            if val is not None: session.engagement_frequency = val

        if "assessment_accuracy" in updates:
            val = clip(updates["assessment_accuracy"])
            if val is not None: session.assessment_accuracy = val

        db.commit()
        logger.info(f"Successfully updated student metrics for session {session_id}.")

    except Exception as e:
        logger.warning(f"Student metrics update failed (non-critical): {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Cognitive Middleware & Personalisation Additions
# ─────────────────────────────────────────────────────────────────────────────

ADJUST_METRICS_SYSTEM_PROMPT = """You are a cognitive evaluation middleware for an AI Tutor.
Your task is to analyze the student's incoming message (and the recent conversation context) and decide how to adjust 10 key student learning metrics.

Current metrics values:
{current_metrics}

Recent conversation context:
{context}

Student's new message:
"{question}"

For each of the 10 metrics, you MUST decide on an adjustment: "increase", "decrease", or "constant".
Rules for adjusting:
1. Concept Master Score (0-100): Increase if the student shows correct understanding of concepts. Decrease if they state wrong facts or show complete confusion. Constant if the question is conversational or doesn't show mastery state.
2. Error Repetition Rate (0.0-1.0): Increase (+0.05 to +0.2) if they repeat a mistake or misunderstanding after the tutor JUST corrected them in the context. Decrease (-0.05 to -0.2) if they avoid a mistake or show they corrected themselves. Keep constant otherwise.
3. Attempt Persistence (0-100): Increase if they ask follow-up questions, request clarification, or try to solve a problem again. Decrease if they give up ("I don't care", "skip this"). Constant otherwise.
4. Struggle Recovery Rate (0-100): Increase if they correct their understanding after being guided/prompted. Decrease if they remain stuck or repeat errors. Constant otherwise.
5. Practice Intensity (0-100): Increase if the question is long, complex, or asks for deep explanations/problems. Decrease if it is extremely simple or low effort (e.g., single word). Constant otherwise.
6. Learning Velocity (0-100): Increase if they progress quickly to new topics. Decrease if they need multiple explanations for the same basic point. Constant otherwise.
7. Knowledge Retention (0-100): Increase if they correctly reference a concept discussed earlier in the conversation. Decrease if they forgot a concept explained just a few turns ago. Constant otherwise.
8. Cognitive Thinking Level (0-100): Estimate the level of Bloom's Taxonomy of their new query (0-20: Recall/remember facts, 20-40: Understand/explain, 40-60: Apply to new situations, 60-80: Analyze details/relations, 80-100: Evaluate/Create). Use "increase", "decrease", or "constant" relative to the current value, and set the new_value accordingly.
9. Engagement Frequency (0-100): Increase if they ask highly active, detailed questions. Decrease if their responses are minimal/passive. Constant otherwise.
10. Assessment Accuracy (0-100): Increase if they answered a check question from the tutor correctly. Decrease if they answered it incorrectly. Constant if the student did not answer an assessment check.

Output ONLY a JSON object mapping each metric to its adjustment, delta, new_value, and reason.
Ensure the delta and new_value are floats, and new_value is clipped to 0.0-100.0 (or 0.0-1.0 for error_repetition_rate).

Example JSON output format:
{{
  "concept_master_score": {{
    "adjustment": "increase",
    "delta": 5.0,
    "new_value": 55.0,
    "reason": "Student correctly applied the concept of displacement reactions."
  }},
  "error_repetition_rate": {{
    "adjustment": "constant",
    "delta": 0.0,
    "new_value": 0.2,
    "reason": "No error repeated in this turn."
  }}
}}"""


def adjust_student_metrics_pre_generation(
    session_id: str,
    question: str,
    history: list,
    memory_summary: str,
    db
) -> dict:
    """
    Cognitive middleware: analyzes the incoming question and history, updates the 10 metrics
    in the database, and returns the detailed adjustments.
    """
    try:
        session = db.query(ConversationSession).filter(ConversationSession.id == session_id).first()
        if not session:
            logger.warning(f"Session {session_id} not found for pre-generation metrics update.")
            return {}

        current_metrics = {
            "concept_master_score": session.concept_master_score if session.concept_master_score is not None else 50.0,
            "error_repetition_rate": session.error_repetition_rate if session.error_repetition_rate is not None else 0.0,
            "attempt_persistence": session.attempt_persistence if session.attempt_persistence is not None else 50.0,
            "struggle_recovery_rate": session.struggle_recovery_rate if session.struggle_recovery_rate is not None else 50.0,
            "practice_intensity": session.practice_intensity if session.practice_intensity is not None else 50.0,
            "learning_velocity": session.learning_velocity if session.learning_velocity is not None else 50.0,
            "knowledge_retention": session.knowledge_retention if session.knowledge_retention is not None else 50.0,
            "cognitive_thinking_level": session.cognitive_thinking_level if session.cognitive_thinking_level is not None else 50.0,
            "engagement_frequency": session.engagement_frequency if session.engagement_frequency is not None else 50.0,
            "assessment_accuracy": session.assessment_accuracy if session.assessment_accuracy is not None else 50.0
        }

        # Build context preview
        context_preview = ""
        if memory_summary:
            context_preview += f"Memory Summary: {memory_summary}\n"
        if history:
            context_preview += "Recent turns:\n"
            for msg in history[-4:]:
                context_preview += f"- {msg.role.capitalize()}: {msg.content}\n"

        prompt = ADJUST_METRICS_SYSTEM_PROMPT.format(
            current_metrics=json.dumps(current_metrics, indent=2),
            context=context_preview if context_preview else "(No prior context)",
            question=question
        )

        client = _get_groq()
        model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.1,
            max_tokens=600,
            response_format={"type": "json_object"}
        )

        output_text = response.choices[0].message.content.strip()
        updates = json.loads(output_text)

        # Apply updates and clip values
        def clip(val, min_val=0.0, max_val=100.0):
            try:
                f_val = float(val)
                return max(min_val, min(max_val, f_val))
            except (ValueError, TypeError):
                return None

        adjustments = {}

        for key in current_metrics.keys():
            if key in updates:
                adj_data = updates[key]
                adj_type = adj_data.get("adjustment", "constant")
                delta = float(adj_data.get("delta", 0.0))
                reason = adj_data.get("reason", "")

                min_limit = 0.0
                max_limit = 1.0 if key == "error_repetition_rate" else 100.0
                new_val = clip(adj_data.get("new_value", current_metrics[key]), min_limit, max_limit)

                if new_val is not None:
                    setattr(session, key, new_val)
                    adjustments[key] = {
                        "adjustment": adj_type,
                        "delta": delta,
                        "new_value": new_val,
                        "reason": reason
                    }

        db.commit()
        logger.info(f"Cognitive middleware: successfully adjusted metrics for session {session_id}.")
        return adjustments

    except Exception as e:
        logger.warning(f"Cognitive middleware adjustment failed (non-critical): {e}")
        return {}


def apply_profile_metrics(session_id: str, profile_name: str, db) -> dict:
    """
    Applies a predefined profile preset to the session metrics.
    """
    session = db.query(ConversationSession).filter(ConversationSession.id == session_id).first()
    if not session:
        return {}

    profiles = {
        "Standard": {
            "concept_master_score": 50.0,
            "error_repetition_rate": 0.2,
            "attempt_persistence": 50.0,
            "struggle_recovery_rate": 50.0,
            "practice_intensity": 50.0,
            "learning_velocity": 50.0,
            "knowledge_retention": 50.0,
            "cognitive_thinking_level": 50.0,
            "engagement_frequency": 50.0,
            "assessment_accuracy": 50.0,
        },
        "Struggling but Persistent": {
            "concept_master_score": 30.0,
            "error_repetition_rate": 0.4,
            "attempt_persistence": 85.0,
            "struggle_recovery_rate": 60.0,
            "practice_intensity": 40.0,
            "learning_velocity": 35.0,
            "knowledge_retention": 45.0,
            "cognitive_thinking_level": 30.0,
            "engagement_frequency": 75.0,
            "assessment_accuracy": 40.0,
        },
        "Fast Learner": {
            "concept_master_score": 80.0,
            "error_repetition_rate": 0.05,
            "attempt_persistence": 70.0,
            "struggle_recovery_rate": 80.0,
            "practice_intensity": 75.0,
            "learning_velocity": 90.0,
            "knowledge_retention": 80.0,
            "cognitive_thinking_level": 70.0,
            "engagement_frequency": 85.0,
            "assessment_accuracy": 80.0,
        },
        "Casual": {
            "concept_master_score": 45.0,
            "error_repetition_rate": 0.3,
            "attempt_persistence": 30.0,
            "struggle_recovery_rate": 40.0,
            "practice_intensity": 35.0,
            "learning_velocity": 40.0,
            "knowledge_retention": 40.0,
            "cognitive_thinking_level": 35.0,
            "engagement_frequency": 25.0,
            "assessment_accuracy": 45.0,
        }
    }

    preset = profiles.get(profile_name, profiles["Standard"])
    for key, val in preset.items():
        setattr(session, key, val)

    db.commit()
    logger.info(f"Applied profile '{profile_name}' to session {session_id}.")
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

    # 1. Concept Understanding
    concept_understanding = (concept_master + assess_accuracy) / 2.0

    # 2. Learning Effort
    learning_effort = (practice_int + persistence + engagement) / 3.0

    # 3. Learning Adaptability (error_repetition_rate is 0.0 to 1.0, so (1.0 - err_rep) * 100)
    learning_adaptability = (recovery + (1.0 - err_rep) * 100.0) / 2.0

    # 4. Knowledge Stability
    knowledge_stability = (retention + velocity) / 2.0

    # 5. Cognitive Depth
    cognitive_depth = cog_thinking

    return {
        "concept_understanding": round(concept_understanding, 1),
        "learning_effort": round(learning_effort, 1),
        "learning_adaptability": round(learning_adaptability, 1),
        "knowledge_stability": round(knowledge_stability, 1),
        "cognitive_depth": round(cognitive_depth, 1)
    }

