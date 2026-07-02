"""
main.py
───────
Entry point for the VishwAlpha AI Tutor.

Usage:
  python main.py --serve       Start the FastAPI server (default: port 8000)
  python main.py --ingest      Run the PDF ingestion pipeline
  python main.py               Interactive CLI chat for testing
"""

import sys
import logging
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
sys.stdout.reconfigure(encoding="utf-8")

load_dotenv(override=True)

from db.database import init_db
init_db()

def run_server():
    """Starts the FastAPI server."""
    import uvicorn
    logger.info("Starting VishwAlpha AI Tutor API server...")
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)

def run_ingest():
    """Runs the PDF ingestion pipeline."""
    from ingestion.pipeline import ingest_pdf
    ingest_pdf(
        pdf_path="DataSet/Class_10/Science/chapter_2.pdf",
        class_num=10,
        subject="Science",
        chapter="Acids, Bases and Salts",
    )

def run_interactive_chat():
    """Interactive CLI chat for quick testing."""
    from schemas import ChatRequest
    from tutor.chat import chat

    print("\n╔══════════════════════════════════════════════════════╗")
    print("║      VishwAlpha AI Tutor — Interactive Mode         ║")
    print("║      Type 'quit' or 'exit' to stop                  ║")
    print("║      Type 'new' to start a new session              ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    session_id = ""

    while True:
        try:
            question = input("Student > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not question:
            continue
        if question.lower() in ("quit", "exit"):
            print("Goodbye!")
            break
        if question.lower() == "new":
            session_id = ""
            print("🆕 Starting a new session.\n")
            continue

        request = ChatRequest(
            student_id="test_student",
            session_id=session_id,
            question=question,
            class_num=10,
            subject="Science",
        )

        response = chat(request)
        session_id = response.session_id

        print(f"\nTutor > {response.answer}")
        if response.sources:
            sources_str = ", ".join(f"{s.topic} ({s.score})" for s in response.sources)
            print(f"  📚 Sources: {sources_str}")
        print(f"  💬 Turn #{response.conversation_length // 2}\n")

if __name__ == "__main__":
    if "--serve" in sys.argv:
        run_server()
    elif "--ingest" in sys.argv:
        run_ingest()
    else:
        run_interactive_chat()
