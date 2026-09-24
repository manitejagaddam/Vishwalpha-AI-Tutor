"""
007_indexes.py
───────────────
Migration: Performance indexes — HNSW (pgvector), GIN (full-text + JSONB), trigram, composite.

Index strategy:
  - HNSW on block_embeddings.embedding (cosine, m=16, ef_construction=64)
    These parameters work for our expected scale (<100K blocks).
    Tune ef_search at query time (SET hnsw.ef_search = 100).
  - GIN tsvector on message_content_blocks.content for full-text chat search.
  - GIN tsvector on content_blocks.raw_text for retrieval debug search.
  - GIN on JSONB columns queried by containment (@>) or key checks.
  - btree composite indexes for common multi-column filters.

NOTE: HNSW indexes are created to avoid locking production tables.
      In a fresh migration (empty DB), is not needed but is harmless.
"""
from alembic import op


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── HNSW vector index (pgvector) ─────────────────────────────────────────
    # Used for: semantic retrieval of content blocks; topic routing
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_block_embeddings_hnsw
        ON block_embeddings
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # ── GIN full-text index on content blocks (raw_text) ─────────────────────
    # Used for: hybrid BM25+vector search in retrieval pipeline
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_content_blocks_fts
        ON content_blocks
        USING gin(to_tsvector('english', raw_text))
    """)

    # ── GIN full-text index on message content ────────────────────────────────
    # Used for: conversation search (GET /conversations/search?q=...)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_msg_content_blocks_fts
        ON message_content_blocks
        USING gin(to_tsvector('english', coalesce(content, '')))
    """)

    # ── GIN JSONB indexes ─────────────────────────────────────────────────────
    # enriched_keywords — used in quiz generation to find blocks by keyword
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_content_blocks_keywords_gin
        ON content_blocks
        USING gin(enriched_keywords)
    """)

    # bloom_levels_hit on conversations — for analytics queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_bloom_gin
        ON conversations
        USING gin(bloom_levels_hit)
    """)

    # signals on pending_metric_signals — JSONB containment queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_pending_signals_gin
        ON pending_metric_signals
        USING gin(signals)
    """)

    # ── Composite btree indexes for common access patterns ────────────────────

    # Students due for spaced review today (most common query in recommendation engine)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_topic_mastery_review_compound
        ON topic_mastery (user_id, next_review_date, mastery_level)
        WHERE next_review_date IS NOT NULL
    """)

    # Quiz history ordered by date (GET /quiz/history)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_quiz_attempts_user_created
        ON quiz_attempts (user_id, created_at DESC)
    """)

    # Conversation list ordered by updated_at (GET /conversations)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_user_updated
        ON conversations (user_id, updated_at DESC)
        WHERE is_deleted = false
    """)

    # Pinned conversations (appear first in sidebar)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_user_pinned
        ON conversations (user_id, is_pinned)
        WHERE is_pinned = true AND is_deleted = false
    """)

    # LLM cost analysis by date range
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_llm_logs_date_user
        ON llm_call_logs (created_at DESC, user_id)
    """)

    # Message tree traversal (fetch all messages in a conversation ordered)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_conv_created
        ON messages (conversation_id, created_at ASC)
        WHERE is_active_branch = true
    """)

    # Active memory items (loaded on every chat turn)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_memory_items_user_active
        ON student_memory_items (user_id, subject_id, is_active)
        WHERE is_active = true
    """)

    # Job queue: pick next pending job
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_job_queue_next
        ON job_queue (priority ASC, created_at ASC)
        WHERE status = 'pending'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_job_queue_next")
    op.execute("DROP INDEX IF EXISTS idx_memory_items_user_active")
    op.execute("DROP INDEX IF EXISTS idx_messages_conv_created")
    op.execute("DROP INDEX IF EXISTS idx_llm_logs_date_user")
    op.execute("DROP INDEX IF EXISTS idx_conversations_user_pinned")
    op.execute("DROP INDEX IF EXISTS idx_conversations_user_updated")
    op.execute("DROP INDEX IF EXISTS idx_quiz_attempts_user_created")
    op.execute("DROP INDEX IF EXISTS idx_topic_mastery_review_compound")
    op.execute("DROP INDEX IF EXISTS idx_pending_signals_gin")
    op.execute("DROP INDEX IF EXISTS idx_conversations_bloom_gin")
    op.execute("DROP INDEX IF EXISTS idx_content_blocks_keywords_gin")
    op.execute("DROP INDEX IF EXISTS idx_msg_content_blocks_fts")
    op.execute("DROP INDEX IF EXISTS idx_content_blocks_fts")
    op.execute("DROP INDEX IF EXISTS idx_block_embeddings_hnsw")
