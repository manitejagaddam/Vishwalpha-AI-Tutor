"""
app/schemas.py
──────────────
All Pydantic request/response schemas for the API.
"""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


# ── Auth ──────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username:  str = Field(min_length=3, max_length=50)
    email:     str = Field(max_length=200)
    password:  str = Field(min_length=6, max_length=128)
    class_num: int = Field(ge=6, le=12)


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    student_id:   str
    username:     str
    class_num:    int
    access_token: str = ""          # JWT bearer token
    token_type:   str = "bearer"
    message:      str = ""


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role:    str
    content: str


class SourceInfo(BaseModel):
    chapter: str
    topic:   str
    score:   float


class QuizSuggestion(BaseModel):
    """Injected into ChatResponse when AI detects a concept is fully explained."""
    topic:         str
    subject:       str
    num_questions: int = 7


class YesterdayContext(BaseModel):
    """Injected into ChatResponse on session start when yesterday's session exists."""
    subject:      str
    topic:        str
    session_date: str


class ChatRequest(BaseModel):
    session_id: str    = Field(default="", description="Leave empty to start a new session")
    question:   str    = Field(min_length=1, max_length=4000, description="The student's question")
    subject:    str    = Field(default="Science")
    class_num:  Optional[int] = Field(default=None, description="Resolved from JWT if absent")
    tutor_mode: str    = Field(
        default="standard",
        description="'standard' = direct answer | 'deep' = Socratic diagnostic"
    )

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Question cannot be blank.")
        return v.strip()

    @field_validator("tutor_mode")
    @classmethod
    def valid_tutor_mode(cls, v: str) -> str:
        if v not in ("standard", "deep"):
            raise ValueError("tutor_mode must be 'standard' or 'deep'.")
        return v


class ChatResponse(BaseModel):
    session_id:          str
    answer:              str
    sources:             list[SourceInfo] = Field(default_factory=list)
    conversation_length: int = 0
    routed_chapter:      str = ""
    routed_topic:        str = ""
    question_type:       str = "curriculum"
    metrics:             dict = Field(default_factory=dict)
    metrics_adjustments: dict = Field(default_factory=dict)
    cognitive_skills:    dict = Field(default_factory=dict)
    diagnostic_question: str = ""
    is_session_start:    bool = False
    pending_tasks:       list[str] = Field(default_factory=list)
    # Quiz / assignment
    quiz_suggestion:     Optional[QuizSuggestion] = None
    yesterday_context:   Optional[YesterdayContext] = None


# ── Student profile ───────────────────────────────────────────────────────────

class UpdateMetricsRequest(BaseModel):
    metrics:      Optional[dict] = None
    profile_name: Optional[str] = None


# ── Ingestion (admin) ─────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    pdf_path:         str = Field(description="Path to PDF file (absolute or relative to project root)")
    board_name:       str = Field(default="NCERT", description="Board name, e.g. NCERT")
    class_num:        int = Field(ge=6, le=12)
    subject_name:     str = Field(description="Subject name, e.g. Science")
    book_title:       str = Field(description="Full book title")
    book_natural_key: str = Field(description="Unique book key, e.g. NCERT_10_Science_en_2023")
    chapter_title:    str = Field(description="Chapter title")
    chapter_number:   int = Field(ge=1, description="Chapter number")


class IngestResponse(BaseModel):
    status:               str
    sections_ingested:    int = 0
    blocks_stored:        int = 0
    chapter_id:           Optional[int] = None
    message:              str = ""
    warnings:             list[str] = []
    ingestion_confidence: Optional[float] = None
    coverage:             dict = {}


class IngestLogResponse(BaseModel):
    id:                   int
    book_id:              int
    book_natural_key:     str | None = None
    chapter_number:       int | None = None
    pdf_hash:             str
    status:               str
    ingestion_confidence: float | None = None
    coverage:             dict | None = None
    error:                str | None = None
    ingested_at:          datetime
    finished_at:          datetime | None = None


# ── Curriculum schemas (internal) ─────────────────────────────────────────────

class ProcessedSection(BaseModel):
    heading:            str
    section_number:     str = ""
    repaired_text:      str
    raw_extracted_text: str = ""
    summary:            str
    keywords:           list[str] = Field(default_factory=list)
    prerequisites:      list[str] = Field(default_factory=list)


class CanonicalCurriculum(BaseModel):
    board:         str
    class_num:     int = Field(alias="class")
    subject:       str
    chapter:       str
    section_count: int
    sections:      list[ProcessedSection]

    model_config = {"populate_by_name": True}


# ── Quiz / Assignment Schemas ─────────────────────────────────────────────────

class GenerateQuizRequest(BaseModel):
    subject:       str = "Science"
    topic:         Optional[str] = ""
    session_id:    Optional[str] = ""
    source:        str = Field(
        default="manual",
        description="mid_concept | yesterday | manual"
    )
    num_questions: int = Field(default=7, ge=3, le=15)

    @field_validator("session_id", "topic", mode="before")
    def none_to_empty(cls, v):
        return "" if v is None else str(v)


class QuizQuestionOut(BaseModel):
    """A single question sent to the frontend — correct answer hidden."""
    id:       int
    q_index:  int
    q_type:   str
    question: str
    options:  list[str] = Field(default_factory=list)


class GenerateQuizResponse(BaseModel):
    attempt_id: str
    subject:    str
    topic:      str
    source:     str
    questions:  list[QuizQuestionOut]


class SubmitAnswerRequest(BaseModel):
    question_id:          int
    student_answer:       str = ""
    student_answer_index: Optional[int] = None


class SubmitAnswerResponse(BaseModel):
    is_correct:     bool
    correct_index:  Optional[int] = None
    correct_answer: Optional[str] = None
    explanation:    str = ""


class FinishQuizRequest(BaseModel):
    attempt_id: str
    session_id: Optional[str] = ""

    @field_validator("session_id", mode="before")
    def null_to_empty(cls, v):
        return "" if v is None else str(v)


class FinishQuizResponse(BaseModel):
    attempt_id:     str
    score:          float
    total:          int
    correct:        int
    passed:         bool
    topic:          str
    subject:        str
    ai_feedback:    str = ""
    metrics_impact: dict = Field(default_factory=dict)


class QuizHistoryItem(BaseModel):
    id:            str
    subject:       str
    topic:         Optional[str] = None
    source:        str
    score:         Optional[float] = None
    passed:        Optional[bool] = None
    num_questions: int
    finished_at:   Optional[str] = None
    created_at:    Optional[str] = None


class SubjectQuizFeedbackOut(BaseModel):
    total_attempts:  int = 0
    total_questions: int = 0
    total_correct:   int = 0
    avg_score:       float = 0.0
    mcq_accuracy:    float = 0.0
    theory_accuracy: float = 0.0
    weak_topics:     list[str] = Field(default_factory=list)
    strong_topics:   list[str] = Field(default_factory=list)
    ai_feedback:     str = ""
