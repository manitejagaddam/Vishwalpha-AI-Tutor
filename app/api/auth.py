"""
app/api/auth.py
───────────────
Authentication routes: register and login.
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.data.database import get_db
from app.data.auth_repo import register_student, login_student
from app.schemas import RegisterRequest, LoginRequest, AuthResponse

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=AuthResponse)
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new student account."""
    try:
        student = register_student(
            db,
            username=request.username,
            email=request.email,
            password=request.password,
            class_num=request.class_num,
        )
        return AuthResponse(
            student_id=student.id,
            username=student.username,
            class_num=student.class_num,
            message="Registration successful",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/login", response_model=AuthResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate a student."""
    student = login_student(db, request.username, request.password)
    if not student:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return AuthResponse(
        student_id=student.id,
        username=student.username,
        class_num=student.class_num,
        message="Login successful",
    )
