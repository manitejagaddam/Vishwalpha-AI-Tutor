import logging
from sqlalchemy import text
from app.data.database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fix_db2")

def add_missing_columns():
    with engine.begin() as conn:
        columns_to_add = [
            ("conversation_sessions", "memory_summary", "TEXT"),
            ("conversation_sessions", "last_remark", "TEXT"),
            ("conversation_sessions", "last_remark_turn", "INTEGER DEFAULT 0"),
            ("conversation_sessions", "topics_covered", "TEXT DEFAULT '[]'"),
            ("conversation_sessions", "last_topic_name", "VARCHAR(300)"),
        ]
        
        for table, column, col_type in columns_to_add:
            try:
                logger.info(f"Adding {column} to {table}...")
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type};"))
                logger.info(f"Successfully added/verified {column} for {table}")
            except Exception as e:
                logger.error(f"Error adding {column} to {table}: {e}")

if __name__ == "__main__":
    add_missing_columns()
