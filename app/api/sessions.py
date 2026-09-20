"""
app/api/sessions.py
-------------------
Session history routes - JWT protected.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.data.database import get_db
from app.data.models.chat import Conversation, Message, MessageContentBlock
from app.data.models.platform import User
from app.api.deps import get_current_user
from app.data.models.content import Subject
from app.data.cognitive_repo import get_subject_metrics
from app.data.repos.conversation_repo import update_conversation_title

router = APIRouter(tags=["Sessions"])


@router.get("/sessions")
def list_sessions(
    subject: str = "Science",
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db)
):
    """Returns all past sessions for the authenticated student, most recent first."""
    sub = db.query(Subject).filter(Subject.name == subject).first()
    sub_id = sub.id if sub else None

    convos = db.query(Conversation).filter(
        Conversation.user_id == current_user.id,
        Conversation.subject_id == sub_id,
        Conversation.is_deleted == False
    ).order_by(Conversation.updated_at.desc()).all()
    
    res = []
    for c in convos:
        res.append({
            "id": str(c.id),
            "chat_title": c.title or "New Chat",
            "last_topic_name": c.last_topic_name,
            "created_at": c.created_at,
            "subject": subject
        })
        
    return {"sessions": res}


@router.get("/history/{session_id}")
def get_session_history(
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns FULL conversation history for a session.
    """
    session = db.query(Conversation).filter(
        Conversation.id == session_id,
        Conversation.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    messages = db.query(Message).filter(
        Message.conversation_id == session_id,
        Message.is_active_branch == True
    ).order_by(Message.created_at.asc()).all()

    recent_messages = []
    for m in messages:
        tb = db.query(MessageContentBlock).filter(
            MessageContentBlock.message_id == m.id,
            MessageContentBlock.block_type == "text"
        ).first()
        content = tb.content if tb else ""
        recent_messages.append({
            "id": str(m.id),
            "role": m.role,
            "content": content,
            "created_at": m.created_at
        })

    metrics = get_subject_metrics(db, str(current_user.id), session.subject_id) if session.subject_id else {}

    return {
        "session_id": session_id,
        "recent_messages": recent_messages,
        "total_messages": len(recent_messages),
        "metrics": metrics,
        "subject": session.subject.name if session.subject else "Science",
        "chat_title": session.title or "New Chat",
        "last_topic_name": session.last_topic_name,
    }


@router.get("/sessions/{session_id}/remark")
def session_remark(
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns the latest AI-generated teacher remark for a session."""
    session = db.query(Conversation).filter(
        Conversation.id == session_id,
        Conversation.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    
    return {"remark": "Keep up the good work on this topic!"}


# ── Title Management ──────────────────────────────────────────────────────────

class TitleUpdateRequest(BaseModel):
    title: str


@router.patch("/sessions/{session_id}/title")
def update_title(
    session_id: str,
    body: TitleUpdateRequest,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually set a custom title for a session."""
    session = db.query(Conversation).filter(
        Conversation.id == session_id,
        Conversation.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    update_conversation_title(db, session.id, body.title.strip()[:120])
    db.commit()
    return {"title": session.title}


@router.post("/sessions/{session_id}/generate-title")
def generate_title(
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Regenerates the chat title from the first few messages using AI.
    Returns the generated title and saves it to the DB.
    This mimics Claude's smart heading: short, specific, no fluff.
    """
    session = db.query(Conversation).filter(
        Conversation.id == session_id,
        Conversation.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    # Grab first 3 messages to build context for the title
    messages = (
        db.query(Message, MessageContentBlock)
        .join(MessageContentBlock, Message.id == MessageContentBlock.message_id)
        .filter(
            Message.conversation_id == session_id,
            Message.is_active_branch == True,
            MessageContentBlock.block_type == "text",
        )
        .order_by(Message.created_at.asc())
        .limit(6)
        .all()
    )

    if not messages:
        return {"title": session.title or "New Chat"}

    snippet = "\n".join(
        f"{m.Message.role.upper()}: {m.MessageContentBlock.content[:200]}"
        for m in messages
    )

    try:
        from app.infra.azure_openai_client import get_openai
        from app.config import settings

        client = get_openai()
        prompt = (
            "Generate a short, specific chat title (3-6 words, no punctuation, no quotes) "
            "for this tutoring conversation. Be precise about the topic — like Claude does it.\n\n"
            f"Conversation:\n{snippet}\n\n"
            "Title:"
        )
        resp = client.chat.completions.create(
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=20,
            temperature=0.3,
        )
        title = resp.choices[0].message.content.strip().strip('"').strip("'")[:120]
    except Exception:
        # Fallback: first student message truncated
        first = messages[0].MessageContentBlock.content
        words = first.split()
        title = " ".join(words[:6]) + ("..." if len(words) > 6 else "")

    update_conversation_title(db, session.id, title)
    db.commit()
    return {"title": title}
