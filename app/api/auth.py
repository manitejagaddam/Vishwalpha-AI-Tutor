"""
app/api/auth.py
───────────────
Authentication routes: register and login.

Now returns a JWT access_token alongside the student profile.
All subsequent requests must include:
  Authorization: Bearer <access_token>

The token payload contains: sub (student_id), username, class_num.
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.data.database import get_db
from app.data.auth_repo import register_student, login_student
from app.schemas import RegisterRequest, LoginRequest, AuthResponse
from app.api.deps import create_access_token

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=AuthResponse)
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new student account. Returns JWT access_token."""
    try:
        student = register_student(
            db,
            username=request.username,
            email=request.email,
            password=request.password,
            class_num=request.class_num,
        )
        token = create_access_token(student)
        return AuthResponse(
            student_id=student.id,
            username=student.username,
            class_num=student.class_num,
            access_token=token,
            message="Registration successful",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/login", response_model=AuthResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate a student. Returns JWT access_token."""
    student = login_student(db, request.username, request.password)
    if not student:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token(student)
    return AuthResponse(
        student_id=student.id,
        username=student.username,
        class_num=student.class_num,
        access_token=token,
        message="Login successful",
    )
