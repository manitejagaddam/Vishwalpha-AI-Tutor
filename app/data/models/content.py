"""
app/data/models/content.py
───────────────────────────
Curriculum content hierarchy ORM models.

Hierarchy: Board → SchoolClass → Subject → Book → Chapter → Topic → Subtopic → ContentBlock
Vectors:   ContentBlock → BlockEmbedding (separate table records embedding_model)

Design decisions:
  - `natural_key` UNIQUE on Book, Chapter, Topic: stable cross-ingestion identifier
    so re-ingestion (with new PDF edition) never orphans student mastery data.
    Format: "NCERT_10_Science_en_C03" (board_chapter_subject_lang_num).
  - `subject_id` FK everywhere (never free-text subject name).
  - `lang_code` stub column present but unused in Phase 1 (English only).
  - BlockEmbedding is a separate table to support multiple embedding models
    and to allow re-embedding without touching content.
  - `raw_text` = verbatim textbook text (never paraphrased).
  - `enriched_*` columns = LLM-generated, labelled with `prompt_version`.
  - StudySpace lives here as it references Subject (content domain).
"""
import uuid
from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Text, Float,
    ForeignKey, UniqueConstraint, Index, CheckConstraint, SmallInteger,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from app.data.models.base import Base, register_updated_at_listener


# ── Curriculum Hierarchy ──────────────────────────────────────────────────────

class Board(Base):
    """Educational board (e.g. NCERT, CBSE, ICSE, IGCSE)."""
    __tablename__ = "boards"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)

    classes = relationship("SchoolClass", back_populates="board", cascade="all, delete-orphan")


class SchoolClass(Base):
    """A class level within a board (Class 6 – 12)."""
    __tablename__ = "classes"
    __table_args__ = (
        UniqueConstraint("board_id", "level", name="uq_classes_board_level"),
        CheckConstraint("level BETWEEN 1 AND 12", name="ck_classes_level"),
    )

    id           = Column(Integer, primary_key=True, autoincrement=True)
    board_id     = Column(Integer, ForeignKey("boards.id", ondelete="CASCADE"), nullable=False)
    level        = Column(Integer, nullable=False)          # 6, 7, … 12
    display_name = Column(String(50), nullable=False)       # "Class 10"

    board    = relationship("Board", back_populates="classes")
    subjects = relationship("Subject", back_populates="school_class", cascade="all, delete-orphan")


class Subject(Base):
    """A subject within a class (e.g. Science, Mathematics, History)."""
    __tablename__ = "subjects"
    __table_args__ = (
        UniqueConstraint("class_id", "name", name="uq_subjects_class_name"),
    )

    id           = Column(Integer, primary_key=True, autoincrement=True)
    class_id     = Column(Integer, ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    name         = Column(String(100), nullable=False)       # "Science"
    display_name = Column(String(150), nullable=True)        # "Science (Physics + Chemistry + Biology)"
    lang_code    = Column(String(10), nullable=False, default="en")

    school_class = relationship("SchoolClass", back_populates="subjects")
    books        = relationship("Book", back_populates="subject", cascade="all, delete-orphan")
    study_spaces = relationship("StudySpace", back_populates="subject")


class Book(Base):
    """
    A textbook within a subject.
    One subject can have multiple books (e.g. Science Part I and Part II).

    natural_key: stable identifier across re-ingestions.
    Format: "{board}_{class}_{subject}_{lang}_{edition}"
    Example: "NCERT_10_Science_en_2023"
    """
    __tablename__ = "books"
    __table_args__ = (
        UniqueConstraint("natural_key", name="uq_books_natural_key"),
        Index("idx_books_subject_id", "subject_id"),
    )

    id          = Column(Integer, primary_key=True, autoincrement=True)
    subject_id  = Column(Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    title       = Column(String(300), nullable=False)
    edition     = Column(String(50), nullable=True)          # "2023", "NCERT Standard"
    lang_code   = Column(String(10), nullable=False, default="en")
    natural_key = Column(String(200), nullable=False, unique=True)
    created_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    subject  = relationship("Subject", back_populates="books")
    chapters = relationship("Chapter", back_populates="book", cascade="all, delete-orphan")


class Chapter(Base):
    """
    A chapter within a book.
    natural_key: stable identifier. Format: "{book_natural_key}_C{chapter_number:02d}"
    """
    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("book_id", "chapter_number", name="uq_chapters_book_num"),
        UniqueConstraint("natural_key", name="uq_chapters_natural_key"),
        Index("idx_chapters_book_id", "book_id"),
    )

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    book_id             = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    title               = Column(String(300), nullable=False)
    chapter_number      = Column(Integer, nullable=False)
    natural_key         = Column(String(250), nullable=False, unique=True)
    summary             = Column(Text, nullable=True)        # LLM-generated
    learning_objectives = Column(Text, nullable=True)        # LLM-generated (JSON list)
    key_concepts        = Column(Text, nullable=True)        # LLM-generated (JSON list)
    display_order       = Column(Integer, nullable=False, default=0)
    prompt_version      = Column(String(20), nullable=True)  # prompt template version used

    book   = relationship("Book", back_populates="chapters")
    topics = relationship("Topic", back_populates="chapter", cascade="all, delete-orphan")


class Topic(Base):
    """
    A topic within a chapter.
    natural_key: "{chapter_natural_key}_T{topic_number}"
    """
    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint("chapter_id", "topic_number", name="uq_topics_chapter_num"),
        UniqueConstraint("natural_key", name="uq_topics_natural_key"),
        Index("idx_topics_chapter_id", "chapter_id"),
    )

    id             = Column(Integer, primary_key=True, autoincrement=True)
    chapter_id     = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    title          = Column(String(300), nullable=False)
    topic_number   = Column(String(50), nullable=True)       # "3.2", "Ex 3.2" etc.
    natural_key    = Column(String(300), nullable=False, unique=True)
    summary        = Column(Text, nullable=True)
    display_order  = Column(Integer, nullable=False, default=0)
    prompt_version = Column(String(20), nullable=True)

    chapter      = relationship("Chapter", back_populates="topics")
    subtopics    = relationship("Subtopic", back_populates="topic", cascade="all, delete-orphan")
    blocks       = relationship("ContentBlock", back_populates="topic", cascade="all, delete-orphan")
    prerequisites_from = relationship(
        "TopicPrerequisite",
        foreign_keys="TopicPrerequisite.topic_id",
        back_populates="topic",
        cascade="all, delete-orphan",
    )


class Subtopic(Base):
    """
    Optional sub-section within a topic (e.g. "3.2.1 Laws of Motion").
    Not all topics have subtopics.
    """
    __tablename__ = "subtopics"
    __table_args__ = (
        UniqueConstraint("topic_id", "display_order", name="uq_subtopics_topic_order"),
        Index("idx_subtopics_topic_id", "topic_id"),
    )

    id            = Column(Integer, primary_key=True, autoincrement=True)
    topic_id      = Column(Integer, ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    title         = Column(String(300), nullable=False)
    display_order = Column(Integer, nullable=False, default=0)

    topic  = relationship("Topic", back_populates="subtopics")
    blocks = relationship("ContentBlock", back_populates="subtopic")


class ContentBlock(Base):
    """
    The atomic unit of curriculum content.
    One block = one paragraph / activity / figure / equation / table.

    block_type: text | heading | activity | example | exercise | figure | equation | table | box | summary
    raw_text: verbatim extracted text from the PDF. NEVER paraphrased.
    enriched_*: LLM-generated fields, always labelled with prompt_version.
    page_num: page number in the original PDF.
    block_index: reading-order position within its parent topic.
    """
    __tablename__ = "content_blocks"
    __table_args__ = (
        UniqueConstraint("topic_id", "block_index", name="uq_blocks_topic_index"),
        Index("idx_blocks_topic_id", "topic_id"),
        Index("idx_blocks_subtopic_id", "subtopic_id"),
    )

    id               = Column(Integer, primary_key=True, autoincrement=True)
    topic_id         = Column(Integer, ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    subtopic_id      = Column(Integer, ForeignKey("subtopics.id", ondelete="SET NULL"), nullable=True)
    block_type              = Column(String(30), nullable=False, default="text")
    raw_text                = Column(Text, nullable=False)          # verbatim — NEVER LLM paraphrase
    enriched_summary        = Column(Text, nullable=True)           # LLM-generated summary
    enriched_keywords       = Column(JSONB, nullable=True)          # LLM-generated keyword list
    enriched_prerequisites  = Column(JSONB, nullable=True)          # LLM-extracted prerequisite topics
    page_num                = Column(Integer, nullable=True)
    block_index             = Column(Integer, nullable=False, default=0)
    ocr_confidence          = Column(Float, nullable=True)          # avg OCR confidence (NULL if digital)
    content_hash            = Column(String(32), nullable=True)     # MD5 of raw_text for dedup
    prompt_version          = Column(String(20), nullable=True)     # which prompt built enriched_*
    created_at              = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    topic    = relationship("Topic", back_populates="blocks")
    subtopic = relationship("Subtopic", back_populates="blocks")
    embeddings = relationship("BlockEmbedding", back_populates="block", cascade="all, delete-orphan")
    sources    = relationship("MessageSource", back_populates="block")


class BlockEmbedding(Base):
    """
    Embedding vector for a content block.
    Separate table so we can re-embed with a new model without touching content.

    UNIQUE(block_id, embedding_model): one vector per block per model.
    embedding_model: "text-embedding-3-small-1536" — includes dimension to prevent mix-ups.
    """
    __tablename__ = "block_embeddings"
    __table_args__ = (
        UniqueConstraint("block_id", "embedding_model", name="uq_block_embeddings_block_model"),
        Index("idx_block_embeddings_block_id", "block_id"),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    block_id        = Column(Integer, ForeignKey("content_blocks.id", ondelete="CASCADE"), nullable=False)
    embedding       = Column(Vector(1536), nullable=False)
    embedding_model = Column(String(100), nullable=False, default="text-embedding-3-small-1536")
    created_at      = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    block = relationship("ContentBlock", back_populates="embeddings")


class BookIngestionLog(Base):
    """
    Tracks each PDF ingestion run for a book.
    pdf_hash: SHA256 of the PDF file — skip re-ingestion if unchanged.
    coverage: JSONB coverage report per chapter.
    status: pending | in_progress | complete | failed
    """
    __tablename__ = "book_ingestion_log"
    __table_args__ = (
        Index("idx_ingestion_log_book_id", "book_id"),
        Index("idx_ingestion_log_pdf_hash", "pdf_hash"),
    )

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    book_id              = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    pdf_hash             = Column(String(64), nullable=False)    # SHA256 hex
    chapter_number       = Column(Integer, nullable=True)        # which chapter this run covers
    mime_type            = Column(String(50), nullable=True)     # detected MIME type
    page_count           = Column(Integer, nullable=True)        # total pages in PDF
    status               = Column(String(20), nullable=False, default="pending")
    # valid statuses: pending | in_progress | complete | partial | needs_review | failed
    coverage             = Column(JSONB, nullable=True)          # full coverage report JSON
    ingestion_confidence = Column(Float, nullable=True)          # overall pipeline confidence 0-1
    error                = Column(Text, nullable=True)
    ingested_at          = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at          = Column(DateTime(timezone=True), nullable=True)

    book = relationship("Book")


class StudySpace(Base):
    """
    Per-subject workspace that groups related conversations.
    (Deferred from frontend — see addons.md — but schema is included now.)

    custom_instructions: injected into the system prompt when a conversation
    belongs to this space, overriding global student preferences.
    """
    __tablename__ = "study_spaces"
    __table_args__ = (
        Index("idx_study_spaces_user_id", "user_id"),
    )

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id             = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subject_id          = Column(Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    title               = Column(String(150), nullable=False)
    custom_instructions = Column(Text, nullable=True)
    pinned_context      = Column(JSONB, nullable=False, default=list)   # list of block_ids
    is_archived         = Column(Boolean, nullable=False, default=False)
    created_at          = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    user    = relationship("User", back_populates="study_spaces")
    subject = relationship("Subject", back_populates="study_spaces")
    conversations = relationship("Conversation", back_populates="study_space")


register_updated_at_listener(StudySpace)
