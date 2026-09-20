import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.data.database import SessionLocal
from app.data.models.content import Board, SchoolClass, Subject

def seed_curriculum():
    db = SessionLocal()
    try:
        # Create Board
        board = db.query(Board).filter_by(name="NCERT").first()
        if not board:
            board = Board(name="NCERT", description="National Council of Educational Research and Training")
            db.add(board)
            db.commit()
            db.refresh(board)
            print(f"Created board: {board.name}")
        
        # Create Class 10
        cls10 = db.query(SchoolClass).filter_by(board_id=board.id, level=10).first()
        if not cls10:
            cls10 = SchoolClass(board_id=board.id, level=10, display_name="Class 10")
            db.add(cls10)
            db.commit()
            db.refresh(cls10)
            print(f"Created class: {cls10.display_name}")
            
        # Create Subjects
        subjects = ["Science", "Mathematics", "Social Science", "English"]
        for sub_name in subjects:
            sub = db.query(Subject).filter_by(class_id=cls10.id, name=sub_name).first()
            if not sub:
                sub = Subject(class_id=cls10.id, name=sub_name, display_name=sub_name)
                db.add(sub)
                db.commit()
                print(f"Created subject: {sub_name}")
                
        print("Seeding complete.")
    finally:
        db.close()

if __name__ == "__main__":
    seed_curriculum()
