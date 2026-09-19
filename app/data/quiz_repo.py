"""
app/data/quiz_repo.py
─────────────────────
All DB operations for the quiz / assignment system.

Responsibilities:
  - Create and manage quiz attempts (QuizAttempt)
  - Bulk-insert and retrieve quiz questions (QuizQuestion)
  - Record student answers and compute correctness
  - Finish an attempt (compute final score)
  - Maintain per-subject aggregated feedback (SubjectQuizFeedback)
  - Detect yesterday's session context for session-start prompts
  - Update topic mastery after quiz completion
  - Update session topic tracking
"""
import uuid
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.data.database import managed_session
from app.data.models import (
    QuizAttempt,
    QuizQuestion,
    SubjectQuizFeedback,
    ConversationSession,
    ConversationMessage,
)

logger = logging.getLogger(__name__)


# ── Quiz Attempt CRUD ─────────────────────────────────────────────────────────

def create_quiz_attempt(
    student_id: str,
    subject: str,
    topic: str,
    source: str,               # 'mid_concept' | 'yesterday' | 'manual' | 'spaced_review'
    session_id: str | None = None,
    num_questions: int = 7,
) -> str:
    """Creates a new quiz attempt and returns its UUID."""
    attempt_id = str(uuid.uuid4())
    with managed_session() as db:
        db.add(QuizAttempt(
            id=attempt_id,
            student_id=student_id,
            session_id=session_id,
            subject=subject,
            topic=topic,
            source=source,
            num_questions=num_questions,
        ))
    return attempt_id


def save_quiz_questions(attempt_id: str, questions: list[dict]) -> list[int]:
    """
    Bulk-inserts a list of question dicts into quiz_questions.
    Each dict has keys: q_type, question, options (list), correct_index,
    correct_answer, explanation, difficulty, bloom_level.
    Returns list of inserted question IDs.
    """
    with managed_session() as db:
        inserted = []
        for idx, q in enumerate(questions):
            row = QuizQuestion(
                attempt_id=attempt_id,
                q_index=idx,
                q_type=q.get("q_type", "mcq"),
                question=q["question"],
                options=json.dumps(q.get("options") or []),
                correct_index=q.get("correct_index"),
                correct_answer=q.get("correct_answer"),
                explanation=q.get("explanation", ""),
                difficulty=q.get("difficulty", "medium"),
                bloom_level=q.get("bloom_level", "remember"),
            )
            db.add(row)
            db.flush()
            inserted.append(row.id)
        return inserted


def get_quiz_questions(attempt_id: str) -> list[dict]:
    """Returns all questions for an attempt (without answers — safe for frontend)."""
    with managed_session() as db:
        rows = (
            db.query(QuizQuestion)
            .filter(QuizQuestion.attempt_id == attempt_id)
            .order_by(QuizQuestion.q_index)
            .all()
        )
        result = []
        for r in rows:
            result.append({
                "id": r.id,
                "q_index": r.q_index,
                "q_type": r.q_type,
                "question": r.question,
                "options": json.loads(r.options) if r.options else [],
                "explanation": r.explanation,
                "difficulty": r.difficulty,
                "bloom_level": r.bloom_level,
                # Note: correct_index / correct_answer NOT sent here
            })
        return result


def submit_quiz_answer(
    question_id: int,
    student_answer: str,          # For MCQ: "0"/"1"/"2"/"3"; for theory: free text
    student_answer_index: int | None = None,  # For MCQ
    time_taken_ms: int | None = None,
) -> dict:
    """
    Records a student's answer for a single question.
    Returns {is_correct, correct_index, correct_answer, explanation}.
    """
    with managed_session() as db:
        q = db.query(QuizQuestion).filter(QuizQuestion.id == question_id).first()
        if not q:
            raise ValueError(f"Question {question_id} not found")

        q.student_answer = student_answer
        if time_taken_ms is not None:
            q.time_taken_ms = time_taken_ms

        if q.q_type == "mcq":
            q.is_correct = (student_answer_index is not None and
                            student_answer_index == q.correct_index)
        else:
            # Theory: mark as correct if student submitted a non-empty answer
            # (AI-graded correctness is tracked via score at finish)
            q.is_correct = bool(student_answer.strip())

        return {
            "is_correct": q.is_correct,
            "correct_index": q.correct_index,
            "correct_answer": q.correct_answer,
            "explanation": q.explanation or "",
        }


def finish_quiz_attempt(attempt_id: str) -> dict:
    """
    Finalises the attempt: computes score from answered questions.
    Returns {score, total, correct, passed, topic, subject, student_id}.
    """
    with managed_session() as db:
        attempt = db.query(QuizAttempt).filter(QuizAttempt.id == attempt_id).first()
        if not attempt:
            raise ValueError(f"Attempt {attempt_id} not found")

        questions = (
            db.query(QuizQuestion)
            .filter(QuizQuestion.attempt_id == attempt_id)
            .all()
        )

        answered = [q for q in questions if q.is_correct is not None]
        correct = sum(1 for q in answered if q.is_correct)
        total = len(questions)
        score = round((correct / total) * 100, 1) if total else 0.0
        passed = score >= 60.0

        attempt.score = score
        attempt.passed = passed
        attempt.finished_at = datetime.now(timezone.utc)

        return {
            "attempt_id": attempt_id,
            "score": score,
            "total": total,
            "correct": correct,
            "passed": passed,
            "topic": attempt.topic or "",
            "subject": attempt.subject,
            "student_id": attempt.student_id,
        }


def get_attempt_details(attempt_id: str) -> dict | None:
    """Full attempt data including all answered questions."""
    with managed_session() as db:
        attempt = db.query(QuizAttempt).filter(QuizAttempt.id == attempt_id).first()
        if not attempt:
            return None
        questions = (
            db.query(QuizQuestion)
            .filter(QuizQuestion.attempt_id == attempt_id)
            .order_by(QuizQuestion.q_index)
            .all()
        )
        return {
            "id": attempt.id,
            "subject": attempt.subject,
            "topic": attempt.topic,
            "source": attempt.source,
            "score": attempt.score,
            "passed": attempt.passed,
            "questions": [
                {
                    "q_index": q.q_index,
                    "q_type": q.q_type,
                    "question": q.question,
                    "options": json.loads(q.options) if q.options else [],
                    "correct_index": q.correct_index,
                    "correct_answer": q.correct_answer,
                    "explanation": q.explanation,
                    "student_answer": q.student_answer,
                    "is_correct": q.is_correct,
                    "difficulty": q.difficulty,
                    "bloom_level": q.bloom_level,
                    "time_taken_ms": q.time_taken_ms,
                }
                for q in questions
            ],
        }


# ── Subject Quiz Feedback (aggregated) ───────────────────────────────────────

def update_subject_quiz_feedback(
    student_id: str,
    subject: str,
    attempt_result: dict,
    questions: list[dict],
    ai_feedback: str = "",
) -> None:
    """
    Upserts the SubjectQuizFeedback row for this student/subject.
    Recomputes cumulative stats and updates weak/strong topic lists.

    attempt_result: output of finish_quiz_attempt()
    questions: full question rows with is_correct + q_type + student_answer
    """
    with managed_session() as db:
        feedback = db.query(SubjectQuizFeedback).filter(
            SubjectQuizFeedback.student_id == student_id,
            SubjectQuizFeedback.subject == subject,
        ).first()

        if not feedback:
            feedback = SubjectQuizFeedback(
                id=str(uuid.uuid4()),
                student_id=student_id,
                subject=subject,
            )
            db.add(feedback)

        total_q = attempt_result["total"]
        correct_q = attempt_result["correct"]
        score = attempt_result["score"]
        topic = attempt_result.get("topic", "")

        # Cumulative stats
        feedback.total_attempts = (feedback.total_attempts or 0) + 1
        feedback.total_questions = (feedback.total_questions or 0) + total_q
        feedback.total_correct = (feedback.total_correct or 0) + correct_q

        # Recompute avg score
        prev_total = feedback.total_attempts - 1
        old_avg = feedback.avg_score or 0.0
        feedback.avg_score = round(
            (old_avg * prev_total + score) / feedback.total_attempts, 2
        )

        # MCQ vs theory accuracy
        mcq_qs = [q for q in questions if q.get("q_type") == "mcq" and q.get("is_correct") is not None]
        theory_qs = [q for q in questions if q.get("q_type") == "theory" and q.get("is_correct") is not None]

        if mcq_qs:
            mcq_correct = sum(1 for q in mcq_qs if q.get("is_correct"))
            feedback.mcq_accuracy = round(
                (
                    ((feedback.mcq_accuracy or 0) * prev_total) + (mcq_correct / len(mcq_qs) * 100)
                ) / feedback.total_attempts, 2
            )
        if theory_qs:
            theory_correct = sum(1 for q in theory_qs if q.get("is_correct"))
            feedback.theory_accuracy = round(
                (
                    ((feedback.theory_accuracy or 0) * prev_total) + (theory_correct / len(theory_qs) * 100)
                ) / feedback.total_attempts, 2
            )

        # Topic tracking
        if topic:
            try:
                weak = json.loads(feedback.weak_topics or "[]")
                strong = json.loads(feedback.strong_topics or "[]")
            except Exception:
                weak, strong = [], []

            if score < 50 and topic not in weak:
                weak.append(topic)
                if topic in strong:
                    strong.remove(topic)
            elif score >= 70 and topic not in strong:
                strong.append(topic)
                if topic in weak:
                    weak.remove(topic)

            feedback.weak_topics = json.dumps(weak[-10:])
            feedback.strong_topics = json.dumps(strong[-10:])

        if ai_feedback:
            feedback.ai_feedback = ai_feedback


# ── Yesterday-context detection ───────────────────────────────────────────────

def get_yesterday_session_context(student_id: str) -> dict | None:
    """
    Checks if the student had a session yesterday (between 18h and 48h ago).
    Returns {subject, topic, session_date, session_id} or None.
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=48)
    window_end   = now - timedelta(hours=18)

    with managed_session() as db:
        session = (
            db.query(ConversationSession)
            .filter(
                ConversationSession.student_id == student_id,
                ConversationSession.created_at >= window_start,
                ConversationSession.created_at <= window_end,
                ConversationSession.last_topic_name.isnot(None),
            )
            .order_by(ConversationSession.created_at.desc())
            .first()
        )

        if not session or not session.last_topic_name:
            return None

        return {
            "subject": session.subject or "General",
            "topic": session.last_topic_name,
            "session_date": session.created_at.strftime("%d %b %Y") if session.created_at else "",
            "session_id": session.id,
        }


def update_session_topic(session_id: str, topic_name: str) -> None:
    """
    Updates topics_covered + last_topic_name on a session when a new topic is routed.
    """
    with managed_session() as db:
        session = db.query(ConversationSession).filter(
            ConversationSession.id == session_id
        ).first()
        if not session:
            return

        try:
            covered = json.loads(session.topics_covered or "[]")
        except Exception:
            covered = []

        if topic_name and topic_name not in covered:
            covered.append(topic_name)
            session.topics_covered = json.dumps(covered)

        session.last_topic_name = topic_name


# ── Quiz history ──────────────────────────────────────────────────────────────

def get_quiz_history(student_id: str, subject: str | None = None) -> list[dict]:
    """Returns summary of past quiz attempts, most recent first."""
    with managed_session() as db:
        query = db.query(QuizAttempt).filter(QuizAttempt.student_id == student_id)
        if subject:
            query = query.filter(QuizAttempt.subject == subject)
        attempts = query.order_by(QuizAttempt.created_at.desc()).limit(20).all()
        return [
            {
                "id": a.id,
                "subject": a.subject,
                "topic": a.topic,
                "source": a.source,
                "score": a.score,
                "passed": a.passed,
                "num_questions": a.num_questions,
                "finished_at": a.finished_at.isoformat() if a.finished_at else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in attempts
        ]


def get_subject_quiz_feedback(student_id: str, subject: str) -> dict | None:
    """Returns the aggregated quiz feedback record for a student/subject."""
    with managed_session() as db:
        f = db.query(SubjectQuizFeedback).filter(
            SubjectQuizFeedback.student_id == student_id,
            SubjectQuizFeedback.subject == subject,
        ).first()
        if not f:
            return None
        return {
            "total_attempts": f.total_attempts,
            "total_questions": f.total_questions,
            "total_correct": f.total_correct,
            "avg_score": f.avg_score,
            "mcq_accuracy": f.mcq_accuracy,
            "theory_accuracy": f.theory_accuracy,
            "weak_topics": json.loads(f.weak_topics or "[]"),
            "strong_topics": json.loads(f.strong_topics or "[]"),
            "ai_feedback": f.ai_feedback or "",
        }
