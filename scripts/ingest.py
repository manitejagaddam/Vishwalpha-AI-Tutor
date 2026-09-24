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
import json
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
    parser.add_argument("--verbose", action="store_true", help="Print full coverage JSON")
    parser.add_argument("--log-file", action="store_true", help="Write logs to a daily file in logs/ instead of terminal")

    parser.add_argument("--json-only", action="store_true", help="Stop before DB insertion and just output the JSON file")
    
    args = parser.parse_args()

    # Reconfigure logging if --log-file is set
    if args.log_file:
        import os
        from datetime import datetime
        os.makedirs("logs", exist_ok=True)
        log_filename = os.path.join("logs", f"ingest_{datetime.now().strftime('%Y%m%d')}.log")
        
        # Remove existing handlers (like the basicConfig stream handler)
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            
        file_handler = logging.FileHandler(log_filename, mode='a', encoding='utf-8')
        file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        root_logger.addHandler(file_handler)
        
        print(f"Logging redirected to {log_filename}")

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
            json_only=args.json_only,
        )
        print(f"\n[SUCCESS] Ingestion complete!")
        print(f"   Status              : {result.get('status', 'unknown')}")
        print(f"   Sections extracted  : {result.get('sections_ingested', 0)}")
        print(f"   Blocks stored       : {result.get('blocks_stored', 0)}")
        print(f"   Chapter ID          : {result.get('chapter_id', 'unknown')}")
        
        conf = result.get('ingestion_confidence')
        conf_str = f"{conf:.3f}" if conf is not None else "N/A"
        print(f"   Confidence          : {conf_str}")
        
        cov = result.get('coverage', {})
        if cov:
            print(f"   Coverage summary    :")
            print(f"      Pages: {cov.get('processed_pages', 0)} processed / {cov.get('total_pages', 0)} total")
            print(f"      OCR pages: {cov.get('ocr_pages', [])}")
            print(f"      Low-conf pages: {cov.get('low_confidence_pages', [])}")
            print(f"      Sections skipped: {cov.get('sections_skipped', 0)} / {cov.get('sections_found', 0)}")
            print(f"      Deduplicated: {cov.get('deduplicated', 0)} blocks")
            
        warns = result.get('warnings', [])
        print(f"   Warnings ({len(warns)}):")
        for w in warns:
            print(f"      - {w}")
            
        if args.verbose and cov:
            print("\n[VERBOSE] Full Coverage JSON:")
            print(json.dumps(cov, indent=2))
            
    except FileNotFoundError as e:
        print(f"\n[ERROR] File not found: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Ingestion failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
