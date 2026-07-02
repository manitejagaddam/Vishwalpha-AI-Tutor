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

from core.db_session import managed_session
from db.database import init_db
from db.memory import get_history, get_session_message_count
from db.profile import get_subject_metrics, apply_profile_metrics, update_subject_profile
from db.models import ConversationSession
from schemas import ChatRequest, ChatResponse, UpdateMetricsRequest
from tutor.chat import chat

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once on startup: ensures all DB tables exist and cleans up old prompt logs."""
    logger.info("Starting VishwAlpha AI Tutor API...")
    init_db()
    
    from db.memory import cleanup_old_prompt_logs
    cleanup_old_prompt_logs(days=5)
    
    yield
    logger.info("Shutting down.")

app = FastAPI(
    title="VishwAlpha AI Tutor",
    description="Personalised NCERT curriculum tutor powered by RAG + Groq LLM",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    """
    Send a question and receive a tutoring answer.
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
    """
    memory_summary, recent = get_history(session_id)
    total = get_session_message_count(session_id)
    
    if total == 0:
        raise HTTPException(status_code=404, detail="Session not found.")
        
    with managed_session() as db:
        session = db.query(ConversationSession).filter(ConversationSession.id == session_id).first()
        if session:
            metrics = get_subject_metrics(db, session.student_id, session.subject)
        else:
            metrics = {}

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
    with managed_session() as db:
        session = db.query(ConversationSession).filter(ConversationSession.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found.")
            
        student_id = session.student_id
        subject = session.subject
        
        try:
            if request.profile_name:
                updated = apply_profile_metrics(student_id, subject, request.profile_name, db)
                return {"status": "success", "message": f"Applied profile '{request.profile_name}'", "metrics": updated}
            
            if request.metrics:
                # Format adjustments for update_subject_profile
                raw_adjustments = {}
                current_metrics = get_subject_metrics(db, student_id, subject)
                for key, new_val in request.metrics.items():
                    if key in current_metrics:
                        raw_adjustments[key] = {"delta": float(new_val) - float(current_metrics[key])}
                
                update_subject_profile(db, student_id, subject, raw_adjustments, source="manual")
                
                updated = get_subject_metrics(db, student_id, subject)
                return {"status": "success", "message": "Metrics updated successfully", "metrics": updated}
                
            raise HTTPException(status_code=400, detail="Must provide either metrics or profile_name.")
        except Exception as e:
            logger.error(f"Error updating metrics: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to update metrics: {str(e)}")
