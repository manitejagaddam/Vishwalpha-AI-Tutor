"""
app/data/seeds/seeder.py
────────────────────────
Loads the 7-chapter curriculum snapshot into PostgreSQL.
Used by:
  1. Alembic migration 013 (upgrade/downgrade)
  2. scripts/restore_checkpoint.py / restore_7_chapters.ps1
"""
import os
import json
from pathlib import Path
from sqlalchemy import text

TABLES_IN_ORDER = [
    "boards",
    "classes",
    "subjects",
    "books",
    "chapters",
    "topics",
    "subtopics",
    "content_blocks",
    "block_embeddings",
    "content_raw_archive",
    "activities",
    "topic_prerequisites"
]

def load_snapshot_data():
    snapshot_path = Path(__file__).resolve().parent / "snapshot_7_chapters.json"
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot not found at {snapshot_path}")
    with open(snapshot_path, "r", encoding="utf-8") as f:
        return json.load(f)

def seed_snapshot(conn):
    data = load_snapshot_data()

    for tbl in TABLES_IN_ORDER:
        records = data.get(tbl, [])
        if not records:
            continue

        cols = list(records[0].keys())
        col_names = ", ".join(f'"{c}"' for c in cols)
        
        # Build parameterized value placeholders using standard SQL CAST
        # to avoid SQLAlchemy text() parser collisions with double-colons (::)
        placeholders = []
        for c in cols:
            if c == "embedding":
                placeholders.append("CAST(:embedding AS vector)")
            elif c in ("enriched_keywords", "learning_objectives", "key_concepts", "enriched_prerequisites", "keywords"):
                placeholders.append(f"CAST(:{c} AS jsonb)")
            else:
                placeholders.append(f":{c}")
        val_placeholders = ", ".join(placeholders)

        sql = f"INSERT INTO {tbl} ({col_names}) VALUES ({val_placeholders}) ON CONFLICT DO NOTHING"

        # Prepare parameters
        stmt = text(sql)
        for r in records:
            params = {}
            for c in cols:
                val = r[c]
                if c in ("enriched_keywords", "learning_objectives", "key_concepts", "enriched_prerequisites", "keywords"):
                    params[c] = json.dumps(val) if val is not None else None
                else:
                    params[c] = val
            conn.execute(stmt, params)

    # Sync PostgreSQL sequences so subsequent autoincrement IDs don't collide
    for tbl in TABLES_IN_ORDER:
        try:
            seq_sql = text(f"""
                SELECT setval(
                    pg_get_serial_sequence('{tbl}', 'id'),
                    COALESCE((SELECT MAX(id) FROM {tbl}), 1)
                );
            """)
            conn.execute(seq_sql)
        except Exception:
            pass


def downgrade_snapshot(conn):
    """Deletes the seeded 7 chapters (cascading deletes child topics, blocks, embeddings)."""
    conn.execute(text("""
        DELETE FROM chapters 
        WHERE chapter_number IN (1, 2, 3, 10, 11, 12, 13)
        AND book_id IN (
            SELECT id FROM books WHERE natural_key = 'NCERT_10_Science_en_2023'
        )
    """))


def reset_to_snapshot(conn):
    """
    Cleans up any partially-ingested chapters outside 1, 2, 3, 10, 11, 12, 13
    and ensures all 7 snapshot chapters are intact.
    """
    # 1. Delete any chapters other than the 7 snapshot ones
    conn.execute(text("""
        DELETE FROM chapters 
        WHERE chapter_number NOT IN (1, 2, 3, 10, 11, 12, 13)
        AND book_id IN (
            SELECT id FROM books WHERE natural_key = 'NCERT_10_Science_en_2023'
        )
    """))
    # 2. Re-apply snapshot with ON CONFLICT DO NOTHING
    seed_snapshot(conn)
