"""
app/api/curriculum.py
──────────────────────
Curriculum browse routes — used by frontend to populate dropdowns.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.data.database import get_db
from app.data.curriculum_repo import get_subjects, get_chapters, get_topics

router = APIRouter(prefix="/curriculum", tags=["Curriculum"])


@router.get("/subjects")
def list_subjects(class_num: int, db: Session = Depends(get_db)):
    """Returns all subjects available for a given class."""
    return {"subjects": get_subjects(db, class_num)}


@router.get("/chapters")
def list_chapters(class_num: int, subject: str, db: Session = Depends(get_db)):
    """Returns all chapters for a given class and subject."""
    return {"chapters": get_chapters(db, class_num, subject)}


@router.get("/topics")
def list_topics(
    class_num: int, subject: str, chapter: str, db: Session = Depends(get_db)
):
    """Returns all topics for a given class, subject, and chapter."""
    return {"topics": get_topics(db, class_num, subject, chapter)}
