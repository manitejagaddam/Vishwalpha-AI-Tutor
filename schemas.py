"""
schemas.py
──────────
Central Pydantic models shared across the ingestion and retrieval pipeline.

These are the canonical data structures that flow between modules:
  - ProcessedSection  : one repaired + LLM-headed section of a chapter
  - CanonicalCurriculum : the full chapter document exported as JSON
"""

from pydantic import BaseModel, Field


class ProcessedSection(BaseModel):
    """
    A fully processed section of a chapter.

    Produced after:
      - TextStructurer detects raw section boundaries (deterministic)
      - LLMStructureRepair repairs the content and generates a proper heading

    Fields:
        heading       : LLM-generated accurate heading (stored as Topic.title in DB)
        section_number: Deterministic section number, e.g. "1.1" (may be empty)
        repaired_text : LLM-repaired clean content (stored as ContentChunk.content in DB)
        summary       : LLM-generated 2-3 sentence summary (stored as Topic.summary + embedded in Qdrant routing)
        keywords      : Key educational terms extracted by the LLM
    """
    heading: str
    section_number: str = ""
    repaired_text: str
    summary: str
    keywords: list[str] = Field(default_factory=list)


class CanonicalCurriculum(BaseModel):
    """
    Top-level canonical document for an entire chapter.
    Exported as JSON after ingestion completes.
    Uses "class" as the serialized key (via alias) for JSON compatibility.
    """
    board: str
    class_num: int = Field(alias="class")
    subject: str
    chapter: str
    section_count: int
    sections: list[ProcessedSection]

    model_config = {"populate_by_name": True}


# ─────────────────────────────────────────────────────────────────────────────
# Chat / Tutor API Models
# ─────────────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    """A single message in a conversation (student or tutor)."""
    role: str          # "student" or "tutor"
    content: str


class ChatRequest(BaseModel):
    """Incoming request from the frontend to the /chat endpoint."""
    session_id: str = Field(
        default="",
        description="Conversation session ID. Leave empty for a new session.",
    )
    question: str
    class_num: int = Field(default=10, description="Student's class level, e.g. 10")
    subject: str = Field(default="Science", description="Subject name")


class SourceInfo(BaseModel):
    """Metadata about a curriculum source used in the answer."""
    chapter: str
    topic: str
    score: float


class ChatResponse(BaseModel):
    """Response returned by the /chat endpoint."""
    session_id: str
    answer: str
    sources: list[SourceInfo] = Field(default_factory=list)
    conversation_length: int = 0
    raw_chunks: list[dict] = Field(default_factory=list, exclude=True)  # not serialised to API
    routed_chapter: str = ""
    routed_topic: str = ""
    question_type: str = "curriculum"   # "curriculum" or "conversational"
    prompt_messages: list[dict] = Field(default_factory=list, exclude=True)  # exact msgs sent to LLM
    metrics: dict = Field(default_factory=dict)
    metrics_adjustments: dict = Field(default_factory=dict)
    cognitive_skills: dict = Field(default_factory=dict)


class UpdateMetricsRequest(BaseModel):
    """Request to manually adjust session metrics or apply a profile preset."""
    metrics: dict | None = None
    profile_name: str | None = None


