import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from db.database import engine, Base

load_dotenv()

def clear_postgres():
    print("Clearing PostgreSQL tables...")
    Base.metadata.drop_all(bind=engine)
    print("PostgreSQL tables dropped.")
    Base.metadata.create_all(bind=engine)
    print("PostgreSQL tables recreated (empty).")

def clear_qdrant():
    print("Clearing Qdrant collections...")
    qdrant_url = os.environ.get("QDRANT_URL")
    qdrant_api_key = os.environ.get("QDRANT_API_KEY")
    
    if qdrant_url and qdrant_api_key:
        client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        
        # All Collections used in the system
        collections = ["curriculum_routing", "curriculum_content"]
        
        for collection in collections:
            if client.collection_exists(collection_name=collection):
                client.delete_collection(collection_name=collection)
                print(f"Deleted Qdrant collection: {collection}")
    else:
        print("QDRANT_URL or QDRANT_API_KEY missing. Cannot clear remote Qdrant.")

if __name__ == "__main__":
    clear_postgres()
    clear_qdrant()
    print("All databases thoroughly reset!")
