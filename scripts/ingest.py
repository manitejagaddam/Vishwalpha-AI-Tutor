"""
scripts/ingest.py
─────────────────
CLI script to run the ingestion pipeline directly from the terminal.
Usage: python -m scripts.ingest path/to/book.pdf --class 10 --subject Science --chapter "Light"
"""
import argparse
import sys
import logging
from app.services.ingestion_pipeline import IngestionPipeline

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def main():
    parser = argparse.ArgumentParser(description="Ingest a PDF textbook into VishwAlpha.")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument("--class", dest="class_num", type=int, required=True, help="Class number (e.g., 10)")
    parser.add_argument("--subject", type=str, required=True, help="Subject name (e.g., Science)")
    parser.add_argument("--chapter", type=str, required=True, help="Chapter title")
    
    args = parser.parse_args()
    
    pipeline = IngestionPipeline()
    try:
        result = pipeline.process_pdf(args.pdf_path, args.class_num, args.subject, args.chapter)
        print(f"Success! {result['sections_ingested']} sections ingested.")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
