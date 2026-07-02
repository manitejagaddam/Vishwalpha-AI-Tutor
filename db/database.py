"""
db/database.py
──────────────
Database configuration and session management setup.
"""
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from db.models import Base
from dotenv import load_dotenv

load_dotenv(override=True)

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL environment variable is not set. "
        "Please create a .env file and define DATABASE_URL."
    )

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """
    Creates all tables defined in db/models.py if they don't exist.
    """
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
    """
    Generator yielding a new database session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
