"""
002_content.py
───────────────
Migration: Curriculum content hierarchy.
boards → classes → subjects → books → chapters → topics → subtopics
→ content_blocks → block_embeddings → book_ingestion_log → study_spaces
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── boards ────────────────────────────────────────────────────────────────
    op.create_table(
        "boards",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
    )

    # ── classes ───────────────────────────────────────────────────────────────
    op.create_table(
        "classes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("board_id", sa.Integer, sa.ForeignKey("boards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level", sa.Integer, nullable=False),
        sa.Column("display_name", sa.String(50), nullable=False),
        sa.UniqueConstraint("board_id", "level", name="uq_classes_board_level"),
        sa.CheckConstraint("level BETWEEN 1 AND 12", name="ck_classes_level"),
    )

    # ── subjects ──────────────────────────────────────────────────────────────
    op.create_table(
        "subjects",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("class_id", sa.Integer, sa.ForeignKey("classes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(150), nullable=True),
        sa.Column("lang_code", sa.String(10), nullable=False, server_default="en"),
        sa.UniqueConstraint("class_id", "name", name="uq_subjects_class_name"),
    )

    # ── books ─────────────────────────────────────────────────────────────────
    op.create_table(
        "books",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("edition", sa.String(50), nullable=True),
        sa.Column("lang_code", sa.String(10), nullable=False, server_default="en"),
        sa.Column("natural_key", sa.String(200), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_books_subject_id", "books", ["subject_id"])

    # ── chapters ──────────────────────────────────────────────────────────────
    op.create_table(
        "chapters",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("book_id", sa.Integer, sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("chapter_number", sa.Integer, nullable=False),
        sa.Column("natural_key", sa.String(250), nullable=False, unique=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("learning_objectives", sa.Text, nullable=True),
        sa.Column("key_concepts", sa.Text, nullable=True),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("prompt_version", sa.String(20), nullable=True),
        sa.UniqueConstraint("book_id", "chapter_number", name="uq_chapters_book_num"),
    )
    op.create_index("idx_chapters_book_id", "chapters", ["book_id"])

    # ── topics ────────────────────────────────────────────────────────────────
    op.create_table(
        "topics",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("chapter_id", sa.Integer, sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("topic_number", sa.String(50), nullable=True),
        sa.Column("natural_key", sa.String(300), nullable=False, unique=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("prompt_version", sa.String(20), nullable=True),
        sa.UniqueConstraint("chapter_id", "topic_number", name="uq_topics_chapter_num"),
    )
    op.create_index("idx_topics_chapter_id", "topics", ["chapter_id"])

    # ── subtopics ─────────────────────────────────────────────────────────────
    op.create_table(
        "subtopics",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("topic_id", sa.Integer, sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("topic_id", "display_order", name="uq_subtopics_topic_order"),
    )
    op.create_index("idx_subtopics_topic_id", "subtopics", ["topic_id"])

    # ── content_blocks ────────────────────────────────────────────────────────
    op.create_table(
        "content_blocks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("topic_id", sa.Integer, sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subtopic_id", sa.Integer, sa.ForeignKey("subtopics.id", ondelete="SET NULL"), nullable=True),
        sa.Column("block_type", sa.String(30), nullable=False, server_default="text"),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("enriched_summary", sa.Text, nullable=True),
        sa.Column("enriched_keywords", JSONB, nullable=True),
        sa.Column("page_num", sa.Integer, nullable=True),
        sa.Column("block_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("prompt_version", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("topic_id", "block_index", name="uq_blocks_topic_index"),
    )
    op.create_index("idx_blocks_topic_id", "content_blocks", ["topic_id"])
    op.create_index("idx_blocks_subtopic_id", "content_blocks", ["subtopic_id"])

    # ── block_embeddings ──────────────────────────────────────────────────────
    op.create_table(
        "block_embeddings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("block_id", sa.Integer, sa.ForeignKey("content_blocks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("embedding_model", sa.String(100), nullable=False, server_default="text-embedding-3-small-1536"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("block_id", "embedding_model", name="uq_block_embeddings_block_model"),
    )
    # Create the embedding column as vector(1536) — pgvector type
    op.execute("ALTER TABLE block_embeddings ADD COLUMN embedding vector(1536) NOT NULL")
    op.create_index("idx_block_embeddings_block_id", "block_embeddings", ["block_id"])

    # ── book_ingestion_log ────────────────────────────────────────────────────
    op.create_table(
        "book_ingestion_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("book_id", sa.Integer, sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pdf_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("coverage", JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_ingestion_log_book_id", "book_ingestion_log", ["book_id"])
    op.create_index("idx_ingestion_log_pdf_hash", "book_ingestion_log", ["pdf_hash"])

    # ── study_spaces ─────────────────────────────────────────────────────────
    op.create_table(
        "study_spaces",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_id", sa.Integer, sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("custom_instructions", sa.Text, nullable=True),
        sa.Column("pinned_context", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_archived", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_study_spaces_user_id", "study_spaces", ["user_id"])

    # ── Seed: NCERT board, classes 6–12 ────────────────────────────────────────
    op.execute("""
        INSERT INTO boards (name, description) VALUES
        ('NCERT', 'National Council of Educational Research and Training');
    """)
    op.execute("""
        INSERT INTO classes (board_id, level, display_name)
        SELECT id, lvl, 'Class ' || lvl::text
        FROM boards, unnest(ARRAY[6,7,8,9,10,11,12]) AS lvl
        WHERE boards.name = 'NCERT';
    """)


def downgrade() -> None:
    op.drop_table("study_spaces")
    op.drop_table("book_ingestion_log")
    op.drop_table("block_embeddings")
    op.drop_table("content_blocks")
    op.drop_table("subtopics")
    op.drop_table("topics")
    op.drop_table("chapters")
    op.drop_table("books")
    op.drop_table("subjects")
    op.drop_table("classes")
    op.drop_table("boards")
