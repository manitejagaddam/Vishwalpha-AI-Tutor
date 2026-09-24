from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from uuid import UUID
from app.schemas.legacy import SourceInfo, QuizSuggestion, YesterdayContext

class ChatRequest(BaseModel):
    conversation_id: Optional[UUID] = Field(None, alias="session_id")
    parent_message_id: Optional[UUID] = None
    study_space_id: Optional[UUID] = None
    incognito: bool = False
    question: str = Field(..., min_length=1, max_length=4000)
    subject_id: Optional[int] = None
    subject: Optional[str] = None  # Frontend sends string "Science"
    tutor_mode: str = "standard"
    attachments: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    idempotency_key: Optional[str] = None
    
    @field_validator("conversation_id", "parent_message_id", "study_space_id", mode="before")
    def empty_or_invalid_uuid_to_none(cls, v):
        if not v or v in ("", "null", "undefined", "None"):
            return None
        if isinstance(v, str):
            v_clean = v.strip()
            if not v_clean:
                return None
            try:
                return UUID(v_clean)
            except Exception:
                return None
        return v

    @field_validator("subject_id", mode="before")
    def empty_subject_id_to_none(cls, v):
        if not v or v in ("", "null", "undefined", "None"):
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    class Config:
        populate_by_name = True

class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    answer: str
    sources: List[SourceInfo] = []
    attachments: List[Dict[str, Any]] = []
    routed_chapter: str = ""
    routed_topic: str = ""
    question_type: str = "conversational"
    cognitive_skills: Dict[str, Any] = {}
    metrics: Dict[str, float] = {}
    metrics_adjustments: Dict[str, Any] = {}
    conversation_length: int = 0
    pending_tasks: List[str] = []
    quiz_suggestion: Optional[QuizSuggestion] = None
    yesterday_context: Optional[YesterdayContext] = None
    is_new_conversation: bool = False
    context: str = ""
    chunks: List[Dict[str, Any]] = []
    prompt_messages: List[Dict[str, Any]] = []
