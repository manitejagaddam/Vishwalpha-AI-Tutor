"""
app/api/student.py
───────────────────
Student profile, cognitive, and learning-path routes — JWT protected.

Endpoints
---------
GET  /student/profile                — basic identity + subject_id resolver
GET  /student/memory                 — overall memory + metrics (single subject)
POST /student/memory                 — manually add a memory fact

GET  /student/cognitive/{subject}    — FULL per-subject cognitive profile
                                       (13 metrics + 5 derived skills + counters
                                        + quiz feedback + memory facts)
GET  /student/cognitive              — overview of ALL subjects this student
                                       has a profile for (multi-subject dashboard)
GET  /student/topics/{subject}       — per-topic mastery list for a subject
GET  /student/learning-path/{subject}— chapter -> topic learning path with
                                       mastery, bloom level, and review dates
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.data.database import get_db
from app.data.models.platform import User
from app.data.models.learning import StudentProfile
from app.api.deps import get_current_user

router = APIRouter(prefix="/student", tags=["Student"])


# ── Basic profile ─────────────────────────────────────────────────────────────

@router.get("/profile")
def get_profile(
    subject: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns the student's basic identity.
    Pass ?subject=Science to also get the resolved numeric subject_id.
    Cache subject_id in the frontend and pass it back in POST /chat/session/end.
    """
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == current_user.id).first()

    from app.api.deps import resolve_subject
    class_num = getattr(current_user, "class_num", 10) or 10
    sub = resolve_subject(db, subject, class_num) if subject else None
    resolved_subject_id = sub.id if sub else None

    return {
        "student_id":     str(current_user.id),
        "username":       current_user.username,
        "class_num":      current_user.class_num,
        "subject":        subject,
        "subject_id":     resolved_subject_id,
        "board_id":       profile.board_id if profile else None,
        "learning_style": profile.learning_style if profile else None,
    }


# ── Memory (convenience) ──────────────────────────────────────────────────────

@router.get("/memory")
def get_memory(
    subject: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns cognitive metrics, derived skills, and semantic memory for one subject.
    For the richer full profile use GET /student/cognitive/{subject}.
    """
    from app.api.deps import resolve_subject
    from app.data.cognitive_repo import get_subject_metrics, compute_cognitive_skills
    from app.data.session_repo import get_student_memory

    class_num = getattr(current_user, "class_num", 10) or 10
    sub = resolve_subject(db, subject, class_num) if subject else None

    if not sub:
        from app.data.models.content import SchoolClass, Subject
        sub = (
            db.query(Subject)
            .join(SchoolClass, Subject.class_id == SchoolClass.id)
            .filter(SchoolClass.level == class_num)
            .first()
        )
        if not sub:
            sub = db.query(Subject).first()

    if not sub:
        return {"metrics": {}, "cognitive_skills": {}, "memory": ""}

    metrics = get_subject_metrics(db, str(current_user.id), sub.id)
    memory_items = get_student_memory(str(current_user.id), sub.id)
    memory_str = "\n".join(f"• {m}" for m in memory_items) if memory_items else ""

    return {
        "metrics":          metrics,
        "cognitive_skills": compute_cognitive_skills(metrics) if metrics else {},
        "memory":           memory_str,
    }


from pydantic import BaseModel


class UpdateMemoryRequest(BaseModel):
    subject: str | None = None
    fact: str


@router.post("/memory")
def update_memory(
    request: UpdateMemoryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually add a persistent memory fact for this student."""
    from app.api.deps import resolve_subject
    from app.data.session_repo import add_fast_memory_fact

    class_num = getattr(current_user, "class_num", 10) or 10
    sub = resolve_subject(db, request.subject, class_num) if request.subject else None
    subject_id = sub.id if sub else None

    success = add_fast_memory_fact(
        student_id=str(current_user.id),
        fact=request.fact,
        subject_id=subject_id,
    )

    return {"status": "success", "inserted": success, "fact": request.fact}


# ── Per-subject cognitive profile ─────────────────────────────────────────────

@router.get("/cognitive/{subject}")
def get_subject_cognitive_profile(
    subject: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    FULL per-subject cognitive profile for this student.

    Returns:
    - 13 raw cognitive metrics (10 core + bloom_level_avg + frustration + confidence)
    - 5 derived high-level cognitive skills
    - Engagement counters (total_chat_turns, total_quizzes, avg_session_duration_min)
    - Aggregated quiz feedback (avg_score, weak_topics, strong_topics, ai_feedback)
    - All active memory facts for this subject

    This is the primary data source for a per-subject student dashboard card.
    The profile row is auto-created on first access (defaults to 50/100 for all metrics).
    """
    from app.api.deps import resolve_subject
    from app.data.cognitive_repo import get_full_subject_profile, compute_cognitive_skills
    from app.data.session_repo import get_student_memory
    from app.data.models.learning import SubjectQuizFeedback

    class_num = getattr(current_user, "class_num", 10) or 10
    sub = resolve_subject(db, subject, class_num)
    if not sub:
        raise HTTPException(
            status_code=404,
            detail=f"Subject '{subject}' not found for class {class_num}."
        )

    user_id = str(current_user.id)
    full = get_full_subject_profile(db, user_id, sub.id)

    core_metrics = {
        k: full[k] for k in [
            "concept_master_score", "error_repetition_rate", "attempt_persistence",
            "struggle_recovery_rate", "practice_intensity", "learning_velocity",
            "knowledge_retention", "cognitive_thinking_level", "engagement_frequency",
            "assessment_accuracy",
        ]
    }
    skills = compute_cognitive_skills(core_metrics)

    sqf = db.query(SubjectQuizFeedback).filter(
        SubjectQuizFeedback.user_id == current_user.id,
        SubjectQuizFeedback.subject_id == sub.id,
    ).first()

    quiz_feedback = {
        "total_attempts":  sqf.total_attempts if sqf else 0,
        "total_questions": sqf.total_questions if sqf else 0,
        "avg_score":       sqf.avg_score if sqf else 0.0,
        "mcq_accuracy":    sqf.mcq_accuracy if sqf else 0.0,
        "theory_accuracy": sqf.theory_accuracy if sqf else 0.0,
        "weak_topics":     sqf.weak_topics if sqf else [],
        "strong_topics":   sqf.strong_topics if sqf else [],
        "ai_feedback":     sqf.ai_feedback if sqf else "",
    }

    memory_items = get_student_memory(user_id, sub.id)

    return {
        "subject_id":               sub.id,
        "subject_name":             sub.name,
        # ── Raw 10 core metrics (0-100, except error_repetition_rate: 0.0-1.0)
        "metrics":                  core_metrics,
        # ── Extended metrics
        "bloom_level_avg":          full.get("bloom_level_avg", 1.0),
        "frustration_index":        full.get("frustration_index", 0.0),
        "confidence_index":         full.get("confidence_index", 50.0),
        # ── Engagement counters
        "total_chat_turns":         full.get("total_chat_turns", 0),
        "total_quizzes":            full.get("total_quizzes", 0),
        "avg_session_duration_min": full.get("avg_session_duration_min", 0.0),
        # ── 5 derived high-level skills (0-100 each)
        "cognitive_skills":         skills,
        # ── Quiz performance aggregate
        "quiz_feedback":            quiz_feedback,
        # ── AI-curated memory facts
        "memory_facts":             memory_items,
    }


# ── All-subjects overview ─────────────────────────────────────────────────────

@router.get("/cognitive")
def get_all_subject_profiles(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns a summary card for EVERY subject this student has a cognitive
    profile for (i.e. every subject they have chatted or taken a quiz in).

    Use this to render the multi-subject overview / home dashboard.
    Subjects with no profile yet are not included — they appear only after
    the student's first chat/quiz turn in that subject.
    """
    from app.data.cognitive_repo import compute_cognitive_skills
    from app.data.models.learning import StudentSubjectProfile
    from app.data.models.content import Subject

    rows = (
        db.query(StudentSubjectProfile, Subject)
        .join(Subject, StudentSubjectProfile.subject_id == Subject.id)
        .filter(StudentSubjectProfile.user_id == current_user.id)
        .all()
    )

    result = []
    for prof, subj in rows:
        core = {
            "concept_master_score":     prof.concept_master_score,
            "error_repetition_rate":    prof.error_repetition_rate,
            "attempt_persistence":      prof.attempt_persistence,
            "struggle_recovery_rate":   prof.struggle_recovery_rate,
            "practice_intensity":       prof.practice_intensity,
            "learning_velocity":        prof.learning_velocity,
            "knowledge_retention":      prof.knowledge_retention,
            "cognitive_thinking_level": prof.cognitive_thinking_level,
            "engagement_frequency":     prof.engagement_frequency,
            "assessment_accuracy":      prof.assessment_accuracy,
        }
        result.append({
            "subject_id":       subj.id,
            "subject_name":     subj.name,
            "cognitive_skills": compute_cognitive_skills(core),
            "bloom_level_avg":  prof.bloom_level_avg,
            "total_chat_turns": prof.total_chat_turns,
            "total_quizzes":    prof.total_quizzes,
            "confidence_index": prof.confidence_index,
            "frustration_index": prof.frustration_index,
            "updated_at":       prof.updated_at,
        })

    return {"profiles": result, "total": len(result)}


# ── Per-topic mastery list ────────────────────────────────────────────────────

@router.get("/topics/{subject}")
def get_topic_mastery(
    subject: str,
    chapter_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns per-topic mastery data for this student in a given subject.

    Each entry shows mastery_level (0-100), bloom_level_reached (1-6),
    understood/confused concepts, spaced-repetition schedule, and confidence.

    Pass ?chapter_id=<id> to filter to a single chapter.
    Use this to render a topic mastery heatmap or list view.
    Topics never visited are not included (they appear once first visited via chat/quiz).
    """
    from app.api.deps import resolve_subject
    from app.data.models.learning import TopicMastery
    from app.data.models.content import Topic, Chapter, Book

    class_num = getattr(current_user, "class_num", 10) or 10
    sub = resolve_subject(db, subject, class_num)
    if not sub:
        raise HTTPException(status_code=404, detail=f"Subject '{subject}' not found.")

    q = (
        db.query(TopicMastery, Topic, Chapter)
        .join(Topic, TopicMastery.topic_id == Topic.id)
        .join(Chapter, Topic.chapter_id == Chapter.id)
        .join(Book, Chapter.book_id == Book.id)
        .filter(
            TopicMastery.user_id == current_user.id,
            Book.subject_id == sub.id,
        )
    )
    if chapter_id:
        q = q.filter(Chapter.id == chapter_id)

    rows = q.order_by(Chapter.chapter_number, Topic.display_order).all()

    topics = []
    for tm, topic, chapter in rows:
        topics.append({
            "topic_id":            topic.id,
            "topic_title":         topic.title,
            "topic_number":        topic.topic_number,
            "chapter_id":          chapter.id,
            "chapter_title":       chapter.title,
            "chapter_number":      chapter.chapter_number,
            # Mastery
            "mastery_level":       tm.mastery_level,
            "bloom_level_reached": tm.bloom_level_reached,
            "times_visited":       tm.times_visited,
            "last_visited":        tm.last_visited,
            "confidence":          tm.confidence,
            # Concept breakdown
            "understood_concepts": tm.understood_concepts or [],
            "confused_concepts":   tm.confused_concepts or [],
            "common_mistakes":     tm.common_mistakes or [],
            # Spaced repetition
            "next_review_date":    tm.next_review_date,
            "review_count":        tm.review_count,
            "decay_rate":          tm.decay_rate,
            "last_quiz_score":     tm.last_quiz_score,
        })

    return {
        "subject_id":   sub.id,
        "subject_name": sub.name,
        "topics":       topics,
        "total":        len(topics),
    }


# ── Full learning path ────────────────────────────────────────────────────────

@router.get("/learning-path/{subject}")
def get_learning_path(
    subject: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns a chapter-by-chapter learning path for this student.

    Each chapter node contains:
    - Chapter title, number, summary, learning_objectives (from NCERT)
    - Topics with their individual mastery_level + bloom_level_reached
    - Chapter aggregate: avg_mastery, strongest_bloom_level
    - Whether any topic has a spaced-repetition review due today

    Topics the student has NEVER visited have mastery_level = null (not 0).
    Use this to render the subject roadmap / curriculum map view.
    """
    from app.api.deps import resolve_subject
    from app.data.models.learning import TopicMastery
    from app.data.models.content import Topic, Chapter, Book
    from datetime import date

    class_num = getattr(current_user, "class_num", 10) or 10
    sub = resolve_subject(db, subject, class_num)
    if not sub:
        raise HTTPException(status_code=404, detail=f"Subject '{subject}' not found.")

    # All chapters for this subject
    chapters = (
        db.query(Chapter)
        .join(Book, Chapter.book_id == Book.id)
        .filter(Book.subject_id == sub.id)
        .order_by(Chapter.chapter_number)
        .all()
    )

    # Build a mastery lookup: topic_id -> TopicMastery
    mastery_map: dict[int, TopicMastery] = {}
    all_tm = (
        db.query(TopicMastery, Topic)
        .join(Topic, TopicMastery.topic_id == Topic.id)
        .join(Chapter, Topic.chapter_id == Chapter.id)
        .join(Book, Chapter.book_id == Book.id)
        .filter(
            TopicMastery.user_id == current_user.id,
            Book.subject_id == sub.id,
        )
        .all()
    )
    for tm, _ in all_tm:
        mastery_map[tm.topic_id] = tm

    today = date.today()
    path = []

    for chap in chapters:
        topics_in_chap = (
            db.query(Topic)
            .filter(Topic.chapter_id == chap.id)
            .order_by(Topic.display_order)
            .all()
        )

        topic_nodes = []
        mastery_values = []
        bloom_values = []
        has_review_due = False

        for topic in topics_in_chap:
            tm = mastery_map.get(topic.id)
            review_due = False

            if tm:
                mastery_values.append(tm.mastery_level)
                bloom_values.append(tm.bloom_level_reached)
                review_due = bool(tm.next_review_date and tm.next_review_date <= today)
                if review_due:
                    has_review_due = True

            topic_nodes.append({
                "topic_id":            topic.id,
                "topic_title":         topic.title,
                "topic_number":        topic.topic_number,
                "content_type":        topic.content_type,
                "difficulty_level":    topic.difficulty_level,
                # null = never visited by this student
                "mastery_level":       tm.mastery_level if tm else None,
                "bloom_level_reached": tm.bloom_level_reached if tm else None,
                "times_visited":       tm.times_visited if tm else 0,
                "confidence":          tm.confidence if tm else None,
                "next_review_date":    tm.next_review_date if tm else None,
                "review_due":          review_due,
            })

        path.append({
            "chapter_id":          chap.id,
            "chapter_number":      chap.chapter_number,
            "chapter_title":       chap.title,
            "learning_objectives": chap.learning_objectives,
            "summary":             chap.summary,
            "topics":              topic_nodes,
            "topic_count":         len(topic_nodes),
            "visited_count":       len(mastery_values),
            "avg_mastery":         round(sum(mastery_values) / len(mastery_values), 1) if mastery_values else None,
            "strongest_bloom":     max(bloom_values) if bloom_values else None,
            "has_review_due":      has_review_due,
        })

    return {
        "subject_id":    sub.id,
        "subject_name":  sub.name,
        "chapters":      path,
        "chapter_count": len(path),
    }
