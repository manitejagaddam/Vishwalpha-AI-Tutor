"""
app/main.py
───────────
FastAPI application entry point.
"""
import logging
from contextlib import asynccontextmanager
import time
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.data.database import init_db
from app.middleware import RequestTracingMiddleware, SecurityHeadersMiddleware

from app.api import auth, student, curriculum, chat, sessions, quiz, admin, spaces

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


# ── Factory ───────────────────────────────────────────────────────────────────
def create_app() -> FastAPI:
    app = FastAPI(
        title="VishwAlpha AI Tutor",
        description="Personalised NCERT curriculum tutor powered by RAG + Azure OpenAI (GPT-4.1-mini, text-embedding-3-small)",
        version="2.0.0",
        lifespan=lifespan,
    )

    # ── Exception handlers
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # ── CORS: origins from env var (comma-separated list) ──────────────────────
    _origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
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

    @app.get("/health", tags=["System"])
    def health_check():
        return {"status": "ok", "version": "2.0.0"}

    return app


# Uvicorn entry point
app = create_app()
