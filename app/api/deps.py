"""
app/api/deps.py
────────────────
FastAPI dependency injection utilities.

Provides:
  - get_current_student : Verifies the JWT Bearer token and returns the
                          authenticated Student record.
  - require_admin       : Verifies the X-Admin-Key header for admin routes.

JWT Strategy
────────────
• Login / Register returns an ``access_token`` (HS256 JWT, configurable TTL).
• All protected endpoints receive the token via ``Authorization: Bearer <token>``.
• The token payload carries ``sub`` (student UUID), ``class_num``, ``username``.
• No refresh-token for now — simplest viable auth for a student app.
  Upgrade path: add refresh tokens or switch to Supabase Auth.

Usage
─────
    from app.api.deps import get_current_student

    @router.get("/protected")
    def route(student = Depends(get_current_student)):
        # student.id, student.class_num, student.username available
        ...
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, APIKeyHeader
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.data.database import get_db
from app.data.models import Student

# ── Constants ──────────────────────────────────────────────────────────────────

_ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


# ── Token creation ─────────────────────────────────────────────────────────────

def create_access_token(student: Student) -> str:
    """
    Creates a signed JWT access token for a student.
    Payload: sub (student UUID), username, class_num, exp.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(student.id),
        "username": student.username,
        "class_num": student.class_num,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=_ALGORITHM)


# ── Token verification ─────────────────────────────────────────────────────────

def _decode_token(token: str) -> dict:
    """Decodes and validates a JWT. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[_ALGORITHM])
        if payload.get("sub") is None:
            raise ValueError("Missing sub claim")
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── FastAPI dependencies ───────────────────────────────────────────────────────

def get_current_student(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ] = None,
    db: Session = Depends(get_db),
) -> Student:
    """
    FastAPI dependency — validates the Bearer JWT and returns the Student ORM row.
    Raises 401 if the token is missing, invalid, or the student no longer exists.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = _decode_token(credentials.credentials)
    student_id: str = payload["sub"]

    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Student account not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return student


def verify_admin_key(
    api_key: str | None = Security(_api_key_header),
) -> str:
    """
    FastAPI dependency — validates the X-Admin-Key header.
    Raises 403 if the key is not configured, 401 if it doesn't match.
    """
    if not settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin API key not configured on server.",
        )
    if api_key != settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Admin API Key.",
        )
    return api_key
