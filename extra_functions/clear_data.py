import os
from dotenv import load_dotenv
from db.database import engine, Base

load_dotenv()

def clear_postgres():
    print("Clearing PostgreSQL tables...")
    Base.metadata.drop_all(bind=engine)
    print("PostgreSQL tables dropped.")
    Base.metadata.create_all(bind=engine)
    print("PostgreSQL tables recreated (empty).")

if __name__ == "__main__":
    clear_postgres()
    print("All databases thoroughly reset!")
