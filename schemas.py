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
