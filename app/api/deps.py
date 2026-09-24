"""
app/api/deps.py
────────────────
FastAPI dependency injection utilities.

Provides:
  - get_current_user    : Verifies the JWT Bearer access token and returns the
                          authenticated User record.
  - get_current_student : Alias for get_current_user for backwards compatibility.
  - require_admin       : Verifies the X-Admin-Key header for admin routes.

JWT Strategy
────────────
• Login / Register returns an `access_token` and `refresh_token`.
• All protected endpoints receive the access token via `Authorization: Bearer <token>`.
• The token payload carries `sub` (user UUID), `role`.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, APIKeyHeader
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.data.database import get_db
from app.data.models.platform import User

# ── Constants ──────────────────────────────────────────────────────────────────

_ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


# ── Token creation ─────────────────────────────────────────────────────────────

def create_access_token(user: User) -> str:
    """
    Creates a signed JWT access token.
    Payload: sub (user UUID), role, exp.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=_ALGORITHM)


def create_refresh_token(user: User) -> str:
    """
    Creates a secure refresh token string (opaque token).
    Does NOT store it in the DB; the caller must do that.
    """
    return secrets.token_urlsafe(64)


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


def decode_token_user_id(token: str) -> str | None:
    """Decodes and returns the user ID string from a JWT without raising an exception."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[_ALGORITHM])
        return payload.get("sub")
    except Exception:
        return None


# ── FastAPI dependencies ───────────────────────────────────────────────────────

def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ] = None,
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency — validates the Bearer JWT and returns the User ORM row.
    Raises 401 if the token is missing, invalid, or the user no longer exists.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = _decode_token(credentials.credentials)
    user_id: str = payload["sub"]

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or inactive.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# Alias for compatibility with older routers until updated
get_current_student = get_current_user


def require_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Dependency that ensures the authenticated user has the admin role.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required."
        )
    return current_user


def verify_admin_key(
    api_key: str | None = Security(_api_key_header),
) -> str:
    """
    FastAPI dependency — validates the X-Admin-Key header.
    (Legacy global admin key)
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


def resolve_subject(db: Session, subject_name: str, class_num: int):
    """
    Securely resolves a subject name to the Subject row for the student's class.
    Prevents cross-class collisions (e.g. Class 9 Science vs Class 10 Science)
    which causes queries to fail by picking the wrong subject_id.
    """
    if not subject_name:
        return None
    from sqlalchemy import func as sqlfunc
    from app.data.models.content import Subject, SchoolClass
    s_clean = subject_name.strip()
    
    if s_clean.isdigit():
        return db.query(Subject).filter(Subject.id == int(s_clean)).first()
        
    sub = (
        db.query(Subject)
        .join(SchoolClass, Subject.class_id == SchoolClass.id)
        .filter(
            sqlfunc.lower(Subject.name) == s_clean.lower(),
            SchoolClass.level == class_num
        )
        .first()
    )
    if not sub:
        sub = db.query(Subject).filter(sqlfunc.lower(Subject.name) == s_clean.lower()).first()
    return sub
