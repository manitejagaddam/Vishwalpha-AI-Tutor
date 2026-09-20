"""
scripts/ingest.py
─────────────────
CLI script to ingest a PDF textbook into VishwAlpha.

Usage:
  python -m scripts.ingest path/to/book.pdf \\
      --board NCERT --class 10 --subject Science \\
      --book-title "NCERT Science Class 10" \\
      --book-key "NCERT_10_Science_en_2023" \\
      --chapter "Light - Reflection and Refraction" --chapter-num 10

Example (quick):
  python -m scripts.ingest DataSet/science.pdf --board NCERT --class 10 \\
      --subject Science --book-title "NCERT Science Class 10" \\
      --book-key "NCERT_10_Science_en" --chapter "Chemical Reactions" --chapter-num 1
"""
import argparse
import sys
import logging
from app.services.ingestion_pipeline import IngestionPipeline

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Ingest a PDF textbook chapter into VishwAlpha.")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument("--board",       default="NCERT",  help="Board name (default: NCERT)")
    parser.add_argument("--class",       dest="class_num", type=int, required=True,
                        help="Class level, e.g. 10")
    parser.add_argument("--subject",     required=True,    help="Subject name, e.g. Science")
    parser.add_argument("--book-title",  required=True,    help="Book title")
    parser.add_argument("--book-key",    required=True,
                        help="Unique book natural key, e.g. NCERT_10_Science_en_2023")
    parser.add_argument("--chapter",     required=True,    help="Chapter title")
    parser.add_argument("--chapter-num", dest="chapter_num", type=int, required=True,
                        help="Chapter number (integer)")

    args = parser.parse_args()

    pipeline = IngestionPipeline()
    try:
        result = pipeline.process_pdf(
            pdf_path=args.pdf_path,
            board_name=args.board,
            class_num=args.class_num,
            subject_name=args.subject,
            book_title=args.book_title,
            book_natural_key=args.book_key,
            chapter_title=args.chapter,
            chapter_number=args.chapter_num,
        )
        print(f"\n[SUCCESS] Ingestion complete!")
        print(f"   Sections extracted : {result['sections_ingested']}")
        print(f"   Content blocks stored: {result.get('blocks_stored', '?')}")
        print(f"   Chapter ID: {result.get('chapter_id')}")
    except FileNotFoundError as e:
        print(f"\n[ERROR] File not found: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Ingestion failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
