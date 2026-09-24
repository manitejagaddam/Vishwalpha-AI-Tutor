"""
scripts/export_snapshot.py
──────────────────────────
Exports the current 7-chapter database state into:
  1. app/data/seeds/snapshot_7_chapters.json
  2. app/data/seeds/snapshot_7_chapters.sql

Captures:
  - boards
  - classes
  - subjects
  - books
  - chapters
  - topics
  - subtopics
  - content_blocks
  - block_embeddings
  - content_raw_archive
  - activities
  - topic_prerequisites
"""
import os
import json
from datetime import datetime
from sqlalchemy import text
from app.data.session_repo import managed_session

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

def serialize_val(val):
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if hasattr(val, "tolist"):
        return val.tolist()
    if isinstance(val, (list, dict)):
        return val
    return str(val) if not isinstance(val, (int, float, bool)) else val

def sql_quote(val, col_type=None):
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, (list, dict)):
        s = json.dumps(val).replace("'", "''")
        return f"'{s}'::jsonb"
    s = str(val).replace("'", "''")
    return f"'{s}'"

def export_all():
    os.makedirs("app/data/seeds", exist_ok=True)
    json_path = "app/data/seeds/snapshot_7_chapters.json"
    sql_path = "app/data/seeds/snapshot_7_chapters.sql"

    all_data = {}
    sql_statements = [
        "-- VishwAlpha 7-Chapter Database Snapshot",
        f"-- Exported on: {datetime.now().isoformat()}",
        "BEGIN;",
        ""
    ]

    with managed_session() as session:
        for tbl in TABLES_IN_ORDER:
            # Query all columns for table
            res = session.execute(text(f"SELECT * FROM {tbl}"))
            cols = list(res.keys())
            rows = res.fetchall()
            print(f"Exporting {tbl}: {len(rows)} rows")

            tbl_records = []
            for r in rows:
                row_dict = {}
                for idx, col in enumerate(cols):
                    val = r[idx]
                    row_dict[col] = serialize_val(val)
                tbl_records.append(row_dict)

                # Format SQL INSERT statement
                val_strs = []
                for idx, col in enumerate(cols):
                    val = r[idx]
                    if col == "embedding" and val is not None:
                        # Vector handling
                        if hasattr(val, "tolist"):
                            vec_list = val.tolist()
                        elif isinstance(val, list):
                            vec_list = val
                        else:
                            vec_list = str(val)
                        val_strs.append(f"'{vec_list}'::vector")
                    else:
                        val_strs.append(sql_quote(val))

                col_names_joined = ", ".join(f'"{c}"' for c in cols)
                vals_joined = ", ".join(val_strs)
                sql_statements.append(f'INSERT INTO {tbl} ({col_names_joined}) VALUES ({vals_joined}) ON CONFLICT DO NOTHING;')

            all_data[tbl] = tbl_records
            sql_statements.append("")

    sql_statements.append("COMMIT;")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=2)
    print(f"Saved JSON snapshot to {json_path}")

    with open(sql_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sql_statements))
    print(f"Saved SQL snapshot to {sql_path}")

if __name__ == "__main__":
    export_all()
