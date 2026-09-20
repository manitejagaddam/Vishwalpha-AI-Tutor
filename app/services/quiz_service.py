"""
app/services/quiz_service.py
──────────────────────────────
LLM-powered quiz generation and concept-completion detection.

Features:
  - generate_quiz(): Produces a mixed MCQ + theory question set via Groq.
    Difficulty adapts dynamically from cognitive profile metrics.
    Now includes Bloom's taxonomy level and difficulty per question.
  - detect_concept_completion(): Scans tutor response for topic-completion signals.
  - generate_quiz_ai_feedback(): Generates a paragraph of AI feedback after a quiz.
  - apply_quiz_cognitive_impact(): Updates subject cognitive profile + memory
    based on quiz results.
"""
import re
import json
import logging

from app.infra.azure_openai_client import get_openai
from app.config import settings

logger = logging.getLogger(__name__)

# ── Concept-completion detector ────────────────────────────────────────────────

_COMPLETION_PATTERNS = re.compile(
    r"\b(in summary|to summarise|to recap|let's recap|now you (know|understand|have learned|"
    r"can see)|we've covered|we have covered|that covers|that's (all|the|everything) about|"
    r"this completes|by the end of (this|today)|great job|well done|you've now|"
    r"in conclusion|to conclude|with this (we|you)|test your (knowledge|understanding)|"
    r"practice (question|quiz|problem)|try (these|this))\b",
    re.IGNORECASE,
)

def detect_concept_completion(answer_text: str, routed_topic: str = "") -> tuple[bool, str]:
    """
    Scans the tutor's answer for signals that a concept/topic explanation is complete.

    Returns:
        (is_complete: bool, topic_name: str)
    """
    if len(answer_text) < 300:
        return False, ""

    if _COMPLETION_PATTERNS.search(answer_text):
        return True, routed_topic or _extract_topic_from_answer(answer_text)

    # Heuristic: long structured answer (>= 4 markdown sections) implies complete explanation
    headings = re.findall(r"^#{1,3}\s+.+", answer_text, re.MULTILINE)
    if len(headings) >= 3:
        return True, routed_topic or _extract_topic_from_answer(answer_text)

    return False, ""


def _extract_topic_from_answer(text: str) -> str:
    """Best-effort topic extraction from the first heading in the answer."""
    match = re.search(r"^#{1,3}\s+(.+)", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


# ── Quiz generation ───────────────────────────────────────────────────────────

_QUIZ_GENERATION_PROMPT = """\
You are an expert NCERT curriculum teacher creating a personalised quiz.

Student Profile:
- Subject: {subject}
- Topic: {topic}
- Class: {class_num}
- Concept mastery score: {concept_score}/100
- Cognitive thinking level: {thinking_level}/100
- Assessment accuracy: {assessment_accuracy}/100
- Known weak areas from memory: {weak_topics}

Student memory (persistent facts about this student):
{student_memory}

Generate exactly {num_questions} questions on "{topic}" for a Class {class_num} {subject} student.
Mix question types:
  - 60-70% MCQ: 4 options (A/B/C/D), one correct
  - 30-40% Theory: short-answer questions expecting 2-4 sentence answers

Difficulty calibration:
  - If concept_score < 40 → mostly recall/definition questions (Bloom's: Remember/Understand)
  - If concept_score 40-70 → mix of application and comprehension (Apply/Analyze)
  - If concept_score > 70 → higher-order thinking: evaluate, create, compare (Evaluate/Create)
  - ALWAYS include at least 1 real-life application or India-context question.

Output ONLY a valid JSON array. No other text.
Each element must have these exact keys:
  - "q_type": "mcq" or "theory"
  - "question": the question text (string)
  - "options": list of 4 strings for MCQ, null for theory
  - "correct_index": 0-based index for MCQ, null for theory
  - "correct_answer": null for MCQ, model answer string for theory
  - "explanation": brief explanation of the correct answer (1-2 sentences)
  - "difficulty": "easy" or "medium" or "hard"
  - "bloom_level": one of "remember", "understand", "apply", "analyze", "evaluate", "create"

Example MCQ:
{{"q_type":"mcq","question":"Which gas is produced during photosynthesis?","options":["Carbon dioxide","Oxygen","Nitrogen","Hydrogen"],"correct_index":1,"correct_answer":null,"explanation":"Plants release oxygen as a by-product of splitting water molecules during the light reaction.","difficulty":"easy","bloom_level":"remember"}}

Example theory:
{{"q_type":"theory","question":"Explain why leaves appear green. Use the concept of chlorophyll.","options":null,"correct_index":null,"correct_answer":"Leaves contain chlorophyll which absorbs red and blue light but reflects green light, making them appear green.","explanation":"Chlorophyll is the primary pigment in leaves and its molecular structure selectively reflects green wavelengths.","difficulty":"medium","bloom_level":"understand"}}

JSON array:
"""


def generate_quiz(
    subject: str,
    topic: str,
    class_num: int,
    student_memory: str,
    cognitive_metrics: dict,
    weak_topics: list[str] | None = None,
    num_questions: int = 7,
) -> list[dict]:
    """
    Calls Groq LLM to generate a personalised quiz.

    Returns a list of question dicts ready to be stored in QuizQuestion rows.
    Now includes difficulty and bloom_level per question.
    Falls back to a minimal stub on LLM failure so the UI never crashes.
    """
    client = get_openai()

    concept_score = cognitive_metrics.get("concept_master_score", 50)
    thinking_level = cognitive_metrics.get("cognitive_thinking_level", 50)
    assessment_accuracy = cognitive_metrics.get("assessment_accuracy", 50)
    weak_str = ", ".join(weak_topics or []) if weak_topics else "none identified"

    prompt = _QUIZ_GENERATION_PROMPT.format(
        subject=subject,
        topic=topic,
        class_num=class_num,
        concept_score=round(concept_score, 1),
        thinking_level=round(thinking_level, 1),
        assessment_accuracy=round(assessment_accuracy, 1),
        student_memory=student_memory or "(no memory yet)",
        weak_topics=weak_str,
        num_questions=num_questions,
    )

    try:
        resp = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            temperature=0.6,
            max_completion_tokens=3000,
        )
        raw = resp.choices[0].message.content.strip()

        # Extract JSON array robustly
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1:
            raise ValueError("No JSON array found in LLM response")

        questions = json.loads(raw[start:end + 1])

        # Validate and normalise each question
        validated = []
        for q in questions[:num_questions]:
            if not q.get("question"):
                continue
            q_type = q.get("q_type", "mcq")
            validated.append({
                "q_type": q_type,
                "question": q["question"],
                "options": q.get("options") if q_type == "mcq" else None,
                "correct_index": q.get("correct_index") if q_type == "mcq" else None,
                "correct_answer": q.get("correct_answer") if q_type == "theory" else None,
                "explanation": q.get("explanation", ""),
                "difficulty": q.get("difficulty", "medium"),
                "bloom_level": q.get("bloom_level", "remember"),
            })

        if not validated:
            raise ValueError("LLM returned empty question list")

        logger.info(f"Generated {len(validated)} questions for {subject}/{topic}")
        return validated

    except Exception as exc:
        logger.error(f"Quiz generation failed: {exc}")
        # Minimal fallback so the feature doesn't break completely
        return _fallback_questions(subject, topic, num_questions)


def _fallback_questions(subject: str, topic: str, num_questions: int) -> list[dict]:
    """Emergency fallback questions when LLM fails."""
    return [
        {
            "q_type": "mcq",
            "question": f"Which of the following best describes '{topic}' in {subject}?",
            "options": [
                "A fundamental concept in this subject",
                "An unrelated term",
                "A historical event",
                "A measurement unit",
            ],
            "correct_index": 0,
            "correct_answer": None,
            "explanation": f"{topic} is a key concept in {subject}.",
            "difficulty": "easy",
            "bloom_level": "remember",
        }
    ] * min(num_questions, 3)


# ── AI Feedback generation ────────────────────────────────────────────────────

_FEEDBACK_PROMPT = """\
You are a supportive NCERT teacher reviewing a student's quiz performance.

Student: Class {class_num}, {subject}
Topic tested: {topic}
Score: {score}/100 ({correct}/{total} questions correct)
MCQ accuracy: {mcq_accuracy}%
Theory accuracy: {theory_accuracy}%
Questions answered incorrectly: {wrong_questions}

Write a personalised 3-4 sentence feedback paragraph for the student.
Be specific, constructive, and encouraging. Mention what they got right, what needs work, and one concrete study tip.
Address the student directly (use "you" / "your").
"""


def generate_quiz_ai_feedback(
    subject: str,
    topic: str,
    class_num: int,
    score: float,
    correct: int,
    total: int,
    mcq_accuracy: float,
    theory_accuracy: float,
    wrong_questions: list[str],
) -> str:
    """Generates a personalised AI feedback paragraph after quiz completion."""
    client = get_openai()
    wrong_str = "\n".join(f"- {q}" for q in wrong_questions[:5]) if wrong_questions else "None"

    prompt = _FEEDBACK_PROMPT.format(
        class_num=class_num,
        subject=subject,
        topic=topic,
        score=round(score, 1),
        correct=correct,
        total=total,
        mcq_accuracy=round(mcq_accuracy, 1),
        theory_accuracy=round(theory_accuracy, 1),
        wrong_questions=wrong_str,
    )

    try:
        resp = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            temperature=0.4,
            max_completion_tokens=200,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning(f"Quiz AI feedback generation failed: {exc}")
        return ""


# ── Cognitive impact from quiz results ────────────────────────────────────────

def compute_quiz_cognitive_signals(
    score: float,
    mcq_accuracy: float,
    theory_accuracy: float,
    num_questions: int,
    passed: bool,
) -> dict:
    """
    Computes metric delta signals to apply to the cognitive profile after a quiz.

    High score → boosts concept_master_score, assessment_accuracy, knowledge_retention
    Low score  → reduces concept_master_score, increases error_repetition_rate
    Completing the quiz → boosts attempt_persistence, engagement_frequency
    """
    signals: dict[str, float] = {}

    # Always: student attempted = engagement + persistence
    signals["engagement_frequency"] = 2.0
    signals["attempt_persistence"] = 2.0

    # Score-based signals
    normalised_score = score / 100.0  # 0.0 – 1.0

    if passed:
        signals["concept_master_score"] = round(3.0 * normalised_score, 2)
        signals["assessment_accuracy"] = round(4.0 * normalised_score, 2)
        signals["knowledge_retention"] = round(2.0 * normalised_score, 2)
        signals["struggle_recovery_rate"] = 1.0
    else:
        signals["concept_master_score"] = round(-2.0 * (1 - normalised_score), 2)
        signals["assessment_accuracy"] = round(-1.0 * (1 - normalised_score), 2)
        signals["error_repetition_rate"] = round(0.05 * (1 - normalised_score), 3)

    # Theory questions boost higher-order thinking
    if theory_accuracy > 60:
        signals["cognitive_thinking_level"] = round(theory_accuracy / 25, 2)

    # High MCQ accuracy → strong recall
    if mcq_accuracy > 70:
        signals["learning_velocity"] = round(mcq_accuracy / 30, 2)

    return signals
