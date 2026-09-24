"""
scripts/restore_checkpoint.py
─────────────────────────────
Restores the database to the 7-chapter clean checkpoint.
Purges any failed/partial chapters outside (1, 2, 3, 10, 11, 12, 13)
and guarantees all 7 chapters and their 199 blocks/embeddings are intact.
"""
from app.data.session_repo import managed_session
from app.data.seeds.seeder import reset_to_snapshot

def main():
    print("Restoring database to 7-chapter clean checkpoint...")
    with managed_session() as session:
        reset_to_snapshot(session.connection())
    print("Database successfully restored to 7-chapter checkpoint!")

if __name__ == "__main__":
    main()
