"""
api.py
──────
FastAPI application for the VishwAlpha AI Tutor.

Endpoints:
  POST /chat               — Send a question, receive a tutoring answer
  GET  /history/{session}   — Retrieve conversation history for a session
  GET  /health              — Health check
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from db.database import init_db, SessionLocal
from db.memory import get_history, get_session_message_count, get_session_metrics, update_session_metrics_directly
from db.metrics import apply_profile_metrics
from schemas import ChatRequest, ChatResponse, ChatMessage, UpdateMetricsRequest
from tutor.chat import chat

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# App lifecycle
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once on startup: ensures all DB tables exist."""
    logger.info("Starting VishwAlpha AI Tutor API...")
    init_db()
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="VishwAlpha AI Tutor",
    description="Personalised NCERT curriculum tutor powered by RAG + Groq LLM",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow all origins for development — restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    """
    Send a question and receive a tutoring answer.

    The system will:
      1. Route the question to the relevant curriculum topic
      2. Retrieve textbook context from Qdrant
      3. Generate a personalised answer using the LLM
      4. Save the conversation turn to PostgreSQL

    Provide a `session_id` to continue an existing conversation.
    Leave it empty for a new session (one will be generated for you).
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    try:
        response = chat(request)
        return response
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while processing your question.")


@app.get("/history/{session_id}")
def history_endpoint(session_id: str):
    """
    Retrieve conversation history for a given session.

    Returns:
      - memory_summary: compressed summary of older turns
      - recent_messages: last 2 turn pairs (verbatim)
      - total_messages: total message count in session
      - metrics: student learning metrics
    """
    memory_summary, recent = get_history(session_id)
    total = get_session_message_count(session_id)
    metrics = get_session_metrics(session_id)

    if total == 0:
        raise HTTPException(status_code=404, detail="Session not found.")

    return {
        "session_id": session_id,
        "memory_summary": memory_summary,
        "recent_messages": [m.model_dump() for m in recent],
        "total_messages": total,
        "metrics": metrics,
    }


@app.post("/session/{session_id}/metrics")
def update_metrics_endpoint(session_id: str, request: UpdateMetricsRequest):
    """
    Manually update a session's metrics or apply a predefined profile preset.
    """
    db = SessionLocal()
    try:
        if request.profile_name:
            updated = apply_profile_metrics(session_id, request.profile_name, db)
            return {"status": "success", "message": f"Applied profile '{request.profile_name}'", "metrics": updated}
        
        if request.metrics:
            update_session_metrics_directly(session_id, request.metrics)
            # Retrieve updated metrics
            updated = get_session_metrics(session_id)
            return {"status": "success", "message": "Metrics updated successfully", "metrics": updated}
            
        raise HTTPException(status_code=400, detail="Must provide either metrics or profile_name.")
    except Exception as e:
        logger.error(f"Error updating metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update metrics: {str(e)}")
    finally:
        db.close()


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "VishwAlpha AI Tutor"}
