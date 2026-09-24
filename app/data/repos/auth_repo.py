import os
import uuid
import hashlib
import logging

from sqlalchemy.orm import Session

from app.data.models.platform import User, UserSession
from app.data.models.learning import (
    StudentProfile,
    OverallCognitiveProfile,
    LearningPreference,
    StudentStreak,
)

logger = logging.getLogger(__name__)


def _hash_password(password: str, salt: bytes | None = None) -> str:
    if salt is None:
        salt = os.urandom(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return salt.hex() + ":" + hashed.hex()


def _verify_password(password: str, hashed_str: str) -> bool:
    try:
        salt_hex, hash_hex = hashed_str.split(":")
        salt = bytes.fromhex(salt_hex)
        hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        return hashed.hex() == hash_hex
    except Exception:
        return False


def register_student(
    db: Session, username: str, email: str, password: str, class_num: int
) -> User:
    """
    Creates a new user (student role) and their default student profiles.
    Raises ValueError if username or email already exists.
    """
    existing = db.query(User).filter(
        (User.username == username) | (User.email == email)
    ).first()
    if existing:
        raise ValueError("Username or email already exists.")

    user_id = str(uuid.uuid4())
    user = User(
        id=user_id,
        username=username,
        email=email,
        password_hash=_hash_password(password),
        class_num=class_num,
        role="student",
    )
    db.add(user)

    # Core student profile
    student_profile = StudentProfile(
        user_id=user_id,
    )
    db.add(student_profile)

    # Initialise default cognitive profile
    db.add(OverallCognitiveProfile(
        user_id=user_id,
    ))

    # Initialise default learning preferences
    db.add(LearningPreference(
        user_id=user_id,
    ))

    # Initialise student streak tracking
    db.add(StudentStreak(
        user_id=user_id,
    ))

    db.commit()
    db.refresh(user)
    logger.info(f"Registered student: {username} (Class {class_num})")
    return user


def login_student(db: Session, username: str, password: str) -> User | None:
    """Returns the User if credentials are valid and user is active, else None."""
    cleaned = (username or "").strip()
    user = db.query(User).filter(
        (User.username == cleaned) | (User.email == cleaned)
    ).first()
    if user and user.is_active and _verify_password(password, user.password_hash):
        logger.info(f"User login: {user.username}")
        return user
    return None


def get_user(db: Session, user_id: str) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def store_refresh_token(db: Session, user_id: str, token: str, expires_at) -> UserSession:
    session_id = str(uuid.uuid4())
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    user_session = UserSession(
        id=session_id,
        user_id=user_id,
        refresh_token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(user_session)
    db.commit()
    return user_session
