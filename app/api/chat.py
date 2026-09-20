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
