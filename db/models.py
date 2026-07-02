"""
db/models.py
────────────
SQLAlchemy ORM models for curriculum, identity, cognitive profiles, and conversation memory.
"""
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Float, Boolean
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

Base = declarative_base()

class Board(Base):
    """Represents an educational board (e.g., NCERT)."""
    __tablename__ = "boards"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    
    classes = relationship("SchoolClass", back_populates="board", cascade="all, delete-orphan")

class SchoolClass(Base):
    """Represents a specific class level (e.g., Class 10)."""
    __tablename__ = "classes"
    id = Column(Integer, primary_key=True, index=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=False)
    name = Column(String(50), nullable=False)
    level = Column(Integer, nullable=False)
    
    board = relationship("Board", back_populates="classes")
    subjects = relationship("Subject", back_populates="school_class", cascade="all, delete-orphan")

class Subject(Base):
    """Represents a subject within a class (e.g., Science)."""
    __tablename__ = "subjects"
    id = Column(Integer, primary_key=True, index=True)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    name = Column(String(100), nullable=False)
    
    school_class = relationship("SchoolClass", back_populates="subjects")
    chapters = relationship("Chapter", back_populates="subject", cascade="all, delete-orphan")

class Chapter(Base):
    """Represents a chapter within a subject."""
    __tablename__ = "chapters"
    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    title = Column(String(200), nullable=False)
    chapter_number = Column(Integer, nullable=False)
    summary = Column(Text, nullable=True)
    learning_objectives = Column(Text, nullable=True)
    key_concepts = Column(Text, nullable=True)
    
    subject = relationship("Subject", back_populates="chapters")
    topics = relationship("Topic", back_populates="chapter", cascade="all, delete-orphan")

class Topic(Base):
    """Represents a topic within a chapter."""
    __tablename__ = "topics"
    id = Column(Integer, primary_key=True, index=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False)
    title = Column(String(200), nullable=False)
    topic_number = Column(String(50), nullable=True)
    chapter_number = Column(Integer, nullable=True)
    summary = Column(Text, nullable=True)
    
    chapter = relationship("Chapter", back_populates="topics")
    chunks = relationship("ContentChunk", back_populates="topic", cascade="all, delete-orphan")

class ContentChunk(Base):
    """Represents a chunk of textbook content associated with a topic."""
    __tablename__ = "content_chunks"
    id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=False)
    content = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    topic = relationship("Topic", back_populates="chunks")

class Student(Base):
    """Represents an authenticated student."""
    __tablename__ = "students"
    id = Column(String(100), primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    class_num = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    subject_profiles = relationship("StudentSubjectProfile", back_populates="student", cascade="all, delete-orphan")
    overall_profile = relationship("OverallCognitiveProfile", back_populates="student", uselist=False, cascade="all, delete-orphan")
    sessions = relationship("ConversationSession", back_populates="student", cascade="all, delete-orphan")

class StudentSubjectProfile(Base):
    """Stores tracking metrics and memory for a student in a specific subject."""
    __tablename__ = "student_subject_profiles"
    id = Column(String(100), primary_key=True)
    student_id = Column(String(100), ForeignKey("students.id"), nullable=False)
    subject = Column(String(100), nullable=False)
    
    concept_master_score = Column(Float, default=50.0, nullable=False)
    error_repetition_rate = Column(Float, default=0.0, nullable=False)
    attempt_persistence = Column(Float, default=50.0, nullable=False)
    struggle_recovery_rate = Column(Float, default=50.0, nullable=False)
    practice_intensity = Column(Float, default=50.0, nullable=False)
    learning_velocity = Column(Float, default=50.0, nullable=False)
    knowledge_retention = Column(Float, default=50.0, nullable=False)
    cognitive_thinking_level = Column(Float, default=50.0, nullable=False)
    engagement_frequency = Column(Float, default=50.0, nullable=False)
    assessment_accuracy = Column(Float, default=50.0, nullable=False)
    
    chat_turns_count = Column(Integer, default=0, nullable=False)
    assignment_count = Column(Integer, default=0, nullable=False)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    student_memory = Column(Text, nullable=True)
    pending_signals = Column(Text, nullable=True)

    student = relationship("Student", back_populates="subject_profiles")

class OverallCognitiveProfile(Base):
    """Stores the aggregated cognitive metrics across all subjects for a student."""
    __tablename__ = "overall_cognitive_profiles"
    id = Column(String(100), primary_key=True)
    student_id = Column(String(100), ForeignKey("students.id"), unique=True, nullable=False)
    
    concept_master_score = Column(Float, default=50.0, nullable=False)
    error_repetition_rate = Column(Float, default=0.0, nullable=False)
    attempt_persistence = Column(Float, default=50.0, nullable=False)
    struggle_recovery_rate = Column(Float, default=50.0, nullable=False)
    practice_intensity = Column(Float, default=50.0, nullable=False)
    learning_velocity = Column(Float, default=50.0, nullable=False)
    knowledge_retention = Column(Float, default=50.0, nullable=False)
    cognitive_thinking_level = Column(Float, default=50.0, nullable=False)
    engagement_frequency = Column(Float, default=50.0, nullable=False)
    assessment_accuracy = Column(Float, default=50.0, nullable=False)
    
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    student = relationship("Student", back_populates="overall_profile")

class ConversationSession(Base):
    """
    Groups a series of student ↔ tutor exchanges into one conversation.
    Linked to a specific student and subject.
    """
    __tablename__ = "conversation_sessions"
    id = Column(String(100), primary_key=True)
    student_id = Column(String(100), ForeignKey("students.id"), nullable=False)
    class_num = Column(Integer, nullable=True)
    subject = Column(String(100), nullable=True)
    summary = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    session_remark = Column(Text, nullable=True)

    student = relationship("Student", back_populates="sessions")
    messages = relationship(
        "ConversationMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.created_at",
    )

class ConversationMessage(Base):
    """
    A single message in a conversation — either from the student or the tutor.
    Stores the context and routing metadata for debugging / audit.
    """
    __tablename__ = "conversation_messages"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), ForeignKey("conversation_sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    context_used = Column(Text, nullable=True)
    routed_topic = Column(String(200), nullable=True)
    is_archived = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("ConversationSession", back_populates="messages")

class CurriculumRouting(Base):
    """
    PostgreSQL-based vector table for semantic routing.
    Equivalent to the Qdrant curriculum_routing collection.
    """
    __tablename__ = "curriculum_routing"
    id = Column(String(100), primary_key=True)
    class_num = Column(Integer, nullable=True)
    subject = Column(String(100), nullable=True)
    chapter = Column(String(200), nullable=True)
    topic = Column(String(200), nullable=True)
    vector = Column(Vector(384), nullable=False)

class CurriculumContent(Base):
    """
    PostgreSQL-based vector table for curriculum RAG retrieval chunks.
    Equivalent to the Qdrant curriculum_content collection.
    """
    __tablename__ = "curriculum_content"
    id = Column(String(100), primary_key=True)
    class_num = Column(Integer, nullable=True)
    subject = Column(String(100), nullable=True)
    chapter = Column(String(200), nullable=True)
    topic = Column(String(200), nullable=True)
    content = Column(Text, nullable=False)
    vector = Column(Vector(384), nullable=False)

class PromptLog(Base):
    """
    Stores raw prompts sent to the LLM for analysis and debugging.
    """
    __tablename__ = "prompt_logs"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), nullable=True)
    student_id = Column(String(100), nullable=True)
    prompt_payload = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

