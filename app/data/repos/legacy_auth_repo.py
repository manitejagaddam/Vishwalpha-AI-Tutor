"""
app/data/auth_repo.py
──────────────────────
Authentication repository: register, login, fetch students.
Passwords hashed with PBKDF2-HMAC-SHA256 (salted, 100k iterations).

On registration, initialises:
  - OverallCognitiveProfile (default metrics)
  - StudentLearningPreference (default preferences)
  - StudentStreak (zeroed counters)
"""
import os
import uuid
import hashlib
import logging

from sqlalchemy.orm import Session

from app.data.models import (
    Student,
    OverallCognitiveProfile,
    StudentLearningPreference,
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
) -> Student:
    """
    Creates a new student and their default cognitive profile,
    learning preferences, and streak record.
    Raises ValueError if username or email already exists.
    """
    existing = db.query(Student).filter(
        (Student.username == username) | (Student.email == email)
    ).first()
    if existing:
        raise ValueError("Username or email already exists.")

    student_id = str(uuid.uuid4())
    student = Student(
        id=student_id,
        username=username,
        email=email,
        password_hash=_hash_password(password),
        class_num=class_num,
    )
    db.add(student)

    # Initialise default cognitive profile
    db.add(OverallCognitiveProfile(
        id=str(uuid.uuid4()),
        student_id=student_id,
    ))

    # Initialise default learning preferences
    db.add(StudentLearningPreference(
        id=str(uuid.uuid4()),
        student_id=student_id,
    ))

    # Initialise streak record
    db.add(StudentStreak(
        id=str(uuid.uuid4()),
        student_id=student_id,
    ))

    db.commit()
    db.refresh(student)
    logger.info(f"Registered student: {username} (Class {class_num})")
    return student


def login_student(db: Session, username: str, password: str) -> Student | None:
    """Returns the Student if credentials are valid, else None."""
    student = db.query(Student).filter(Student.username == username).first()
    if student and _verify_password(password, student.password_hash):
        logger.info(f"Student login: {username}")
        return student
    return None


def get_student(db: Session, student_id: str) -> Student | None:
    return db.query(Student).filter(Student.id == student_id).first()
