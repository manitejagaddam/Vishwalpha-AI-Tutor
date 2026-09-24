"""
app/api/spaces.py
─────────────────
Study Spaces endpoints: per-subject workspaces grouping conversations
with custom instructions for tutoring style/focus.
"""
import uuid
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.data.database import get_db
from app.data.models.content import StudySpace, Subject
from app.data.models.platform import User
from app.api.deps import get_current_user

router = APIRouter(prefix="/spaces", tags=["Study Spaces"])


class SpaceCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=150)
    subject_id: Optional[int] = None
    subject: Optional[str] = None
    custom_instructions: Optional[str] = None


class SpaceUpdateRequest(BaseModel):
    title: Optional[str] = None
    custom_instructions: Optional[str] = None
    is_archived: Optional[bool] = None


@router.get("")
def list_spaces(
    subject: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Lists all study spaces for current student, optionally filtered by subject."""
    query = db.query(StudySpace).filter(
        StudySpace.user_id == current_user.id,
        StudySpace.is_archived == False,
    )
    if subject:
        sub = db.query(Subject).filter(Subject.name == subject).first()
        if sub:
            query = query.filter(StudySpace.subject_id == sub.id)

    spaces = query.order_by(StudySpace.created_at.desc()).all()
    res = []
    for s in spaces:
        res.append({
            "id": str(s.id),
            "title": s.title,
            "subject_id": s.subject_id,
            "subject": s.subject.name if s.subject else (subject or "General"),
            "custom_instructions": s.custom_instructions or "",
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })
    return {"spaces": res}


@router.post("")
def create_space(
    body: SpaceCreateRequest,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Creates a new study space."""
    from app.data.models.content import SchoolClass
    from sqlalchemy import func as sqlfunc
    class_num = getattr(current_user, "class_num", 10) or 10

    subject_id = body.subject_id
    if not subject_id and body.subject:
        s_clean = body.subject.strip()
        sub = (
            db.query(Subject)
            .join(SchoolClass, Subject.class_id == SchoolClass.id)
            .filter(SchoolClass.level == class_num, sqlfunc.lower(Subject.name) == s_clean.lower())
            .first()
        )
        if not sub:
            sub = db.query(Subject).filter(sqlfunc.lower(Subject.name) == s_clean.lower()).first()
        if sub:
            subject_id = sub.id

    if not subject_id:
        sub_class = (
            db.query(Subject)
            .join(SchoolClass, Subject.class_id == SchoolClass.id)
            .filter(SchoolClass.level == class_num)
            .first()
        )
        first_sub = sub_class or db.query(Subject).first()
        subject_id = first_sub.id if first_sub else 1

    space = StudySpace(
        id=uuid.uuid4(),
        user_id=current_user.id,
        subject_id=subject_id,
        title=body.title.strip(),
        custom_instructions=body.custom_instructions.strip() if body.custom_instructions else None,
        pinned_context=[],
        is_archived=False,
    )
    db.add(space)
    db.commit()
    db.refresh(space)

    try:
        from app.services.sync_service import sync_manager
        sync_manager.sync_broadcast(str(current_user.id), "space_updated", {"action": "created", "space_id": str(space.id)})
    except Exception:
        pass

    return {
        "id": str(space.id),
        "title": space.title,
        "subject_id": space.subject_id,
        "subject": space.subject.name if space.subject else "Science",
        "custom_instructions": space.custom_instructions or "",
        "created_at": space.created_at.isoformat() if space.created_at else None,
    }


@router.patch("/{space_id}")
def update_space(
    space_id: str,
    body: SpaceUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Updates a study space title or custom instructions."""
    space = db.query(StudySpace).filter(
        StudySpace.id == uuid.UUID(space_id),
        StudySpace.user_id == current_user.id,
    ).first()
    if not space:
        raise HTTPException(status_code=404, detail="Study space not found.")

    if body.title is not None:
        space.title = body.title.strip()
    if body.custom_instructions is not None:
        space.custom_instructions = body.custom_instructions.strip()
    if body.is_archived is not None:
        space.is_archived = body.is_archived

    db.commit()

    try:
        from app.services.sync_service import sync_manager
        sync_manager.sync_broadcast(str(current_user.id), "space_updated", {"action": "updated", "space_id": str(space.id)})
    except Exception:
        pass

    return {
        "id": str(space.id),
        "title": space.title,
        "custom_instructions": space.custom_instructions or "",
        "is_archived": space.is_archived,
    }


@router.delete("/{space_id}")
def delete_space(
    space_id: str,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Soft-deletes (archives) or deletes a study space."""
    space = db.query(StudySpace).filter(
        StudySpace.id == uuid.UUID(space_id),
        StudySpace.user_id == current_user.id,
    ).first()
    if not space:
        raise HTTPException(status_code=404, detail="Study space not found.")

    space.is_archived = True
    db.commit()

    try:
        from app.services.sync_service import sync_manager
        sync_manager.sync_broadcast(str(current_user.id), "space_updated", {"action": "deleted", "space_id": str(space.id)})
    except Exception:
        pass

    return {"status": "ok", "message": "Study space deleted"}
