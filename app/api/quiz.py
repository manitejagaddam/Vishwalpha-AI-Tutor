"""
app/api/quiz.py
────────────────
Quiz / Assignment API endpoints — JWT protected.

POST /quiz/generate           - Generate a personalised quiz
POST /quiz/answer             - Submit one question's answer
POST /quiz/finish             - Finalise attempt, compute score, update cognitive profile
GET  /quiz/yesterday          - Yesterday's session context (session-start banner)
GET  /quiz/history            - Past quiz attempt summaries
GET  /quiz/feedback/{subject} - Aggregated subject quiz feedback

student_id is always resolved from the JWT token — never from request body.
The /quiz/answer and /quiz/finish endpoints do NOT require ownership
verification at the question level (question_id is a sequential int that
cannot be guessed without the attempt_id, which is a UUID).
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import func as sqlfunc

from app.schemas import (
    GenerateQuizRequest, GenerateQuizResponse, QuizQuestionOut,
    SubmitAnswerRequest, SubmitAnswerResponse,
    FinishQuizRequest, FinishQuizResponse,
    SubjectQuizFeedbackOut,
)
from app.data.quiz_repo import (
    create_quiz_attempt,
    save_quiz_questions,
    get_quiz_questions,
    submit_quiz_answer,
    finish_quiz_attempt,
    get_attempt_details,
    update_subject_quiz_feedback,
    get_yesterday_session_context,
    get_quiz_history,
    get_subject_quiz_feedback,
)
from app.data.cognitive_repo import (
    get_subject_metrics,
    append_pending_signal,
    batch_update_cognitive_profile,
    increment_quiz_count,
    increment_streak_quizzes,
    update_topic_mastery_from_quiz,
    update_student_streak,
)
from app.data.session_repo import get_student_memory
from app.services.quiz_service import (
    generate_quiz,
    generate_quiz_ai_feedback,
    compute_quiz_cognitive_signals,
)
from app.data.database import managed_session
from app.data.models import Student, Topic
from app.api.deps import get_current_student

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/quiz", tags=["Quiz"])


# ── Generate Quiz ──────────────────────────────────────────────────────────────

@router.post("/generate", response_model=GenerateQuizResponse)
def generate_quiz_endpoint(
    request: GenerateQuizRequest,
    student: Student = Depends(get_current_student),
):
    """
    Generates a personalised quiz (MCQ + theory) for the authenticated student.
    Adapts difficulty from their cognitive profile and memory.
    """
    try:
        with managed_session() as db:
            metrics = get_subject_metrics(db, student.id, request.subject)

        memory_items = get_student_memory(student.id, request.subject)
        memory_str = "\n".join(f"- {m}" for m in memory_items) if memory_items else "(no memory yet)"

        existing_fb = get_subject_quiz_feedback(student.id, request.subject)
        weak_topics = existing_fb.get("weak_topics", []) if existing_fb else []

        questions = generate_quiz(
            subject=request.subject,
            topic=request.topic,
            class_num=student.class_num,
            student_memory=memory_str,
            cognitive_metrics=metrics,
            weak_topics=weak_topics,
            num_questions=request.num_questions,
        )

        if not questions:
            raise HTTPException(status_code=500, detail="Quiz generation returned no questions.")

        attempt_id = create_quiz_attempt(
            student_id=student.id,
            subject=request.subject,
            topic=request.topic,
            source=request.source,
            session_id=request.session_id or None,
            num_questions=len(questions),
        )
        save_quiz_questions(attempt_id, questions)
        saved_qs = get_quiz_questions(attempt_id)

        return GenerateQuizResponse(
            attempt_id=attempt_id,
            subject=request.subject,
            topic=request.topic,
            source=request.source,
            questions=[
                QuizQuestionOut(
                    id=q["id"],
                    q_index=q["q_index"],
                    q_type=q["q_type"],
                    question=q["question"],
                    options=q["options"],
                )
                for q in saved_qs
            ],
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Quiz generation error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate quiz.")


# ── Submit Answer ──────────────────────────────────────────────────────────────

@router.post("/answer", response_model=SubmitAnswerResponse)
def submit_answer_endpoint(
    request: SubmitAnswerRequest,
    _student: Student = Depends(get_current_student),   # auth check only
):
    """Submit a student's answer for a single quiz question."""
    try:
        result = submit_quiz_answer(
            question_id=request.question_id,
            student_answer=request.student_answer,
            student_answer_index=request.student_answer_index,
        )
        return SubmitAnswerResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(f"Answer submission error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to submit answer.")


# ── Finish Quiz ────────────────────────────────────────────────────────────────

@router.post("/finish", response_model=FinishQuizResponse)
def finish_quiz_endpoint(
    request: FinishQuizRequest,
    student: Student = Depends(get_current_student),
):
    """
    Finalises a quiz attempt:
    1. Computes final score from all answered questions
    2. Generates AI feedback paragraph
    3. Updates subject quiz feedback (cumulative record)
    4. Applies cognitive metric impact to student profile + memory
    5. Updates topic mastery + spaced repetition schedule
    """
    try:
        # 1. Score the attempt
        result    = finish_quiz_attempt(request.attempt_id)
        student_id = result["student_id"]
        subject   = result["subject"]
        topic     = result["topic"]
        score     = result["score"]
        correct   = result["correct"]
        total     = result["total"]
        passed    = result["passed"]

        # 2. Fetch full question details for feedback
        details       = get_attempt_details(request.attempt_id)
        all_questions = details["questions"] if details else []

        mcq_qs    = [q for q in all_questions if q["q_type"] == "mcq"]
        theory_qs = [q for q in all_questions if q["q_type"] == "theory"]
        mcq_accuracy = (
            round(sum(1 for q in mcq_qs if q["is_correct"]) / len(mcq_qs) * 100, 1)
            if mcq_qs else 0.0
        )
        theory_accuracy = (
            round(sum(1 for q in theory_qs if q["is_correct"]) / len(theory_qs) * 100, 1)
            if theory_qs else 0.0
        )
        wrong_questions = [q["question"] for q in all_questions if not q.get("is_correct")]

        # 3. Generate AI feedback
        ai_feedback = generate_quiz_ai_feedback(
            subject=subject,
            topic=topic,
            class_num=student.class_num,
            score=score,
            correct=correct,
            total=total,
            mcq_accuracy=mcq_accuracy,
            theory_accuracy=theory_accuracy,
            wrong_questions=wrong_questions,
        )

        # 4. Update cumulative subject quiz feedback record
        update_subject_quiz_feedback(
            student_id=student_id,
            subject=subject,
            attempt_result=result,
            questions=all_questions,
            ai_feedback=ai_feedback,
        )

        # 5. Cognitive metric signals
        signals = compute_quiz_cognitive_signals(
            score=score,
            mcq_accuracy=mcq_accuracy,
            theory_accuracy=theory_accuracy,
            num_questions=total,
            passed=passed,
        )
        session_id = request.session_id or None
        append_pending_signal(student_id, subject, session_id or "", signals)
        metrics_applied = batch_update_cognitive_profile(student_id, subject, session_id or "")

        # 6. Update student memory with quiz performance
        if wrong_questions:
            try:
                from app.data.session_repo import update_student_memory
                context_snippet = (
                    f"Quiz on {topic}: score {score:.0f}%. "
                    f"Struggled with: {', '.join(wrong_questions[:3])}."
                )
                remark = (
                    f"Student scored {score:.0f}% on {topic} quiz. "
                    f"Needs review: {', '.join(wrong_questions[:2])}."
                )
                update_student_memory(student_id, subject, remark, context_snippet)
            except Exception as e:
                logger.warning(f"Memory update after quiz failed: {e}")

        # 7. Topic mastery + spaced repetition
        try:
            with managed_session() as db:
                topic_row = db.query(Topic).filter(
                    sqlfunc.lower(Topic.title) == topic.lower()
                ).first()
                if topic_row:
                    update_topic_mastery_from_quiz(student_id, topic_row.id, score, passed)
        except Exception as e:
            logger.warning(f"Topic mastery update after quiz failed: {e}")

        # 8. Increment quiz count + streak
        try:
            increment_quiz_count(student_id, subject)
            increment_streak_quizzes(student_id)
            update_student_streak(student_id)
        except Exception as e:
            logger.warning(f"Quiz count/streak update failed: {e}")

        return FinishQuizResponse(
            attempt_id=request.attempt_id,
            score=score,
            total=total,
            correct=correct,
            passed=passed,
            topic=topic,
            subject=subject,
            ai_feedback=ai_feedback,
            metrics_impact=metrics_applied,
        )

    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(f"Quiz finish error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to finish quiz.")


# ── Yesterday Context ──────────────────────────────────────────────────────────

@router.get("/yesterday")
def yesterday_context_endpoint(student: Student = Depends(get_current_student)):
    """Returns yesterday's session topic for the session-start assignment banner."""
    ctx = get_yesterday_session_context(student.id)
    if not ctx:
        return {"has_context": False, "context": None}
    return {"has_context": True, "context": ctx}


# ── Quiz History ───────────────────────────────────────────────────────────────

@router.get("/history")
def quiz_history_endpoint(
    subject: str | None = None,
    student: Student = Depends(get_current_student),
):
    """Returns the authenticated student's past quiz attempt summaries."""
    history = get_quiz_history(student.id, subject)
    return {"attempts": history}


# ── Subject Quiz Feedback ──────────────────────────────────────────────────────

@router.get("/feedback/{subject}", response_model=SubjectQuizFeedbackOut)
def quiz_feedback_endpoint(
    subject: str,
    student: Student = Depends(get_current_student),
):
    """Returns the aggregated quiz feedback record for the authenticated student/subject."""
    fb = get_subject_quiz_feedback(student.id, subject)
    if not fb:
        return SubjectQuizFeedbackOut()
    return SubjectQuizFeedbackOut(**fb)
