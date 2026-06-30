import os
from sqlalchemy import text
from db.database import engine, Base
from db.models import *

def run_migration():
    with engine.connect() as conn:
        print("Dropping old session tables...")
        conn.execute(text("DROP TABLE IF EXISTS conversation_messages CASCADE;"))
        conn.execute(text("DROP TABLE IF EXISTS conversation_sessions CASCADE;"))
        conn.commit()
        
        print("Altering chapters and topics...")
        try:
            conn.execute(text("ALTER TABLE chapters ADD COLUMN IF NOT EXISTS learning_objectives TEXT;"))
            conn.execute(text("ALTER TABLE chapters ADD COLUMN IF NOT EXISTS key_concepts TEXT;"))
            conn.commit()
        except Exception as e:
            print(f"Error altering chapters: {e}")
            
        try:
            conn.execute(text("ALTER TABLE topics ADD COLUMN IF NOT EXISTS chapter_number INTEGER;"))
            conn.commit()
        except Exception as e:
            print(f"Error altering topics: {e}")
            
    print("Creating new tables...")
    Base.metadata.create_all(bind=engine)
    print("Migration complete!")

if __name__ == "__main__":
    run_migration()
