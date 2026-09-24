"""
app/api/chat.py
───────────────
Chat endpoints.

POST /chat        — Standard JSON response (blocking, backwards-compatible)
POST /chat/stream — Server-Sent Events streaming response (real-time tokens)

Both endpoints require a valid JWT Bearer token.
student_id is extracted from the token — NOT from the request body.

SSE Event format (for /chat/stream):
    data: {"type": "meta",  "session_id": "...", "is_session_start": true}
    data: {"type": "token", "content": "He"}
    data: {"type": "token", "content": "llo"}
    data: {"type": "done",  "sources": [...], "metrics": {...}, ...}
    data: {"type": "error", "detail": "..."}      (only on failure)
"""
import logging
import asyncio

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse

from app.schemas.chat import ChatRequest, ChatResponse
from app.api.deps import get_current_user
from app.data.models.platform import User
from app.services.chat_orchestrator import chat, chat_stream

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Chat"])


# ── Standard (blocking) chat ───────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    user: User = Depends(get_current_user),
):
    """
    Send a question and receive a complete tutoring response (JSON).
    JWT token must be provided via Authorization: Bearer <token>.
    """
    try:
        # Run the synchronous orchestrator in a thread pool so we don't
        # block the async event loop under concurrent load.
        response = await asyncio.to_thread(chat, request, user)
        return response
    except Exception as exc:
        logger.error(f"Chat error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="An error occurred while processing your question."
        )


# ── Streaming (SSE) chat ───────────────────────────────────────────────────────

@router.post("/chat/stream")
async def chat_stream_endpoint(
    request: ChatRequest,
    user: User = Depends(get_current_user),
):
    """
    Send a question and receive a streaming SSE response.

    The response is a stream of ``text/event-stream`` events.
    First event: ``{"type": "meta", "session_id": "...", "is_session_start": ...}``
    Middle events: ``{"type": "token", "content": "<chunk>"}``
    Final event: ``{"type": "done", "sources": [...], "metrics": {...}, ...}``

    The frontend reads these events and progressively renders the answer.
    """
    async def _generate():
        try:
            async for chunk in chat_stream(request, user):
                yield chunk
        except Exception as exc:
            import json
            logger.error(f"Streaming error: {exc}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",    # disable Nginx proxy buffering
        },
    )


# ── Session Management ─────────────────────────────────────────────────────────

from pydantic import BaseModel
from fastapi import BackgroundTasks
from app.services.chat_orchestrator import run_deep_session_sync, _get_session_cache
from app.data.repos.conversation_repo import get_conversation, get_message_history

class SessionEndRequest(BaseModel):
    conversation_id: str
    subject_id: int | None = None

@router.post("/chat/session/end")
async def chat_session_end_endpoint(
    request: SessionEndRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    """
    Explicitly ends a chat session. Triggers the heavy Deep Session Sync 
    (memory extraction, weak topics recalculation, learning preferences) 
    in the background so it doesn't block the client.
    """
    if not request.conversation_id or not str(request.conversation_id).strip() or request.conversation_id in ("new", "null", "undefined"):
        return {"status": "skipped", "detail": "Empty or new conversation_id"}

    # Fetch conversation to ensure it exists and belongs to user
    from app.data.database import managed_session
    with managed_session() as db:
        conv = get_conversation(db, request.conversation_id)
        if not conv or str(conv.user_id) != str(user.id):
            return {"status": "skipped", "detail": "Conversation not found"}
            
        # Get the latest message for context
        history = get_message_history(db, request.conversation_id, limit=2)
        context_snippet = ""
        if len(history) >= 2:
            context_snippet = history[-2]["content"][:200] + " → " + history[-1]["content"][:200]
        elif len(history) == 1:
            context_snippet = history[0]["content"][:200]
            
    # Trigger deep sync in background
    background_tasks.add_task(
        run_deep_session_sync,
        str(user.id),
        request.subject_id,
        request.conversation_id,
        context_snippet
    )
    
    # Clear the last sync timestamp in Redis so next session starts fresh
    _sc = _get_session_cache()
    sid_int = int(request.subject_id) if request.subject_id else 0
    if _sc._client:
        _sc._client.delete(f"sess:last_sync:{user.id}:{sid_int}")
        
    return {"status": "success", "message": "Session deep sync queued."}


# ── Message Feedback ──────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    message_id: str
    rating: int  # 1 for thumbs up, -1 for thumbs down, 0 for neutral/reset
    feedback_text: str | None = None

@router.post("/chat/feedback")
async def chat_feedback_endpoint(
    request: FeedbackRequest,
    user: User = Depends(get_current_user),
):
    """Saves student thumbs-up / thumbs-down rating on a tutor message."""
    import uuid
    from app.data.database import managed_session
    from app.data.models.chat import MessageFeedback

    with managed_session() as db:
        mid = uuid.UUID(request.message_id)
        existing = db.query(MessageFeedback).filter(
            MessageFeedback.message_id == mid,
            MessageFeedback.user_id == user.id,
        ).first()

        if existing:
            existing.rating = request.rating
            if request.feedback_text is not None:
                existing.reason = request.feedback_text
        else:
            fb = MessageFeedback(
                id=uuid.uuid4(),
                message_id=mid,
                user_id=user.id,
                rating=request.rating,
                reason=request.feedback_text,
            )
            db.add(fb)
        db.commit()

    return {"status": "success", "rating": request.rating}
