"""
app/main.py
───────────
FastAPI application entry point.
"""
import logging
from contextlib import asynccontextmanager
import time
import asyncio
from typing import Literal

from fastapi import FastAPI, Request
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.config import settings
from app.data.database import init_db
from app.middleware import RequestTracingMiddleware, SecurityHeadersMiddleware

from app.api import auth, student, curriculum, chat, sessions, quiz, admin, spaces, attachments, sync

logger = logging.getLogger("app")

# ── Setup Rate Limiter ────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


# ── App Lifespan ──────────────────────────────────────────────────────────────
async def background_startup_tasks():
    """Runs synchronous startup tasks (like DB init) in a background thread."""
    try:
        logger.info("Starting background DB initialisation...")
        await asyncio.to_thread(init_db)
        logger.info("Background DB initialisation finished.")
    except Exception as e:
        logger.error(f"Error during background startup tasks: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once on startup. Starts background jobs so API boots instantly."""
    logger.info("Starting VishwAlpha AI Tutor API (v2)...")
    
    # Fire and forget the background tasks
    asyncio.create_task(background_startup_tasks())
    
    yield
    logger.info("Shutting down API...")


# ── OpenAPI tag metadata ──────────────────────────────────────────────────────
openapi_tags = [
    {
        "name": "Auth",
        "description": "Register, login, token refresh, logout, and current-user identity. "
                       "All protected routes require `Authorization: Bearer <access_token>`.",
    },
    {
        "name": "Chat",
        "description": "Core tutoring endpoints. Send a question; receive a structured answer "
                       "(JSON) or a real-time SSE stream of tokens. Rate-limited to 30 req/min.",
    },
    {
        "name": "Sessions",
        "description": "Conversation history management: list past sessions, fetch full message "
                       "history, rename sessions, generate AI titles, branch activation, and sharing.",
    },
    {
        "name": "Student",
        "description": "Student cognitive profile, per-subject metrics, topic mastery heatmap, "
                       "and personalised learning-path view.",
    },
    {
        "name": "Quiz",
        "description": "AI-generated adaptive quizzes. Generate → answer question-by-question → "
                       "finish to get score + AI feedback + cognitive profile update.",
    },
    {
        "name": "Curriculum",
        "description": "Public curriculum browse endpoints to populate dropdowns "
                       "(subjects, chapters, topics). No authentication required.",
    },
    {
        "name": "Study Spaces",
        "description": "Named per-subject workspaces that group conversations with "
                       "custom tutor instructions.",
    },
    {
        "name": "Attachments",
        "description": "Upload images/PDFs. The server runs multimodal vision analysis "
                       "and returns extracted text + a topic hint ready for use in `POST /chat`.",
    },
    {
        "name": "RealTime Sync",
        "description": "WebSocket + HTTP endpoints for cross-device state synchronisation "
                       "(quiz results, study-space changes broadcast to all connected tabs).",
    },
    {
        "name": "Admin",
        "description": "PDF ingestion and ingestion-log inspection. Protected by "
                       "`X-Admin-Key` header — **not** a JWT. Admin-only.",
    },
    {
        "name": "System",
        "description": "Health-check endpoint. No authentication required.",
    },
]


# ── Factory ───────────────────────────────────────────────────────────────────
def create_app() -> FastAPI:
    app = FastAPI(
        title="VishwAlpha AI Tutor API",
        description=(
            "# VishwAlpha AI Tutor\n\n"
            "Personalised NCERT curriculum tutor for Indian school students (Classes 6–12). "
            "Students ask questions via chat; the system retrieves relevant textbook context "
            "via pgvector RAG and generates pedagogically structured answers using Azure OpenAI.\n\n"
            "## Authentication\n\n"
            "All protected endpoints require a JWT Bearer token in the `Authorization` header:\n\n"
            "```\nAuthorization: Bearer <access_token>\n```\n\n"
            "Obtain a token from `POST /auth/login` or `POST /auth/register`. "
            "Tokens expire after **7 days** by default.\n\n"
            "Admin-only routes (`/admin/*`) use a separate static `X-Admin-Key` header instead of JWT.\n\n"
            "## Rate Limits\n\n"
            "| Scope | Limit |\n"
            "|-------|-------|\n"
            "| Chat endpoints | 30 req / minute |\n"
            "| Session end | 10 req / minute |\n"
            "| All other reads | 120 req / minute |\n\n"
            "## SSE Streaming\n\n"
            "`POST /chat/stream` returns `text/event-stream`. Each line is "
            "`data: <json>\\n\\n`. Event types: `meta`, `token`, `done`, `error`."
        ),
        version="2.0.0",
        openapi_tags=openapi_tags,
        contact={
            "name": "VishwAlpha Engineering",
            "email": "dev@vishwalpha.app",
        },
        license_info={
            "name": "Proprietary",
        },
        servers=[
            {"url": "http://localhost:8000", "description": "Local development"},
            {"url": "https://vishwalpha-ai-tutor.onrender.com", "description": "Production (Render)"},
            {"url": "https://vishwalpha-ai-tutor-production.up.railway.app", "description": "Production (Railway)"},
        ],
        lifespan=lifespan,
    )

    # ── Exception handlers
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errs = exc.errors()
        if errs:
            first = errs[0]
            loc = " -> ".join(str(l) for l in first.get("loc", []) if l != "body")
            msg = first.get("msg", "Invalid value")
            detail = f"{loc}: {msg}" if loc else msg
        else:
            detail = "Invalid request parameters"
        logger.warning(f"Validation error on {request.method} {request.url.path}: {detail}")
        return JSONResponse(status_code=400, content={"detail": detail})

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal server error occurred. Please try again."}
        )

    # ── CORS: origins and regex from settings ─────────────────────────────────
    _origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_origin_regex=settings.ALLOWED_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestTracingMiddleware)

    # ── Routers
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(sessions.router)
    app.include_router(student.router)
    app.include_router(curriculum.router)
    app.include_router(quiz.router)
    app.include_router(admin.router)
    app.include_router(spaces.router)
    app.include_router(attachments.router)
    app.include_router(sync.router)

    # ── Static uploads directory for student attachments
    uploads_dir = Path("uploads")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

    class HealthResponse(BaseModel):
        status: Literal["ok"]
        version: str

    @app.get(
        "/",
        tags=["System"],
        summary="Root endpoint",
        description="Returns service metadata and links to documentation and health check.",
    )
    def root():
        return {
            "name": "VishwAlpha AI Tutor API",
            "version": "2.0.0",
            "status": "healthy",
            "docs": "/docs",
            "health": "/health",
        }

    @app.get(
        "/health",
        tags=["System"],
        summary="Health check",
        description="Returns `{status: ok}` when the API is running. No authentication required. "
                    "Use this endpoint for uptime monitoring.",
        response_model=HealthResponse,
    )
    def health_check():
        return HealthResponse(status="ok", version="2.0.0")

    return app


# Uvicorn entry point
app = create_app()
