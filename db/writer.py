"""
db/writer.py
────────────
Handles all PostgreSQL persistence for the ingestion pipeline.

Responsibility: Given a list of ProcessedSections for a chapter, persist the
full hierarchy (Board → Class → Subject → Chapter → Topic → ContentChunk)
in an idempotent way (safe to re-run without duplicating rows).
"""
import logging
from core.db_session import managed_session
from db.models import (
    Board,
    SchoolClass,
    Subject as DBSubject,
    Chapter as DBChapter,
    Topic as DBTopic,
    ContentChunk,
)
from schemas import ProcessedSection

logger = logging.getLogger(__name__)

def save_to_postgres(
    class_num: int,
    subject: str,
    chapter_title: str,
    sections: list[ProcessedSection],
) -> None:
    """
    Persists the ingested curriculum hierarchy to PostgreSQL.

    Mapping:
      ProcessedSection  →  Topic   (title = LLM heading, summary = LLM summary)
                        →  ContentChunk  (content = LLM repaired text, chunk_index = 0)

    All operations are idempotent — safe to re-run on the same data.

    Args:
        class_num     : e.g. 10
        subject       : e.g. "Science"
        chapter_title : e.g. "Chemical Reactions and Equations"
        sections      : list of ProcessedSection objects produced by the pipeline
    """
    try:
        with managed_session() as db:
            board = db.query(Board).filter(Board.name == "NCERT").first()
            if not board:
                board = Board(
                    name="NCERT",
                    description="National Council of Educational Research and Training",
                )
                db.add(board)
                db.commit()

            school_class = db.query(SchoolClass).filter(
                SchoolClass.board_id == board.id,
                SchoolClass.level == class_num,
            ).first()
            if not school_class:
                school_class = SchoolClass(
                    board_id=board.id,
                    name=f"Class {class_num}",
                    level=class_num,
                )
                db.add(school_class)
                db.commit()

            db_subject = db.query(DBSubject).filter(
                DBSubject.class_id == school_class.id,
                DBSubject.name == subject,
            ).first()
            if not db_subject:
                db_subject = DBSubject(class_id=school_class.id, name=subject)
                db.add(db_subject)
                db.commit()

            db_chapter = db.query(DBChapter).filter(
                DBChapter.subject_id == db_subject.id,
                DBChapter.title == chapter_title,
            ).first()
            if not db_chapter:
                db_chapter = DBChapter(
                    subject_id=db_subject.id,
                    title=chapter_title,
                    chapter_number=1,
                )
                db.add(db_chapter)
                db.commit()

            for i, section in enumerate(sections):
                db_topic = db.query(DBTopic).filter(
                    DBTopic.chapter_id == db_chapter.id,
                    DBTopic.title == section.heading,
                ).first()

                if not db_topic:
                    db_topic = DBTopic(
                        chapter_id=db_chapter.id,
                        title=section.heading,
                        topic_number=section.section_number or str(i + 1),
                        summary=section.summary,
                    )
                    db.add(db_topic)
                    db.commit()
                    logger.info(f"  DB ✓ Created topic: \"{section.heading}\"")
                else:
                    logger.info(f"  DB — Topic exists, skipping: \"{section.heading}\"")

                existing_chunk = db.query(ContentChunk).filter(
                    ContentChunk.topic_id == db_topic.id,
                    ContentChunk.chunk_index == 0,
                ).first()

                if not existing_chunk:
                    db.add(ContentChunk(
                        topic_id=db_topic.id,
                        content=section.repaired_text,
                        chunk_index=0,
                    ))
                    logger.info(
                        f"  DB ✓ Stored chunk for \"{section.heading}\" "
                        f"({len(section.repaired_text)} chars)"
                    )

            db.commit()
            logger.info("PostgreSQL: all sections saved successfully.")

    except Exception as e:
        logger.error(f"PostgreSQL error: {e}")
        raise
