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


@router.get(
    "/subjects",
    summary="List subjects for a class",
    description="Returns all subjects available in the NCERT curriculum for the given `class_num` (6–12).",
    responses={400: {"description": "Invalid class_num"}},
)
def list_subjects(class_num: int, db: Session = Depends(get_db)):
    """Returns all subjects available for a given class."""
    return {"subjects": get_subjects(db, class_num)}


@router.get(
    "/chapters",
    summary="List chapters for a subject",
    description="Returns all chapters for the given class and subject name (e.g. `Science`).",
    responses={404: {"description": "Subject not found for this class"}},
)
def list_chapters(class_num: int, subject: str, db: Session = Depends(get_db)):
    """Returns all chapters for a given class and subject."""
    return {"chapters": get_chapters(db, class_num, subject)}


@router.get(
    "/topics",
    summary="List topics for a chapter",
    description="Returns all topics for the given class, subject, and chapter title.",
    responses={404: {"description": "Chapter not found"}},
)
def list_topics(
    class_num: int, subject: str, chapter: str, db: Session = Depends(get_db)
):
    """Returns all topics for a given class, subject, and chapter."""
    return {"topics": get_topics(db, class_num, subject, chapter)}
