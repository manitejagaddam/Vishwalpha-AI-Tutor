"""
app/data/repos/conversation_repo.py
───────────────────────────────────
Repository for Conversation and Message tree operations.
"""
import uuid
from typing import List, Tuple, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, update

from app.data.models.chat import Conversation, Message, MessageContentBlock

def get_conversation(db: Session, conversation_id: uuid.UUID) -> Optional[Conversation]:
    """Fetches a conversation by ID."""
    return db.query(Conversation).filter(Conversation.id == conversation_id).first()

def get_or_create_conversation(
    db: Session,
    user_id: uuid.UUID,
    conversation_id: Optional[uuid.UUID] = None,
    subject_id: Optional[int] = None,
) -> Conversation:
    """Returns an existing conversation or creates a new one."""
    if conversation_id:
        conv = get_conversation(db, conversation_id)
        if conv and conv.user_id == user_id:
            return conv

    # Create new
    conv = Conversation(
        id=conversation_id or uuid.uuid4(),
        user_id=user_id,
        subject_id=subject_id,
        is_pinned=False,
        is_archived=False,
        is_deleted=False,
        total_messages=0
    )
    db.add(conv)
    db.flush()
    return conv

def save_message(
    db: Session,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    parent_message_id: Optional[uuid.UUID] = None,
    idempotency_key: Optional[str] = None,
    block_type: str = "text",
    response_time_ms: Optional[int] = None,
    sentiment: Optional[str] = None,
    bloom_level: Optional[str] = None,
    contains_question: Optional[bool] = None,
    topic_id: Optional[int] = None,
) -> Message:
    """
    Saves a message node in the tree with a single text content block.
    If idempotency_key exists, returns the existing message.
    """
    if idempotency_key:
        existing = db.query(Message).filter_by(idempotency_key=idempotency_key).first()
        if existing:
            return existing

    # Create Message Node
    msg = Message(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        parent_message_id=parent_message_id,
        role=role,
        is_active_branch=True,
        idempotency_key=idempotency_key,
        response_time_ms=response_time_ms,
        sentiment=sentiment,
        bloom_level=bloom_level,
        contains_question=contains_question,
        topic_id=topic_id,
        token_count=len(content) // 4,  # rough estimate
    )
    db.add(msg)
    db.flush()

    # Create Content Block
    block = MessageContentBlock(
        message_id=msg.id,
        block_type=block_type,
        content=content,
        block_index=0
    )
    db.add(block)
    
    # Update conversation active message and count
    conv = get_conversation(db, conversation_id)
    if conv:
        conv.active_message_id = msg.id
        conv.total_messages += 1
        
    db.flush()
    return msg

def get_message_history(
    db: Session, 
    conversation_id: uuid.UUID, 
    leaf_message_id: Optional[uuid.UUID] = None,
    limit: int = 10
) -> List[dict]:
    """
    Walks up the message tree from leaf_message_id to root.
    Returns a list of dicts: {"role": str, "content": str} ordered chronologically.
    """
    if not leaf_message_id:
        return []

    # Load all messages and blocks for this conversation into memory (usually small)
    messages = db.query(Message).filter(Message.conversation_id == conversation_id).all()
    blocks = db.query(MessageContentBlock).filter(
        MessageContentBlock.message_id.in_([m.id for m in messages])
    ).all()
    
    msg_dict = {m.id: m for m in messages}
    # Group blocks by message_id and sort by index
    block_dict = {}
    for b in blocks:
        block_dict.setdefault(b.message_id, []).append(b)
    for m_id in block_dict:
        block_dict[m_id].sort(key=lambda x: x.block_index)

    # Walk up the tree
    path = []
    current_id = leaf_message_id
    while current_id and current_id in msg_dict:
        m = msg_dict[current_id]
        m_blocks = block_dict.get(m.id, [])
        # Combine text blocks
        content = "\n\n".join([b.content for b in m_blocks if b.content])
        path.append({
            "role": m.role,
            "content": content,
            "id": m.id
        })
        current_id = m.parent_message_id
        
        if len(path) >= limit:
            break

    # Reverse to chronological order (oldest first)
    path.reverse()
    return path

def update_conversation_title(db: Session, conversation_id: uuid.UUID, title: str):
    """Updates the generated title for a conversation."""
    db.query(Conversation).filter(Conversation.id == conversation_id).update({"title": title})
    db.flush()
