"""
fix_columns.py
──────────────
One-time script to add any missing columns that migrate.py may have missed
due to table drop/recreate ordering. Safe to re-run (all are IF NOT EXISTS).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.database import engine
from sqlalchemy import text

PATCHES = [
    ("conversation_sessions",   "diagnostic_state", "TEXT"),
    ("student_subject_profiles","tasks",             "TEXT"),
    ("topics",                  "prerequisites",     "TEXT"),
    ("topics",                  "chapter_number",    "INTEGER"),
]

with engine.connect() as conn:
    for table, column, col_type in PATCHES:
        r = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{table}' AND column_name = '{column}'"
        ))
        exists = r.fetchone() is not None
        if not exists:
            conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}"
            ))
            conn.commit()
            print(f"  + Added {table}.{column}")
        else:
            print(f"  [OK] {table}.{column} already present")

print("\nAll patches applied successfully!")
