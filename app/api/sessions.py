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
    study_space_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db)
):
    """Returns all past sessions for the authenticated student, most recent first."""
    import uuid
    sub = db.query(Subject).filter(Subject.name == subject).first()
    sub_id = sub.id if sub else None

    convos = db.query(Conversation).filter(
        Conversation.user_id == current_user.id,
        Conversation.is_deleted == False
    )
    # Filter by subject
    if sub_id is not None:
        convos = convos.filter(Conversation.subject_id == sub_id)
        
    # Filter by study space if provided
    if study_space_id:
        try:
            convos = convos.filter(Conversation.study_space_id == uuid.UUID(study_space_id))
        except Exception:
            pass

    convos = convos.order_by(Conversation.updated_at.desc()).all()
    
    res = []
    for c in convos:
        res.append({
            "id": str(c.id),
            "chat_title": c.title or "New Chat",
            "last_topic_name": c.last_topic_name,
            "created_at": c.created_at,
            "subject": subject,
            "study_space_id": str(c.study_space_id) if c.study_space_id else None,
        })
        
    return {"sessions": res}


@router.get("/history/{session_id}")
def get_session_history(
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns FULL conversation history for a session including branch information.
    """
    session = db.query(Conversation).filter(
        Conversation.id == session_id,
        Conversation.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    # All messages for building the sibling mapping
    all_messages = db.query(Message).filter(
        Message.conversation_id == session_id
    ).order_by(Message.created_at.asc()).all()

    siblings_map = {}
    for m in all_messages:
        key = (m.parent_message_id, m.role)
        siblings_map.setdefault(key, []).append(str(m.id))

    messages = [m for m in all_messages if m.is_active_branch]

    recent_messages = []
    for m in messages:
        tb = db.query(MessageContentBlock).filter(
            MessageContentBlock.message_id == m.id,
            MessageContentBlock.block_type == "text"
        ).first()
        content = tb.content if tb else ""
        meta = tb.extra_data if tb and tb.extra_data else {}
        sibs = siblings_map.get((m.parent_message_id, m.role), [str(m.id)])
        idx = sibs.index(str(m.id)) if str(m.id) in sibs else 0
        recent_messages.append({
            "id": str(m.id),
            "role": m.role,
            "content": content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "parent_message_id": str(m.parent_message_id) if m.parent_message_id else None,
            "sibling_ids": sibs,
            "sibling_index": idx,
            "sibling_count": len(sibs),
            "sources": meta.get("sources", []),
            "chapter": meta.get("chapter", ""),
            "topic": meta.get("topic", ""),
            "question_type": meta.get("question_type", "conversational"),
            "context": meta.get("context", ""),
            "chunks": meta.get("chunks", []),
            "prompt_messages": meta.get("prompt_messages", []),
        })

    metrics = get_subject_metrics(db, str(current_user.id), session.subject_id) if session.subject_id else {}
    from app.data.cognitive_repo import compute_cognitive_skills
    cognitive_skills = compute_cognitive_skills(metrics) if metrics else {}

    return {
        "session_id": session_id,
        "recent_messages": recent_messages,
        "total_messages": len(recent_messages),
        "metrics": metrics,
        "cognitive_skills": cognitive_skills,
        "subject": session.subject.name if session.subject else "Science",
        "chat_title": session.title or "New Chat",
        "last_topic_name": session.last_topic_name,
        "study_space_id": str(session.study_space_id) if session.study_space_id else None,
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
    
    return {"remark": getattr(session, "remark", "") or ""}


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
            max_tokens=20,
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


# ── Message Branch Activation ────────────────────────────────────────────────

@router.patch("/conversations/{session_id}/messages/{message_id}/activate")
def activate_branch_endpoint(
    session_id: str,
    message_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Activates a specific message branch and adjusts the conversation tree."""
    import uuid
    from app.data.repos.conversation_repo import activate_message_branch

    session = db.query(Conversation).filter(
        Conversation.id == session_id,
        Conversation.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    
    msg = activate_message_branch(db, uuid.UUID(session_id), uuid.UUID(message_id))
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found.")
    db.commit()
    return {"status": "ok", "active_message_id": str(msg.id)}


# ── Conversation Search ──────────────────────────────────────────────────────

@router.get("/conversations/search")
def search_conversations(
    q: str,
    limit: int = 20,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full-text and topic search across conversations and message blocks."""
    from sqlalchemy import or_, func
    if not q or not q.strip():
        return {"results": []}
    
    term = f"%{q.strip().lower()}%"
    
    # 1. Search conversations by title or topic
    conv_query = db.query(Conversation).filter(
        Conversation.user_id == current_user.id,
        Conversation.is_deleted == False,
        or_(
            func.lower(Conversation.title).like(term),
            func.lower(Conversation.last_topic_name).like(term),
        )
    ).order_by(Conversation.updated_at.desc()).limit(limit).all()
    
    found_ids = {c.id for c in conv_query}
    results = []
    for c in conv_query:
        results.append({
            "id": str(c.id),
            "chat_title": c.title or "New Chat",
            "last_topic_name": c.last_topic_name,
            "created_at": c.created_at,
            "match_snippet": c.last_topic_name or c.title,
            "match_type": "title_or_topic",
        })
        
    # 2. Search message content blocks
    if len(results) < limit:
        msg_matches = (
            db.query(Message, MessageContentBlock)
            .join(MessageContentBlock, Message.id == MessageContentBlock.message_id)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .filter(
                Conversation.user_id == current_user.id,
                Conversation.is_deleted == False,
                func.lower(MessageContentBlock.content).like(term),
            )
            .order_by(Message.created_at.desc())
            .limit(limit - len(results))
            .all()
        )
        for m, b in msg_matches:
            if m.conversation_id not in found_ids:
                found_ids.add(m.conversation_id)
                idx = b.content.lower().find(q.strip().lower())
                start = max(0, idx - 40)
                end = min(len(b.content), idx + 60)
                snippet = ("..." if start > 0 else "") + b.content[start:end] + ("..." if end < len(b.content) else "")
                conv = db.query(Conversation).filter(Conversation.id == m.conversation_id).first()
                results.append({
                    "id": str(m.conversation_id),
                    "chat_title": conv.title if conv else "Past Chat",
                    "last_topic_name": conv.last_topic_name if conv else None,
                    "created_at": conv.created_at if conv else m.created_at,
                    "match_snippet": snippet,
                    "match_type": "message",
                })
                
    return {"results": results}


# ── Conversation Sharing ─────────────────────────────────────────────────────

@router.post("/conversations/{session_id}/share")
def create_share_link(
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Creates a frozen read-only share link for a conversation snapshot."""
    import secrets
    from app.data.models.chat import ShareLink

    session = db.query(Conversation).filter(
        Conversation.id == session_id,
        Conversation.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
        
    messages = db.query(Message).filter(
        Message.conversation_id == session_id,
        Message.is_active_branch == True,
    ).order_by(Message.created_at.asc()).all()
    
    snapshot_msgs = []
    for m in messages:
        tb = db.query(MessageContentBlock).filter(
            MessageContentBlock.message_id == m.id,
            MessageContentBlock.block_type == "text"
        ).first()
        content = tb.content if tb else ""
        snapshot_msgs.append({
            "id": str(m.id),
            "role": m.role,
            "content": content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })
        
    token = secrets.token_urlsafe(24)
    share = ShareLink(
        conversation_id=session.id,
        user_id=current_user.id,
        token=token,
        snapshot={
            "title": session.title or "VishwAlpha Tutoring Session",
            "subject": session.subject.name if session.subject else "Science",
            "student_class": getattr(current_user, "class_num", 10),
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "messages": snapshot_msgs,
        }
    )
    db.add(share)
    db.commit()
    return {"token": token, "share_url": f"/share/{token}"}


@router.get("/share/{token}")
def get_shared_conversation(
    token: str,
    db: DBSession = Depends(get_db),
):
    """Public read-only endpoint to view a shared conversation snapshot."""
    from app.data.models.chat import ShareLink
    share = db.query(ShareLink).filter(
        ShareLink.token == token,
        ShareLink.revoked_at.is_(None),
    ).first()
    if not share or not share.snapshot:
        raise HTTPException(status_code=404, detail="Shared link not found or expired.")
    return share.snapshot
