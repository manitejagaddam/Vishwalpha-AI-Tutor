"""
app/data/curriculum_repo.py
────────────────────────────
Read-only repository for browsing the curriculum hierarchy.
Powers the /curriculum/* endpoints that populate subject/chapter/topic dropdowns.
"""
import logging
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.data.models import CurriculumRouting

logger = logging.getLogger(__name__)


def get_subjects(db: Session, class_num: int) -> list[str]:
    rows = (
        db.query(CurriculumRouting.subject)
        .filter(CurriculumRouting.class_num == class_num)
        .distinct()
        .all()
    )
    return [r[0] for r in rows if r[0]]


def get_chapters(db: Session, class_num: int, subject: str) -> list[str]:
    rows = (
        db.query(CurriculumRouting.chapter)
        .filter(
            CurriculumRouting.class_num == class_num,
            func.lower(CurriculumRouting.subject) == subject.lower(),
        )
        .distinct()
        .all()
    )
    return [r[0] for r in rows if r[0]]


def get_topics(db: Session, class_num: int, subject: str, chapter: str) -> list[str]:
    rows = (
        db.query(CurriculumRouting.topic)
        .filter(
            CurriculumRouting.class_num == class_num,
            func.lower(CurriculumRouting.subject) == subject.lower(),
            func.lower(CurriculumRouting.chapter) == chapter.lower(),
        )
        .distinct()
        .all()
    )
    return [r[0] for r in rows if r[0]]
