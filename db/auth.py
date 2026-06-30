import uuid
import hashlib
import os
from sqlalchemy.orm import Session
from db.models import Student, OverallCognitiveProfile
import logging

logger = logging.getLogger(__name__)

def hash_password(password: str, salt: bytes = None) -> str:
    """Hashes a password using PBKDF2 HMAC SHA256."""
    if salt is None:
        salt = os.urandom(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return salt.hex() + ":" + hashed.hex()

def verify_password(password: str, hashed_str: str) -> bool:
    """Verifies a password against its hashed string."""
    try:
        salt_hex, hash_hex = hashed_str.split(':')
        salt = bytes.fromhex(salt_hex)
        hashed = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
        return hashed.hex() == hash_hex
    except Exception:
        return False

def register_student(db: Session, username: str, email: str, password: str, class_num: int) -> Student:
    """Registers a new student and initializes their overall cognitive profile."""
    # Check if username or email already exists
    existing = db.query(Student).filter((Student.username == username) | (Student.email == email)).first()
    if existing:
        raise ValueError("Username or email already exists.")

    student_id = str(uuid.uuid4())
    hashed_password = hash_password(password)

    student = Student(
        id=student_id,
        username=username,
        email=email,
        password_hash=hashed_password,
        class_num=class_num
    )
    db.add(student)

    # Initialize empty overall profile
    overall_profile = OverallCognitiveProfile(
        id=str(uuid.uuid4()),
        student_id=student_id,
        concept_master_score=50.0,
        error_repetition_rate=0.0,
        attempt_persistence=50.0,
        struggle_recovery_rate=50.0,
        practice_intensity=50.0,
        learning_velocity=50.0,
        knowledge_retention=50.0,
        cognitive_thinking_level=50.0,
        engagement_frequency=50.0,
        assessment_accuracy=50.0
    )
    db.add(overall_profile)

    db.commit()
    db.refresh(student)
    logger.info(f"Registered new student: {username} (Class {class_num})")
    return student

def login_student(db: Session, username: str, password: str) -> Student | None:
    """Authenticates a student by username and password."""
    student = db.query(Student).filter(Student.username == username).first()
    if student and verify_password(password, student.password_hash):
        logger.info(f"Student logged in: {username}")
        return student
    return None

def get_student(db: Session, student_id: str) -> Student | None:
    """Fetches a student by ID."""
    return db.query(Student).filter(Student.id == student_id).first()
