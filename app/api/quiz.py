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
from app.data.models.platform import User
from app.data.models.content import Subject, Topic
from app.api.deps import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/quiz", tags=["Quiz"])


# ── Generate Quiz ──────────────────────────────────────────────────────────────

@router.post("/generate", response_model=GenerateQuizResponse)
def generate_quiz_endpoint(
    request: GenerateQuizRequest,
    student: User = Depends(get_current_user),
):
    """
    Generates a personalised quiz (MCQ + theory) for the authenticated student.
    Adapts difficulty from their cognitive profile and memory.
    """
    student_id = str(student.id)
    class_num = getattr(student, "class_num", 10) or 10

    try:
        with managed_session() as db:
            sub = None
            req_sub = (request.subject or "").strip()
            # 1. Try if request.subject is an integer ID (e.g. "1")
            if req_sub.isdigit():
                sid_candidate = int(req_sub)
                if sid_candidate > 0:
                    sub = db.query(Subject).filter(Subject.id == sid_candidate).first()
            # 2. Try by case-insensitive name
            if not sub and req_sub:
                sub = db.query(Subject).filter(sqlfunc.lower(Subject.name) == req_sub.lower()).first()
            # 3. Fetch conversation if session_id is provided
            conv = None
            if request.session_id:
                from app.data.models.chat import Conversation
                conv = db.query(Conversation).filter(Conversation.id == request.session_id).first()
                if not sub and conv and conv.subject_id:
                    sub = db.query(Subject).filter(Subject.id == conv.subject_id).first()
            # 4. Fallback to first available subject in DB
            if not sub:
                sub = db.query(Subject).first()

            if not sub:
                raise HTTPException(status_code=400, detail="No subjects found in curriculum database.")

            subject_id = sub.id
            subject_name = sub.name

            # Resolve effective topic if topic is empty or unspecified
            effective_topic = (request.topic or "").strip()
            if not effective_topic:
                if conv and conv.last_topic_name:
                    effective_topic = conv.last_topic_name
                else:
                    from app.data.models.content import Chapter, Book
                    top = (
                        db.query(Topic.title)
                        .join(Chapter, Topic.chapter_id == Chapter.id)
                        .join(Book, Chapter.book_id == Book.id)
                        .filter(Book.subject_id == subject_id)
                        .first()
                    )
                    effective_topic = top[0] if top else f"Comprehensive {subject_name} Review"

            metrics = get_subject_metrics(db, student_id, subject_id)

        memory_items = get_student_memory(student_id, str(subject_id))
        memory_str = "\n".join(f"- {m}" for m in memory_items) if memory_items else "(no memory yet)"

        existing_fb = get_subject_quiz_feedback(student_id, subject_id)
        weak_topics = existing_fb.get("weak_topics", []) if existing_fb else []

        questions = generate_quiz(
            subject=subject_name,
            topic=effective_topic,
            class_num=class_num,
            student_memory=memory_str,
            cognitive_metrics=metrics,
            weak_topics=weak_topics,
            num_questions=request.num_questions,
        )

        if not questions:
            raise HTTPException(status_code=500, detail="Quiz generation returned no questions.")

        attempt_id = create_quiz_attempt(
            student_id=student_id,
            subject_id=subject_id,
            topic=effective_topic,
            source=request.source,
            conversation_id=request.session_id or None,
            num_questions=len(questions),
        )
        save_quiz_questions(attempt_id, questions)
        saved_qs = get_quiz_questions(attempt_id)

        return GenerateQuizResponse(
            attempt_id=attempt_id,
            subject=subject_name,
            topic=effective_topic,
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
    _student: User = Depends(get_current_user),   # auth check only
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
    student: User = Depends(get_current_user),
):
    """
    Finalises a quiz attempt:
    1. Computes final score from all answered questions
    2. Generates AI feedback paragraph
    3. Updates subject quiz feedback (cumulative record)
    4. Applies cognitive metric impact to student profile + memory
    5. Updates topic mastery + spaced repetition schedule
    """
    student_id = str(student.id)
    student_class_num = getattr(student, "class_num", 10) or 10

    try:
        # 1. Score the attempt
        result    = finish_quiz_attempt(request.attempt_id)
        user_id    = result["user_id"]
        subject_id = result["subject_id"]
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
        # Resolve subject name for the AI feedback text
        with managed_session() as db:
            from app.data.models.content import Subject as SubjectModel
            sub_row = db.query(SubjectModel).filter(SubjectModel.id == subject_id).first()
            subject_name = sub_row.name if sub_row else str(subject_id)
        ai_feedback = generate_quiz_ai_feedback(
            subject=subject_name,
            topic=topic,
            class_num=student_class_num,
            score=score,
            correct=correct,
            total=total,
            mcq_accuracy=mcq_accuracy,
            theory_accuracy=theory_accuracy,
            wrong_questions=wrong_questions,
        )

        # 4. Update cumulative subject quiz feedback record
        update_subject_quiz_feedback(
            student_id=user_id,
            subject_id=subject_id,
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
        append_pending_signal(user_id, subject_id, session_id, signals)
        metrics_applied = batch_update_cognitive_profile(user_id, subject_id, session_id or "")

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
                update_student_memory(str(user_id), subject_id, remark, context_snippet)
            except Exception as e:
                logger.warning(f"Memory update after quiz failed: {e}")

        # 7. Topic mastery + spaced repetition
        try:
            with managed_session() as db:
                topic_row = db.query(Topic).filter(
                    sqlfunc.lower(Topic.title) == topic.lower()
                ).first()
                if topic_row:
                    update_topic_mastery_from_quiz(str(user_id), topic_row.id, score, passed)
        except Exception as e:
            logger.warning(f"Topic mastery update after quiz failed: {e}")

        # 8. Increment quiz count + streak
        try:
            increment_quiz_count(str(user_id), subject_id)
            increment_streak_quizzes(str(user_id))
            update_student_streak(str(user_id))
        except Exception as e:
            logger.warning(f"Quiz count/streak update failed: {e}")

        # 9. Invalidate session cache so subsequent chat turns pull fresh weak topics & mastery
        try:
            from app.infra.redis_cache import get_redis_cache
            get_redis_cache().invalidate_session_state(str(user_id), subject_id)
        except Exception as e:
            logger.warning(f"Session cache invalidation after quiz failed: {e}")

        # 10. Real-Time Cross-Device Sync (Addon #4)
        try:
            from app.services.sync_service import sync_manager
            sync_manager.sync_broadcast(
                user_id=str(user_id),
                event="quiz_completed",
                data={
                    "attempt_id": str(request.attempt_id),
                    "score": score,
                    "passed": passed,
                    "topic": topic,
                    "subject": subject_name,
                },
            )
        except Exception as e:
            logger.debug(f"[RealTime Sync] Quiz sync broadcast failed: {e}")

        return FinishQuizResponse(
            attempt_id=str(request.attempt_id),
            score=score,
            total=total,
            correct=correct,
            passed=passed,
            topic=topic,
            subject=subject_name,
            ai_feedback=ai_feedback,
            metrics_impact=metrics_applied or {},
        )

    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(f"Quiz finish error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to finish quiz.")


# ── Yesterday Context ──────────────────────────────────────────────────────────

@router.get("/yesterday")
def yesterday_context_endpoint(student: User = Depends(get_current_user)):
    """Returns yesterday's session topic for the session-start assignment banner."""
    ctx = get_yesterday_session_context(student.id)
    if not ctx:
        return {"has_context": False, "context": None}
    return {"has_context": True, "context": ctx}


# ── Quiz History ───────────────────────────────────────────────────────────────

@router.get("/history")
def quiz_history_endpoint(
    subject: str | None = None,
    student: User = Depends(get_current_user),
):
    """Returns the authenticated student's past quiz attempt summaries."""
    subject_id = None
    if subject:
        with managed_session() as db:
            sub = db.query(Subject).filter(Subject.name == subject).first()
            subject_id = sub.id if sub else None
    history = get_quiz_history(student.id, subject_id)
    return {"attempts": history}


# ── Subject Quiz Feedback ──────────────────────────────────────────────────────

@router.get("/feedback/{subject}", response_model=SubjectQuizFeedbackOut)
def quiz_feedback_endpoint(
    subject: str,
    student: User = Depends(get_current_user),
):
    """Returns the aggregated quiz feedback record for the authenticated student/subject."""
    with managed_session() as db:
        sub = db.query(Subject).filter(Subject.name == subject).first()
        if not sub:
            return SubjectQuizFeedbackOut()
        subject_id = sub.id
    fb = get_subject_quiz_feedback(student.id, subject_id)
    if not fb:
        return SubjectQuizFeedbackOut()
    return SubjectQuizFeedbackOut(**fb)
