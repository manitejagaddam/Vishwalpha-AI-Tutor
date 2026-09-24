"""
app/api/auth.py
───────────────
Authentication routes: register, login, refresh, logout, me.
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
import logging

from app.config import settings
from app.data.database import get_db
from app.data.repos.auth_repo import register_student, login_student, store_refresh_token
from app.schemas.auth import RegisterRequest, LoginRequest, AuthResponse, UserSummary
from app.api.deps import create_access_token, create_refresh_token, get_current_user
from app.data.models.learning import StudentProfile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

# Warn on startup if ADMIN_API_KEY is not configured
if not settings.ADMIN_API_KEY:
    logger.warning("ADMIN_API_KEY is not set — admin endpoints are disabled.")


@router.post("/register", response_model=AuthResponse)
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new student account. Returns JWT access_token and refresh_token."""
    try:
        user = register_student(
            db,
            username=request.username,
            email=request.email,
            password=request.password,
            class_num=request.class_num,
        )
        token = create_access_token(user)
        refresh = create_refresh_token(user)
        
        # Store refresh token in db
        expires_at = datetime.now(timezone.utc) + timedelta(days=7) # 7 days refresh TTL
        store_refresh_token(db, str(user.id), refresh, expires_at)
        
        return AuthResponse(
            user_id=str(user.id),
            username=user.username,
            class_num=request.class_num,
            access_token=token,
            refresh_token=refresh,
            message="Registration successful",
            role=user.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/login", response_model=AuthResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate a student. Returns JWT access_token and refresh_token."""
    user = login_student(db, request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    token = create_access_token(user)
    refresh = create_refresh_token(user)
    
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    store_refresh_token(db, str(user.id), refresh, expires_at)
    
    return AuthResponse(
        user_id=str(user.id),
        username=user.username,
        class_num=user.class_num,
        access_token=token,
        refresh_token=refresh,
        message="Login successful",
        role=user.role,
    )


@router.get("/me", response_model=UserSummary)
def get_me(current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    """Returns the currently authenticated user's summary."""
    return UserSummary(
        user_id=str(current_user.id),
        username=current_user.username,
        email=current_user.email,
        class_num=current_user.class_num,
        role=current_user.role,
    )


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh")
def refresh_token(body: RefreshRequest, db: Session = Depends(get_db)):
    """Refresh an access token using a valid refresh token (sent in request body)."""
    import hashlib
    from app.data.models.platform import UserSession
    token_hash = hashlib.sha256(body.refresh_token.encode()).hexdigest()
    session = db.query(UserSession).filter(
        UserSession.refresh_token_hash == token_hash,
        UserSession.revoked_at.is_(None)
    ).first()

    if not session or session.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = session.user
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User inactive")

    new_access_token = create_access_token(user)
    return {"access_token": new_access_token}


@router.post("/logout")
def logout(current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    """Logout by invalidating all active sessions for the user."""
    from app.data.models.platform import UserSession
    db.query(UserSession).filter(UserSession.user_id == current_user.id).update(
        {"revoked_at": datetime.now(timezone.utc)}
    )
    db.commit()
    return {"ok": True}

