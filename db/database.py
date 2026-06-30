import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from db.models import Base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Using psycopg2 as the driver
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Creates all tables defined in db/models.py if they don't exist."""
    print("Initializing PostgreSQL database...")
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
    except Exception as e:
        print(f"Error enabling pgvector extension (non-critical if already enabled): {e}")
    Base.metadata.create_all(bind=engine)
    print("Database tables created/verified.")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
