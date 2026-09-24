"""
010_raw_archive.py
───────────────────
Migration: Add content_raw_archive table.

PURPOSE:
  Separates verbatim audit text from the live retrieval system.
  - raw_text      = verbatim OCR extraction (never paraphrased)
  - repaired_text = LLM-repaired full text from STRUCTURE_PROMPT
  Both are stored here for auditing and re-migration only.
  The live retrieval pipeline exclusively uses content_blocks.enriched_summary.
"""
from alembic import op
import sqlalchemy as sa


revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_raw_archive",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "block_id",
            sa.Integer,
            sa.ForeignKey("content_blocks.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("repaired_text", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_raw_archive_block_id",
        "content_raw_archive",
        ["block_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_raw_archive_block_id", table_name="content_raw_archive")
    op.drop_table("content_raw_archive")
