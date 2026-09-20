"""
app/data/models/__init__.py
────────────────────────────
Re-exports all ORM models and the shared Base.
Import from here: `from app.data.models import Base, User, Conversation, ...`
"""
from app.data.models.base import Base  # noqa: F401
from app.data.models.platform import (  # noqa: F401
    User, UserSession, AuditLog,
)
from app.data.models.content import (  # noqa: F401
    Board, SchoolClass, Subject, Book, Chapter, Topic, Subtopic,
    ContentBlock, BlockEmbedding, BookIngestionLog, StudySpace,
)
from app.data.models.chat import (  # noqa: F401
    Conversation, Message, MessageContentBlock, MessageSource,
    Artifact, ArtifactVersion, ShareLink, MessageFeedback, ToolCallLog,
)
from app.data.models.learning import (  # noqa: F401
    StudentProfile, StudentSubjectProfile, OverallCognitiveProfile,
    CognitiveMetricHistory, LearningPreference, StudentMemoryItem,
    TopicMastery, MasteryEvent, TopicPrerequisite,
    QuizAttempt, QuizQuestion, QuizQuestionSource, SubjectQuizFeedback,
    SessionInsight, DiagnosticState, StudentGoal, StudentStreak,
    StudentTask, PendingMetricSignal,
)
from app.data.models.platform_ops import (  # noqa: F401
    LLMCallLog, UsageLedger, JobQueue, PromptTemplate,
)

__all__ = [
    "Base",
    # Platform
    "User", "UserSession", "AuditLog",
    # Content
    "Board", "SchoolClass", "Subject", "Book", "Chapter", "Topic", "Subtopic",
    "ContentBlock", "BlockEmbedding", "BookIngestionLog", "StudySpace",
    # Chat
    "Conversation", "Message", "MessageContentBlock", "MessageSource",
    "Artifact", "ArtifactVersion", "ShareLink", "MessageFeedback", "ToolCallLog",
    # Learning
    "StudentProfile", "StudentSubjectProfile", "OverallCognitiveProfile",
    "CognitiveMetricHistory", "LearningPreference", "StudentMemoryItem",
    "TopicMastery", "MasteryEvent", "TopicPrerequisite",
    "QuizAttempt", "QuizQuestion", "QuizQuestionSource", "SubjectQuizFeedback",
    "SessionInsight", "DiagnosticState", "StudentGoal", "StudentStreak",
    "StudentTask", "PendingMetricSignal",
    # Platform Ops
    "LLMCallLog", "UsageLedger", "JobQueue", "PromptTemplate",
]
