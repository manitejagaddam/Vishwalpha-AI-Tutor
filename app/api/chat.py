"""
app/api/chat.py
───────────────
Main chat endpoint.
"""
import logging
from fastapi import APIRouter, HTTPException

from app.schemas import ChatRequest, ChatResponse
from app.services.chat_orchestrator import chat

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Chat"])


@router.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    """
    Send a question and receive a tutoring answer.
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    try:
        response = chat(request)
        return response
    except Exception as exc:
        logger.error(f"Chat error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="An error occurred while processing your question."
        )
