"""
008_ingestion_enhancements.py
──────────────────────────────
Migration: Enhance book_ingestion_log and content_blocks for the full
Trust Pipeline (Phase 8+).

book_ingestion_log additions:
  - chapter_number     : which chapter was ingested in this run
  - mime_type          : detected MIME type of the PDF
  - page_count         : total pages in the PDF
  - ingestion_confidence: overall pipeline confidence score 0.0–1.0

content_blocks additions:
  - enriched_prerequisites : LLM-extracted prerequisite topics (JSONB)
  - ocr_confidence         : avg OCR confidence for this block (NULL if digital)
  - content_hash           : MD5 of normalised raw_text for deduplication
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── book_ingestion_log enhancements ───────────────────────────────────────
    op.add_column("book_ingestion_log", sa.Column(
        "chapter_number", sa.Integer, nullable=True,
    ))
    op.add_column("book_ingestion_log", sa.Column(
        "mime_type", sa.String(50), nullable=True,
    ))
    op.add_column("book_ingestion_log", sa.Column(
        "page_count", sa.Integer, nullable=True,
    ))
    op.add_column("book_ingestion_log", sa.Column(
        "ingestion_confidence", sa.Float, nullable=True,
    ))

    # ── content_blocks enhancements ───────────────────────────────────────────
    op.add_column("content_blocks", sa.Column(
        "enriched_prerequisites", JSONB, nullable=True,
    ))
    op.add_column("content_blocks", sa.Column(
        "ocr_confidence", sa.Float, nullable=True,
    ))
    op.add_column("content_blocks", sa.Column(
        "content_hash", sa.String(32), nullable=True,
    ))

    # Index for deduplication lookups
    op.create_index(
        "idx_content_blocks_hash",
        "content_blocks",
        ["content_hash"],
    )


def downgrade() -> None:
    op.drop_index("idx_content_blocks_hash", "content_blocks")
    op.drop_column("content_blocks", "content_hash")
    op.drop_column("content_blocks", "ocr_confidence")
    op.drop_column("content_blocks", "enriched_prerequisites")
    op.drop_column("book_ingestion_log", "ingestion_confidence")
    op.drop_column("book_ingestion_log", "page_count")
    op.drop_column("book_ingestion_log", "mime_type")
    op.drop_column("book_ingestion_log", "chapter_number")
