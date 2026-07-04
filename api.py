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
from db.database import init_db, SessionLocal
from db.memory import get_history, get_session_message_count, get_student_sessions, get_student_memory, get_session_remark
from db.profile import get_subject_metrics, update_subject_profile
from db.metrics import apply_profile_metrics, compute_cognitive_skills
from db.models import ConversationSession
from db.auth import register_student, login_student
from schemas import (
    ChatRequest, ChatResponse, UpdateMetricsRequest,
    RegisterRequest, LoginRequest, AuthResponse
)
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

@app.post("/auth/register", response_model=AuthResponse)
def register_endpoint(request: RegisterRequest):
    db = SessionLocal()
    try:
        student = register_student(
            db=db,
            username=request.username,
            email=request.email,
            password=request.password,
            class_num=request.class_num
        )
        return AuthResponse(
            student_id=student.id,
            username=student.username,
            class_num=student.class_num,
            message="Registration successful"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()

@app.post("/auth/login", response_model=AuthResponse)
def login_endpoint(request: LoginRequest):
    db = SessionLocal()
    try:
        student = login_student(db, request.username, request.password)
        if not student:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        return AuthResponse(
            student_id=student.id,
            username=student.username,
            class_num=student.class_num,
            message="Login successful"
        )
    finally:
        db.close()

@app.get("/sessions")
def get_sessions_endpoint(student_id: str, subject: str = "Science"):
    """Get all past sessions for a student."""
    sessions = get_student_sessions(student_id, subject)
    return {"sessions": sessions}

@app.get("/student/memory")
def get_student_memory_endpoint(student_id: str, subject: str = "Science"):
    """Get learning memory for a student."""
    memory_str = get_student_memory(student_id, subject)
    return {"memory": memory_str}

@app.get("/student/profile")
def get_student_profile_endpoint(student_id: str, subject: str = "Science"):
    """Get cognitive metrics for a student."""
    with managed_session() as db:
        metrics = get_subject_metrics(db, student_id, subject)
        skills = compute_cognitive_skills(metrics)
    return {"metrics": metrics, "cognitive_skills": skills}

@app.get("/sessions/{session_id}/remark")
def get_session_remark_endpoint(session_id: str):
    remark = get_session_remark(session_id)
    return {"remark": remark}

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
