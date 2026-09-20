"""
app/data/models/platform.py
────────────────────────────
Platform-level ORM models: users, sessions (refresh tokens), audit log.

Design decisions:
  - UUID PKs for users (not sequential — prevents enumeration attacks on minors' data)
  - password_hash stored with argon2id/bcrypt prefix — the app always checks the prefix
  - role: 'student' | 'admin'  (parent/teacher deferred — see addons.md)
  - UserSession stores hashed refresh tokens, not plaintext
  - AuditLog uses bigint PK for high-volume append-only inserts
"""
import uuid
from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Text, ForeignKey, Index,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.data.models.base import Base, register_updated_at_listener


class User(Base):
    """
    Core identity record. One row per person.

    class_num: 6–12 (NCERT classes). Validated at API layer (ge=6, le=12).
    role: 'student' | 'admin'
    onboarding_complete: False until the student finishes the onboarding flow.
    """
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("class_num BETWEEN 6 AND 12", name="ck_users_class_num"),
        CheckConstraint("role IN ('student', 'admin')", name="ck_users_role"),
        Index("idx_users_email", "email"),
        Index("idx_users_username", "username"),
    )

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username            = Column(String(100), nullable=False, unique=True)
    email               = Column(String(200), nullable=False, unique=True)
    password_hash       = Column(String(500), nullable=False)
    class_num           = Column(Integer, nullable=False)
    role                = Column(String(20), nullable=False, default="student")
    onboarding_complete = Column(Boolean, nullable=False, default=False)
    is_active           = Column(Boolean, nullable=False, default=True)
    created_at          = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())
    last_active_at      = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    sessions            = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    profile             = relationship("StudentProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    conversations       = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    study_spaces        = relationship("StudySpace", back_populates="user", cascade="all, delete-orphan")


register_updated_at_listener(User)


class UserSession(Base):
    """
    Refresh token sessions. One row per active device/login.

    refresh_token_hash: sha256 of the plaintext refresh token. Never store plaintext.
    revoked_at: set on logout or token rotation.
    """
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("idx_user_sessions_user_id", "user_id"),
        Index("idx_user_sessions_token_hash", "refresh_token_hash"),
    )

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id             = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    refresh_token_hash  = Column(String(64), nullable=False, unique=True)  # sha256 hex
    expires_at          = Column(DateTime(timezone=True), nullable=False)
    created_at          = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_at          = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="sessions")


class AuditLog(Base):
    """
    Append-only audit trail for sensitive operations.
    Uses bigint PK for high-volume sequential inserts.

    action: 'login' | 'logout' | 'register' | 'update_profile' | 'delete_account' | etc.
    diff: jsonb storing before/after values for UPDATE events.
    """
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_log_user_id", "user_id"),
        Index("idx_audit_log_created_at", "created_at"),
    )

    id          = Column(Integer, primary_key=True, autoincrement=True)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action      = Column(String(100), nullable=False)
    table_name  = Column(String(100), nullable=True)
    record_id   = Column(String(100), nullable=True)   # stringified PK of affected row
    diff        = Column(JSONB, nullable=True)          # {before: {...}, after: {...}}
    ip_address  = Column(String(45), nullable=True)    # IPv4 or IPv6
    created_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
