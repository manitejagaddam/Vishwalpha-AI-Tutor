"""
app/data/quiz_repo.py
─────────────────────
All DB operations for the quiz / assignment system.
"""
import uuid
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.data.database import managed_session
from app.data.models.learning import (
    QuizAttempt,
    QuizQuestion,
    SubjectQuizFeedback,
)
from app.data.models.chat import Conversation, Message
from app.data.models.content import Topic, Subject

logger = logging.getLogger(__name__)


# ── Quiz Attempt CRUD ─────────────────────────────────────────────────────────

def create_quiz_attempt(
    student_id: str,
    subject_id: int,
    topic: str,
    source: str,               # 'mid_concept' | 'yesterday' | 'manual' | 'spaced_review'
    conversation_id: str | None = None,
    num_questions: int = 7,
) -> str:
    """Creates a new quiz attempt and returns its UUID."""
    attempt_id = str(uuid.uuid4())
    with managed_session() as db:
        db.add(QuizAttempt(
            id=attempt_id,
            user_id=student_id,
            conversation_id=conversation_id,
            subject_id=subject_id,
            topic=topic,
            source=source,
            num_questions=num_questions,
        ))
    return attempt_id


def save_quiz_questions(attempt_id: str, questions: list[dict]) -> list[int]:
    """
    Bulk-inserts a list of question dicts into quiz_questions.
    """
    with managed_session() as db:
        inserted = []
        for idx, q in enumerate(questions):
            row = QuizQuestion(
                attempt_id=attempt_id,
                q_index=idx,
                q_type=q.get("q_type", "mcq"),
                question=q["question"],
                options=q.get("options") or [],   # JSONB: pass list directly
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
    """Returns all questions for an attempt (without answers)."""
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
                "options": r.options if isinstance(r.options, list) else (json.loads(r.options) if r.options else []),
                "explanation": r.explanation,
                "difficulty": r.difficulty,
                "bloom_level": r.bloom_level,
            })
        return result


def submit_quiz_answer(
    question_id: int,
    student_answer: str,
    student_answer_index: int | None = None,
    time_taken_ms: int | None = None,
) -> dict:
    """Records a student's answer for a single question."""
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
    Returns {score, total, correct, passed, topic, subject_id, student_id}.
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
            "subject_id": attempt.subject_id,
            "user_id": attempt.user_id,
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
            "subject_id": attempt.subject_id,
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
    subject_id: int,
    attempt_result: dict,
    questions: list[dict],
    ai_feedback: str = "",
) -> None:
    """
    Upserts the SubjectQuizFeedback row for this student/subject.
    """
    with managed_session() as db:
        feedback = db.query(SubjectQuizFeedback).filter(
            SubjectQuizFeedback.user_id == student_id,
            SubjectQuizFeedback.subject_id == subject_id,
        ).first()

        if not feedback:
            feedback = SubjectQuizFeedback(
                id=str(uuid.uuid4()),
                user_id=student_id,
                subject_id=subject_id,
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
            weak = feedback.weak_topics or []
            strong = feedback.strong_topics or []
            if not isinstance(weak, list):
                try: weak = json.loads(weak)
                except: weak = []
            if not isinstance(strong, list):
                try: strong = json.loads(strong)
                except: strong = []

            if score < 50 and topic not in weak:
                weak.append(topic)
                if topic in strong:
                    strong.remove(topic)
            elif score >= 70 and topic not in strong:
                strong.append(topic)
                if topic in weak:
                    weak.remove(topic)

            feedback.weak_topics = weak[-10:]
            feedback.strong_topics = strong[-10:]

        if ai_feedback:
            feedback.ai_feedback = ai_feedback


# ── Yesterday-context detection ───────────────────────────────────────────────

def get_yesterday_session_context(student_id: str) -> dict | None:
    """
    Checks if the student had a conversation yesterday (between 18h and 48h ago) with a topic.
    Returns {subject, topic, session_date, session_id} or None.
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=48)
    window_end   = now - timedelta(hours=18)

    with managed_session() as db:
        # We find the latest message from this student that has a topic_id
        latest_msg = (
            db.query(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .filter(
                Conversation.user_id == student_id,
                Message.created_at >= window_start,
                Message.created_at <= window_end,
                Message.topic_id.isnot(None)
            )
            .order_by(Message.created_at.desc())
            .first()
        )

        if not latest_msg:
            return None

        # Resolve Topic and Subject names
        topic = db.query(Topic).filter(Topic.id == latest_msg.topic_id).first()
        if not topic:
            return None
            
        subject = db.query(Subject).join(Conversation, Conversation.subject_id == Subject.id).filter(Conversation.id == latest_msg.conversation_id).first()

        return {
            "subject": subject.name if subject else "General",
            "topic": topic.title,
            "session_date": latest_msg.created_at.strftime("%d %b %Y") if latest_msg.created_at else "",
            "session_id": str(latest_msg.conversation_id),
        }


# ── Quiz history ──────────────────────────────────────────────────────────────

def get_quiz_history(student_id: str, subject_id: int | None = None) -> list[dict]:
    """Returns summary of past quiz attempts, most recent first."""
    with managed_session() as db:
        query = db.query(QuizAttempt).filter(QuizAttempt.user_id == student_id)
        if subject_id:
            query = query.filter(QuizAttempt.subject_id == subject_id)
        attempts = query.order_by(QuizAttempt.created_at.desc()).limit(20).all()
        return [
            {
                "id": a.id,
                "subject_id": a.subject_id,
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


def get_subject_quiz_feedback(student_id: str, subject_id: int) -> dict | None:
    """Returns the aggregated quiz feedback record for a student/subject."""
    with managed_session() as db:
        f = db.query(SubjectQuizFeedback).filter(
            SubjectQuizFeedback.user_id == student_id,
            SubjectQuizFeedback.subject_id == subject_id,
        ).first()
        if not f:
            return None
        weak = f.weak_topics if isinstance(f.weak_topics, list) else json.loads(f.weak_topics or "[]")
        strong = f.strong_topics if isinstance(f.strong_topics, list) else json.loads(f.strong_topics or "[]")
        return {
            "total_attempts": f.total_attempts,
            "total_questions": f.total_questions,
            "total_correct": f.total_correct,
            "avg_score": f.avg_score,
            "mcq_accuracy": f.mcq_accuracy,
            "theory_accuracy": f.theory_accuracy,
            "weak_topics": weak,
            "strong_topics": strong,
            "ai_feedback": f.ai_feedback or "",
        }
