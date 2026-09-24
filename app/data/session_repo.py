"""
app/data/session_repo.py
────────────────────────
Legacy adapter for memory and task logic.
"""
import json
import logging
from sqlalchemy import func
from app.data.database import managed_session
from app.data.models.learning import StudentMemoryItem, StudentTask
from app.infra.azure_openai_client import get_openai
from app.config import settings

logger = logging.getLogger(__name__)

MEMORY_MERGE_PROMPT = """
You are maintaining a persistent memory list for a student.
Merge the new remark into the existing memory list.
Existing: {existing_memory}
New Remark: {remark}
Context: {context}

Return a JSON array of strings (the updated memory facts).
"""

def update_session_remark(session_id: str, remark: str) -> None:
    # Deprecated: Conversations no longer store remarks directly
    pass

def update_session_mood(session_id: str, mood: str) -> None:
    # Deprecated: Conversations no longer store mood directly
    pass

def get_student_memory(student_id: str, subject_id: int | None = None) -> list[str]:
    with managed_session() as db:
        records = db.query(StudentMemoryItem).filter(
            StudentMemoryItem.user_id == student_id,
            StudentMemoryItem.subject_id == subject_id,
            StudentMemoryItem.is_active == True,
        ).all()
        return [r.fact for r in records]

def update_student_memory(
    student_id: str,
    subject_id: int | None,
    remark: str,
    context: str,
) -> None:
    """Uses an LLM to merge new observations into the persistent memory list."""
    existing = get_student_memory(student_id, subject_id)
    existing_str = "\n".join(f"- {m}" for m in existing) if existing else "(none yet)"

    try:
        client = get_openai()
        resp = client.chat.completions.create(
            messages=[{
                "role": "user",
                "content": MEMORY_MERGE_PROMPT.format(
                    existing_memory=existing_str,
                    remark=remark,
                    context=context[:500],
                ),
            }],
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            temperature=0.2,
            max_tokens=300,
        )
        raw = resp.choices[0].message.content.strip()
        # Extract JSON array
        start, end = raw.find("["), raw.rfind("]")
        new_memory = json.loads(raw[start:end + 1]) if start != -1 else existing
    except Exception as exc:
        logger.warning(f"Memory merge failed: {exc}")
        new_memory = existing

    # Safety guard: never delete existing memory if the LLM returned nothing valid.
    # Deleting before re-inserting would wipe all student memory on LLM failure.
    if not isinstance(new_memory, list) or not new_memory:
        logger.warning(
            "[Memory] LLM returned empty or invalid memory list — preserving existing items."
        )
        return

    with managed_session() as db:
        # Delete old active memories for this subject/user to replace them
        db.query(StudentMemoryItem).filter(
            StudentMemoryItem.user_id == student_id,
            StudentMemoryItem.subject_id == subject_id,
        ).delete()

        # Insert new updated facts
        for fact in new_memory:
            if isinstance(fact, str) and fact.strip():
                db.add(StudentMemoryItem(
                    user_id=student_id,
                    subject_id=subject_id,
                    fact=fact.strip(),
                ))

def get_student_tasks(student_id: str, subject_id: int | None = None) -> list[str]:
    with managed_session() as db:
        tasks = db.query(StudentTask).filter(
            StudentTask.user_id == student_id,
            StudentTask.subject_id == subject_id,
            StudentTask.is_done == False,
        ).order_by(StudentTask.created_at.desc()).limit(5).all()
        return [t.task for t in tasks]
