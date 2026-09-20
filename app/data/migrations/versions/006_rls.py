"""
006_rls.py
───────────
Migration: Row-Level Security (RLS) policies on all student-data tables.

Design:
  - RLS is ENABLED on every table that holds student personal/learning data.
  - Policy type: PERMISSIVE (overlapping policies are ORed).
  - The application connects as the `authenticated` role (Supabase default).
  - Admin role bypasses RLS (BYPASSRLS privilege granted separately via Supabase dashboard).
  - JWT `sub` claim is surfaced as `auth.uid()` by Supabase.

  For local development without Supabase RLS enforcement, these policies
  are still added but have no effect when connecting as a SUPERUSER.

IMPORTANT: These policies assume Supabase's `auth.uid()` function.
If running on a raw PostgreSQL instance (non-Supabase), replace `auth.uid()`
with `current_setting('app.current_user_id', true)::uuid` and set the
session variable in the FastAPI middleware after JWT verification.
"""
from alembic import op


revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


# Tables and their user_id column name
_STUDENT_TABLES = [
    ("student_profiles",           "user_id"),
    ("student_subject_profiles",   "user_id"),
    ("overall_cognitive_profiles", "user_id"),
    ("cognitive_metric_history",   "user_id"),
    ("learning_preferences",       "user_id"),
    ("student_memory_items",       "user_id"),
    ("topic_mastery",              "user_id"),
    ("mastery_events",             "user_id"),
    ("student_goals",              "user_id"),
    ("student_streaks",            "user_id"),
    ("student_tasks",              "user_id"),
    ("pending_metric_signals",     "user_id"),
    ("subject_quiz_feedback",      "user_id"),
    ("quiz_attempts",              "user_id"),
    ("conversations",              "user_id"),
    ("user_sessions",              "user_id"),
    ("study_spaces",               "user_id"),
    ("artifacts",                  "user_id"),
    ("usage_ledger",               "user_id"),
]


def upgrade() -> None:
    for table, col in _STUDENT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_owner ON {table}
            USING ({col}::text = current_setting('app.current_user_id', true))
        """)

    # ── Special: messages are accessed via conversation_id (not direct user_id) ──
    op.execute("ALTER TABLE messages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE messages FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY messages_owner ON messages
        USING (
            conversation_id IN (
                SELECT id FROM conversations
                WHERE user_id::text = current_setting('app.current_user_id', true)
            )
        )
    """)

    # ── Special: session_insights (has user_id) ─────────────────────────────
    op.execute("ALTER TABLE session_insights ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE session_insights FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY session_insights_owner ON session_insights
        USING (user_id::text = current_setting('app.current_user_id', true))
    """)


def downgrade() -> None:
    for table, _ in _STUDENT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_owner ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS messages_owner ON messages")
    op.execute("ALTER TABLE messages DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS session_insights_owner ON session_insights")
    op.execute("ALTER TABLE session_insights DISABLE ROW LEVEL SECURITY")
