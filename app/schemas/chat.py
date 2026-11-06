from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from uuid import UUID
from app.schemas.legacy import SourceInfo, QuizSuggestion, YesterdayContext

class ChatRequest(BaseModel):
    conversation_id: Optional[UUID] = Field(
        None,
        alias="session_id",
        description="Leave null to start a new conversation. Subsequent turns must send the UUID returned in the first response.",
        examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    )
    parent_message_id: Optional[UUID] = Field(None, description="Used for branching/regeneration; omit for normal turns.")
    study_space_id: Optional[UUID] = Field(None, description="Attach this chat to a study space.")
    incognito: bool = Field(default=False, description="If true, this turn is not saved to history.")
    question: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="The student's question in natural language.",
        examples=["Explain Newton's second law of motion with an example."],
    )
    subject_id: Optional[int] = Field(None, description="Numeric subject ID. Preferred over subject string.")
    subject: Optional[str] = Field(None, description="Subject name, e.g. 'Science'. Used if subject_id is not given.", examples=["Science"])
    tutor_mode: str = Field(default="standard", description="'standard' = direct answer | 'deep' = Socratic diagnostic", examples=["standard"])
    attachments: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="List of attachment metadata dicts returned by POST /attachments/upload.")
    idempotency_key: Optional[str] = Field(None, description="Optional client-generated key to prevent duplicate requests.")
    
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
    timings: Dict[str, Any] = {}
