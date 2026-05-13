import os
import sys
import json
import logging

# Configure logging and encoding
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)
sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

from ingestion.parser import PDFParser
from ingestion.cleaner import TextCleaner
from ingestion.structurer import TextStructurer
from ingestion.summarizer import Summarizer
from ingestion.llm_repair import LLMStructureRepair
from routing.router import SemanticRouter
from retrieval.engine import RetrievalEngine
from retrieval.reranker import Reranker
from db.database import init_db, SessionLocal
from db.models import Board, SchoolClass, Subject as DBSubject, Chapter as DBChapter, Topic as DBTopic, ContentChunk

# Initialize PostgreSQL tables
init_db()


def ingest_pdf(pdf_path: str, class_num: int, subject: str, chapter: str):
    """
    Complete ingestion pipeline:
    PDF → Parse → Clean → Detect Sections → Validate → Summarize → Store
    """
    logger.info(f"{'='*60}")
    logger.info(f"INGESTING: {pdf_path}")
    logger.info(f"Class: {class_num}, Subject: {subject}, Chapter: {chapter}")
    logger.info(f"{'='*60}")
    
    # ─── STEP 1: Parse PDF with font metadata ───
    logger.info("STEP 1: Parsing PDF with layout detection...")
    parser = PDFParser(use_ocr=False)  # Digital PDFs don't need OCR
    parsed_pages = parser.parse(pdf_path)
    logger.info(f"Parsed {len(parsed_pages)} pages")
    
    # Log element stats for debugging
    total_elements = sum(len(p.get("elements", [])) for p in parsed_pages)
    header_count = sum(1 for p in parsed_pages for e in p.get("elements", []) if e["type"] == "Header")
    logger.info(f"Total elements: {total_elements}, Headers detected: {header_count}")
    
    # ─── STEP 2: Deterministic section detection ───
    logger.info("STEP 2: Detecting topic sections deterministically...")
    structurer = TextStructurer(max_chunk_chars=800)
    topics = structurer.structure(parsed_pages)
    logger.info(f"Found {len(topics)} semantic topics")
    
    for i, t in enumerate(topics):
        logger.info(f"  Topic {i+1}: [{t.get('section_number', '')}] {t['title']} ({len(t['chunks'])} chunks)")
    
    # ─── STEP 3: LLM Validation (optional — corrects OCR in titles) ───
    logger.info("STEP 3: Validating structure with LLM...")
    raw_text_sample = "\n".join(page.get("raw_text", "")[:500] for page in parsed_pages[:3])
    detected_titles = [t["title"] for t in topics]
    
    llm_repair = LLMStructureRepair()
    validated = llm_repair.validate_structure(detected_titles, raw_text_sample)
    
    # Use LLM-corrected chapter title, fall back to provided
    extracted_chapter = validated.get("chapter", chapter)
    if extracted_chapter == "Unknown Chapter":
        extracted_chapter = chapter
    logger.info(f"Chapter title: {extracted_chapter}")
    
    # Apply corrected topic titles from LLM (if available)
    corrected_titles = validated.get("topics", [])
    if len(corrected_titles) == len(topics):
        for i, corrected in enumerate(corrected_titles):
            if corrected.strip():
                topics[i]["title"] = corrected
        logger.info("Applied LLM-corrected topic titles")
    
    # ─── STEP 4: Summarize each topic via LLM ───
    logger.info("STEP 4: Summarizing topics via LLM...")
    summarizer = Summarizer()
    router = SemanticRouter()
    retrieval_engine = RetrievalEngine()
    
    canonical_topics = []
    
    for topic in topics:
        topic_title = topic["title"]
        chunks = topic["chunks"]
        
        if not chunks:
            continue
        
        # Combine chunks for summarization context
        topic_text = "\n\n".join(chunks)
        
        # LLM summarization (rate-limit-safe)
        summary_data = summarizer.summarize_topic(topic_title, topic_text)
        summary = summary_data.get("summary", "")
        keywords = summary_data.get("keywords", [])
        
        # Add to routing layer (Qdrant - curriculum_routing collection)
        router.add_route(class_num, subject, extracted_chapter, topic_title, summary)
        
        # Add chunks to retrieval engine (Qdrant - curriculum_content collection)
        metadata = {
            "class": class_num,
            "subject": subject,
            "chapter": extracted_chapter,
            "topic": topic_title
        }
        
        for chunk in chunks:
            retrieval_engine.upsert_chunk(metadata, chunk)
        
        canonical_topics.append({
            "topic": topic_title,
            "section_number": topic.get("section_number", ""),
            "summary": summary,
            "keywords": keywords,
            "content_chunks": chunks
        })
        
        logger.info(f"  ✓ {topic_title} — {len(chunks)} chunks stored")
    
    # ─── STEP 5: Generate Canonical JSON ───
    logger.info("STEP 5: Generating Canonical Curriculum JSON...")
    canonical_data = {
        "board": "NCERT",
        "class": class_num,
        "subject": subject,
        "chapter": extracted_chapter,
        "topic_count": len(canonical_topics),
        "topics": canonical_topics
    }
    
    base_name = os.path.basename(pdf_path).replace(".pdf", "")
    json_path = os.path.join(os.path.dirname(pdf_path), f"{base_name}_canonical.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(canonical_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Canonical JSON saved: {json_path}")
    
    # ─── STEP 6: Save to PostgreSQL ───
    logger.info("STEP 6: Saving hierarchy to PostgreSQL...")
    _save_to_postgres(class_num, subject, extracted_chapter, canonical_topics)
    
    logger.info(f"{'='*60}")
    logger.info(f"INGESTION COMPLETE: {len(canonical_topics)} topics, {sum(len(t['content_chunks']) for t in canonical_topics)} chunks")
    logger.info(f"{'='*60}")


def _save_to_postgres(class_num: int, subject: str, chapter: str, canonical_topics: list):
    """Persists the canonical curriculum hierarchy to PostgreSQL."""
    db = SessionLocal()
    try:
        # Board
        board = db.query(Board).filter(Board.name == "NCERT").first()
        if not board:
            board = Board(name="NCERT", description="National Council of Educational Research and Training")
            db.add(board)
            db.commit()
        
        # Class
        school_class = db.query(SchoolClass).filter(
            SchoolClass.board_id == board.id, SchoolClass.level == class_num
        ).first()
        if not school_class:
            school_class = SchoolClass(board_id=board.id, name=f"Class {class_num}", level=class_num)
            db.add(school_class)
            db.commit()
        
        # Subject
        db_subject = db.query(DBSubject).filter(
            DBSubject.class_id == school_class.id, DBSubject.name == subject
        ).first()
        if not db_subject:
            db_subject = DBSubject(class_id=school_class.id, name=subject)
            db.add(db_subject)
            db.commit()
        
        # Chapter
        db_chapter = db.query(DBChapter).filter(
            DBChapter.subject_id == db_subject.id, DBChapter.title == chapter
        ).first()
        if not db_chapter:
            db_chapter = DBChapter(subject_id=db_subject.id, title=chapter, chapter_number=1)
            db.add(db_chapter)
            db.commit()
        
        # Topics and Chunks
        for i, topic in enumerate(canonical_topics):
            db_topic = db.query(DBTopic).filter(
                DBTopic.chapter_id == db_chapter.id, DBTopic.title == topic["topic"]
            ).first()
            if not db_topic:
                db_topic = DBTopic(
                    chapter_id=db_chapter.id,
                    title=topic["topic"],
                    topic_number=topic.get("section_number", str(i + 1)),
                    summary=topic["summary"]
                )
                db.add(db_topic)
                db.commit()
            
            for j, chunk_text in enumerate(topic["content_chunks"]):
                existing = db.query(ContentChunk).filter(
                    ContentChunk.topic_id == db_topic.id, ContentChunk.chunk_index == j
                ).first()
                if not existing:
                    db.add(ContentChunk(topic_id=db_topic.id, content=chunk_text, chunk_index=j))
        
        db.commit()
        logger.info("Successfully saved to PostgreSQL!")
    except Exception as e:
        logger.error(f"Database error: {e}")
        db.rollback()
    finally:
        db.close()


def query_system(question: str):
    """Routes a question and retrieves relevant context."""
    logger.info(f"\n{'='*60}")
    logger.info(f"QUERY: {question}")
    logger.info(f"{'='*60}")
    
    # 1. Route
    router = SemanticRouter()
    route = router.route_query(question)
    
    if not route:
        logger.warning("Could not confidently route the question.")
        return
    
    logger.info(f"Routed → Class {route['class']}, {route['subject']}, {route['chapter']}, {route['topic']}")
    
    # 2. Retrieve
    retrieval_engine = RetrievalEngine()
    chunks = retrieval_engine.retrieve(question, route, top_k=5)
    logger.info(f"Retrieved {len(chunks)} chunks")
    
    # 3. Compress Context
    reranker = Reranker()
    context = reranker.compress_context(chunks)
    print("\n--- Compressed Context ---")
    print(context)


if __name__ == "__main__":
    logger.info("AI Tutor Curriculum Engine v2.0")
    # ingest_pdf(
    #     pdf_path="DataSet/Class_10/Science/chapter_1.pdf",
    #     class_num=10,
    #     subject="Science",
    #     chapter="Chemical Reactions and Equations"
    # )
    query_system("What is the rancidity")
