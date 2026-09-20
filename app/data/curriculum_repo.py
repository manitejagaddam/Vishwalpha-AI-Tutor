"""
app/data/curriculum_repo.py
─────────────────────────────────
Read-only repository for browsing the curriculum hierarchy.
Powers the /curriculum/* endpoints that populate subject/chapter/topic dropdowns.

Phase 2 hierarchy: Board → SchoolClass → Subject → Book → Chapter → Topic
"""
import logging
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.data.models.content import Subject, Book, Chapter, Topic, SchoolClass

logger = logging.getLogger(__name__)


def get_subjects(db: Session, class_num: int) -> list[str]:
    """Returns all subject names for a given class level."""
    rows = (
        db.query(Subject.name)
        .join(SchoolClass, Subject.class_id == SchoolClass.id)
        .filter(SchoolClass.level == class_num)
        .distinct()
        .all()
    )
    return [r[0] for r in rows if r[0]]


def get_chapters(db: Session, class_num: int, subject: str) -> list[str]:
    rows = (
        db.query(Chapter.title)
        .join(Book, Chapter.book_id == Book.id)
        .join(Subject, Book.subject_id == Subject.id)
        .join(SchoolClass, Subject.class_id == SchoolClass.id)
        .filter(
            SchoolClass.level == class_num,
            func.lower(Subject.name) == subject.lower(),
        )
        .order_by(Chapter.display_order)
        .distinct()
        .all()
    )
    return [r[0] for r in rows if r[0]]


def get_topics(db: Session, class_num: int, subject: str, chapter: str) -> list[str]:
    rows = (
        db.query(Topic.title)
        .join(Chapter, Topic.chapter_id == Chapter.id)
        .join(Book, Chapter.book_id == Book.id)
        .join(Subject, Book.subject_id == Subject.id)
        .join(SchoolClass, Subject.class_id == SchoolClass.id)
        .filter(
            SchoolClass.level == class_num,
            func.lower(Subject.name) == subject.lower(),
            func.lower(Chapter.title) == chapter.lower(),
        )
        .order_by(Topic.display_order)
        .distinct()
        .all()
    )
    return [r[0] for r in rows if r[0]]
