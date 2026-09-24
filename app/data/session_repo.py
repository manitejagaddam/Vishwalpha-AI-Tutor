"""
app/data/session_repo.py
────────────────────────
Persistent student memory, real-time fast memory extraction, and task tracking.
All memory operations are non-destructive (historical memories from months/years
ago are preserved permanently with provenance and deduplication).
"""
import json
import logging
import uuid
from typing import Optional
from sqlalchemy import or_, func
from app.data.database import managed_session
from app.data.models.learning import StudentMemoryItem, StudentTask
from app.infra.azure_openai_client import get_openai
from app.config import settings

logger = logging.getLogger(__name__)


def update_session_remark(session_id: str, remark: str) -> None:
    # Deprecated: Conversations no longer store remarks directly
    pass


def update_session_mood(session_id: str, mood: str) -> None:
    # Deprecated: Conversations no longer store mood directly
    pass


def get_student_memory(
    student_id: str, 
    subject_id: Optional[int] = None, 
    limit: int = 25
) -> list[str]:
    """
    Returns active durable facts for a student.
    Crucial fix: Includes both subject-specific facts AND cross-subject facts
    (where subject_id IS NULL) so general student habits, goals, and style
    preferences are never lost when switching subjects.
    """
    with managed_session() as db:
        query = db.query(StudentMemoryItem).filter(
            StudentMemoryItem.user_id == student_id,
            StudentMemoryItem.is_active == True,
        )
        if subject_id is not None:
            query = query.filter(
                or_(
                    StudentMemoryItem.subject_id == subject_id,
                    StudentMemoryItem.subject_id.is_(None),
                )
            )
        else:
            query = query.filter(StudentMemoryItem.subject_id.is_(None))

        records = query.order_by(StudentMemoryItem.created_at.desc()).limit(limit).all()
        return [r.fact for r in records]


def add_fast_memory_fact(
    student_id: str,
    fact: str,
    subject_id: Optional[int] = None,
    source_message_id: Optional[str] = None,
) -> bool:
    """
    Fast, real-time insertion of a memory fact (from per-turn regex or heuristic).
    Deduplicates against existing active facts. Returns True if inserted, False if existed.
    """
    cleaned_fact = fact.strip()
    if not cleaned_fact:
        return False

    msg_uuid = None
    if source_message_id:
        try:
            msg_uuid = uuid.UUID(str(source_message_id))
        except (ValueError, TypeError):
            msg_uuid = None

    with managed_session() as db:
        existing = db.query(StudentMemoryItem).filter(
            StudentMemoryItem.user_id == student_id,
            StudentMemoryItem.is_active == True,
            func.lower(StudentMemoryItem.fact) == cleaned_fact.lower(),
        ).first()

        if existing:
            return False  # Already memorized

        db.add(StudentMemoryItem(
            user_id=student_id,
            subject_id=subject_id,
            source_message_id=msg_uuid,
            fact=cleaned_fact,
            is_active=True,
        ))
        logger.info(f"[Memory] Fast captured fact for user {student_id}: '{cleaned_fact}'")
        return True


def consolidate_student_memories(
    student_id: str,
    subject_id: Optional[int],
    new_facts: list[str],
    resolved_facts: Optional[list[str]] = None,
    source_message_id: Optional[str] = None,
) -> None:
    """
    Non-destructive memory consolidation.
    1. Preserves all past memories (never deletes old historical facts).
    2. Inserts new unique facts with deduplication.
    3. Soft-deactivates (is_active=False) facts explicitly resolved by the student.
    """
    msg_uuid = None
    if source_message_id:
        try:
            msg_uuid = uuid.UUID(str(source_message_id))
        except (ValueError, TypeError):
            msg_uuid = None

    with managed_session() as db:
        # Load existing active facts to prevent duplicate inserts
        existing_items = db.query(StudentMemoryItem).filter(
            StudentMemoryItem.user_id == student_id,
            StudentMemoryItem.is_active == True,
        ).all()
        existing_facts_lower = {item.fact.strip().lower(): item for item in existing_items}

        # 1. Soft-deactivate resolved facts (e.g. misconceptions student corrected)
        if resolved_facts:
            for resolved in resolved_facts:
                if not isinstance(resolved, str):
                    continue
                res_clean = resolved.strip().lower()
                for fact_low, item in existing_facts_lower.items():
                    if res_clean in fact_low or fact_low in res_clean:
                        item.is_active = False
                        logger.info(f"[Memory] Deactivated resolved fact: '{item.fact}'")

        # 2. Add new facts with deduplication
        added_count = 0
        for fact in (new_facts or []):
            if not isinstance(fact, str):
                continue
            clean = fact.strip()
            if not clean:
                continue
            clean_low = clean.lower()

            # Check if this fact or very close variant already exists
            already_exists = any(
                clean_low == ef or (len(clean_low) > 15 and clean_low in ef)
                for ef in existing_facts_lower
            )
            if not already_exists:
                db.add(StudentMemoryItem(
                    user_id=student_id,
                    subject_id=subject_id,
                    source_message_id=msg_uuid,
                    fact=clean,
                    is_active=True,
                ))
                existing_facts_lower[clean_low] = None  # Prevent duplicates within same batch
                added_count += 1

        if added_count > 0:
            logger.info(f"[Memory] Consolidated {added_count} new durable fact(s) for user {student_id}")


def update_student_memory(
    student_id: str,
    subject_id: Optional[int],
    remark: str,
    context: str,
) -> None:
    """
    Legacy-compatible non-destructive memory update.
    Extracts new facts from remark/context and appends them without deleting past facts.
    """
    if not remark:
        return

    # Treat the remark as a candidate fact or summary observation
    add_fast_memory_fact(
        student_id=student_id,
        fact=remark.strip(),
        subject_id=subject_id,
    )


def get_student_tasks(student_id: str, subject_id: Optional[int] = None) -> list[str]:
    with managed_session() as db:
        tasks = db.query(StudentTask).filter(
            StudentTask.user_id == student_id,
            StudentTask.subject_id == subject_id,
            StudentTask.is_done == False,
        ).order_by(StudentTask.created_at.desc()).limit(5).all()
        return [t.task for t in tasks]
