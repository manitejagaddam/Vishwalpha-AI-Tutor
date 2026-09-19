"""
app/schemas.py
──────────────
All Pydantic request/response schemas for the API.
"""
from typing import Optional
from pydantic import BaseModel, Field


# ── Auth ──────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username:  str
    email:     str
    password:  str
    class_num: int


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    student_id: str
    username:   str
    class_num:  int
    message:    str = ""


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
    student_id: str    = Field(description="Authenticated student UUID")
    session_id: str    = Field(default="", description="Leave empty to start a new session")
    question:   str
    subject:    str    = Field(default="Science")
    class_num:  Optional[int] = Field(default=None, description="Resolved from DB if absent")
    tutor_mode: str    = Field(
        default="standard",
        description="'standard' = direct answer | 'deep' = Socratic diagnostic"
    )


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
    pdf_path:  str = Field(description="Path to PDF relative to the server's DataSet/ directory")
    class_num: int
    subject:   str
    chapter:   str


class IngestResponse(BaseModel):
    status:            str
    sections_ingested: int
    message:           str = ""


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
    student_id:    str
    subject:       str
    topic:         str
    session_id:    str = ""
    source:        str = Field(
        default="manual",
        description="mid_concept | yesterday | manual"
    )
    num_questions: int = Field(default=7, ge=5, le=10)


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
    student_answer:       str
    student_answer_index: Optional[int] = None


class SubmitAnswerResponse(BaseModel):
    is_correct:     bool
    correct_index:  Optional[int] = None
    correct_answer: Optional[str] = None
    explanation:    str = ""


class FinishQuizRequest(BaseModel):
    attempt_id: str
    session_id: str = ""


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
