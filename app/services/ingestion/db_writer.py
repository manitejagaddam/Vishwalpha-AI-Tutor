"""
app/services/ingestion/db_writer.py
─────────────────────────────────────
Stages 13-15: Idempotent DB upserts for the content hierarchy.

Responsibilities:
  - _get_or_create_* helpers for Board / SchoolClass / Subject / Book / Chapter
  - _upsert_topic (two-step safe upsert with unique natural_key)
  - _upsert_subtopic
  - _upsert_topic_prerequisite
  - _upsert_block (ContentBlock + BlockEmbedding in one call)
  - write_structured_topics (main DB write loop for stages 13-15)
  - write_chapter_summary (post-loop chapter-level LLM summarisation)

Every function receives an open SQLAlchemy Session from the caller.
None of them call managed_session() themselves — session lifecycle is
controlled by the pipeline orchestrator.

ARCHITECTURAL INVARIANTS:
  - enriched_summary is embedded AND sent to LLM. raw_text is audit-only.
  - Vec (embedding) must be pre-computed OUTSIDE the session so OpenAI
    timeouts cannot roll back an in-progress DB transaction.
  - BlockEmbedding inserts use raw SQL ON CONFLICT — never ORM add().
"""
from __future__ import annotations

import hashlib
import json
import logging
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.data.models.content import (
    Activity, BlockEmbedding, Board, Book, BookIngestionLog,
    Chapter, ContentBlock, ContentRawArchive, SchoolClass,
    Subject, Subtopic, Topic,
)
from app.data.models.learning import TopicPrerequisite
logger = logging.getLogger(__name__)

PROMPT_VERSION = "v2.0"


# ── Board / Class / Subject / Book / Chapter upserts ─────────────────────────

def get_or_create_board(db: Session, name: str) -> Board:
    obj = db.query(Board).filter(Board.name == name).first()
    if not obj:
        obj = Board(name=name)
        db.add(obj)
        db.flush()
    return obj


def get_or_create_class(db: Session, board_id: int, level: int) -> SchoolClass:
    obj = db.query(SchoolClass).filter(
        SchoolClass.board_id == board_id,
        SchoolClass.level == level,
    ).first()
    if not obj:
        obj = SchoolClass(board_id=board_id, level=level, display_name=f"Class {level}")
        db.add(obj)
        db.flush()
    return obj


def get_or_create_subject(db: Session, class_id: int, name: str) -> Subject:
    obj = db.query(Subject).filter(
        Subject.class_id == class_id,
        Subject.name == name,
    ).first()
    if not obj:
        obj = Subject(class_id=class_id, name=name, display_name=name)
        db.add(obj)
        db.flush()
    return obj


def get_or_create_book(
    db: Session, subject_id: int, title: str, natural_key: str
) -> Book:
    obj = db.query(Book).filter(Book.natural_key == natural_key).first()
    if not obj:
        obj = Book(subject_id=subject_id, title=title, natural_key=natural_key)
        db.add(obj)
        db.flush()
    return obj


def get_or_create_chapter(
    db: Session,
    book_id: int,
    title: str,
    chapter_number: int,
    natural_key: str,
) -> Chapter:
    obj = db.query(Chapter).filter(Chapter.natural_key == natural_key).first()
    if not obj:
        obj = Chapter(
            book_id=book_id, title=title,
            chapter_number=chapter_number, natural_key=natural_key,
        )
        db.add(obj)
        db.flush()
    return obj


# ── Topic / Subtopic / Prerequisite upserts ───────────────────────────────────

def upsert_topic(
    db: Session,
    chapter_id: int,
    chap_nk: str,
    title: str,
    order: int,
    topic_number: str | None = None,
) -> Topic:
    """
    Safely upserts a Topic row using natural_key as the conflict key.

    natural_key = "{chap_nk}_{slug}" — globally unique across ALL boards, classes,
    subjects.  Using bare chapter_num collides across subjects (e.g. both Class 9
    History Ch1 and Class 10 Maths Ch1 can have an 'Introduction' topic).

    Two-step approach:
      Step 1 — INSERT without topic_number; ON CONFLICT (natural_key) DO UPDATE.
      Step 2 — UPDATE topic_number only when no other row in the chapter already
               holds that value (silently skips on collision).
    """
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower())[:80]
    nk   = f"{chap_nk}_{slug}"

    db.execute(text("""
        INSERT INTO topics
            (chapter_id, title, natural_key, display_order, prompt_version)
        VALUES
            (:chapter_id, :title, :nk, :display_order, :pv)
        ON CONFLICT (natural_key)
        DO UPDATE SET
            title         = EXCLUDED.title,
            display_order = EXCLUDED.display_order
    """), {
        "chapter_id":    chapter_id,
        "title":         title,
        "nk":            nk,
        "display_order": order,
        "pv":            PROMPT_VERSION,
    })
    db.flush()

    if topic_number is not None:
        db.execute(text("""
            UPDATE topics
               SET topic_number = :tn
             WHERE natural_key  = :nk
               AND NOT EXISTS (
                       SELECT 1 FROM topics t2
                        WHERE t2.chapter_id   = :chapter_id
                          AND t2.topic_number = :tn
                          AND t2.natural_key != :nk
               )
        """), {"tn": topic_number, "nk": nk, "chapter_id": chapter_id})
        db.flush()

    return db.query(Topic).filter(Topic.natural_key == nk).one()


def upsert_subtopic(db: Session, topic_id: int, title: str, order: int) -> Subtopic:
    obj = db.query(Subtopic).filter(
        Subtopic.topic_id == topic_id,
        Subtopic.title == title,
    ).first()
    if not obj:
        obj = Subtopic(topic_id=topic_id, title=title, display_order=order)
        db.add(obj)
        db.flush()
    return obj


def upsert_topic_prerequisite(
    db: Session, topic_id: int, prereq: str
) -> TopicPrerequisite:
    obj = db.query(TopicPrerequisite).filter(
        TopicPrerequisite.topic_id == topic_id,
        TopicPrerequisite.prereq_description == prereq,
    ).first()
    if not obj:
        obj = TopicPrerequisite(
            topic_id=topic_id,
            prereq_class_num=0,
            prereq_subject_id=None,
            prereq_description=prereq,
        )
        db.add(obj)
        db.flush()
    return obj


# ── ContentBlock + BlockEmbedding upsert ─────────────────────────────────────

def upsert_block(
    db: Session,
    topic_id: int,
    raw_text: str,
    block_index: int,
    subtopic_id: int | None = None,
    block_type: str = "text",
    page_num: int | None = None,
    ocr_confidence: float | None = None,
    summary: str = "",
    keywords: list | None = None,
    prerequisites: list | None = None,
    vec: list[float] | None = None,
) -> ContentBlock:
    """
    Upserts a ContentBlock and its BlockEmbedding.

    IMPORTANT: `vec` must be pre-computed BEFORE opening the managed_session that
    calls this function.  If _embed() were called here and the OpenAI call timed out,
    SQLAlchemy would roll back the entire transaction, losing every block flushed so
    far in that chapter.  The pipeline orchestrator computes `vec` ahead of time.
    """
    ch  = hashlib.md5(raw_text.strip().lower().encode()).hexdigest()
    blk = db.query(ContentBlock).filter(
        ContentBlock.topic_id == topic_id,
        ContentBlock.block_index == block_index,
    ).first()
    if not blk:
        blk = ContentBlock(
            topic_id=topic_id,
            subtopic_id=subtopic_id,
            block_type=block_type,
            raw_text=raw_text,
            block_index=block_index,
            page_num=page_num,
            ocr_confidence=ocr_confidence,
            content_hash=ch,
            enriched_summary=summary or None,
            enriched_keywords=keywords or None,
            enriched_prerequisites=prerequisites or None,
            prompt_version=PROMPT_VERSION,
        )
        db.add(blk)
        db.flush()
    else:
        blk.raw_text        = raw_text
        blk.content_hash    = ch
        blk.ocr_confidence  = ocr_confidence
        blk.subtopic_id     = subtopic_id
        if summary:       blk.enriched_summary      = summary
        if keywords:      blk.enriched_keywords     = keywords
        if prerequisites: blk.enriched_prerequisites = prerequisites

    if vec is not None:
        # Inline the vector literal — SQLAlchemy text() parser chokes on :param::vector
        vec_str = "[" + ",".join(str(x) for x in vec) + "]"
        db.execute(text(f"""
            INSERT INTO block_embeddings (block_id, embedding, embedding_model)
            VALUES (:block_id, '{vec_str}'::vector, :model)
            ON CONFLICT (block_id, embedding_model)
            DO UPDATE SET embedding = EXCLUDED.embedding
        """), {
            "block_id": blk.id,
            "model":    settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
        })
        db.flush()

    return blk


# ── Main DB write loop (stages 13-15) ────────────────────────────────────────

def write_structured_topics(
    db: Session,
    structured_topics: list[tuple[str, dict]],
    chapter_id: int,
    chap_nk: str,
    chapter_title: str,
    llm_output_data: dict[str, dict],
    embed_fn,
) -> tuple[int, int, set[str]]:
    """
    Writes all structured LLM sections to the DB as Topics + ContentBlocks.

    Args:
        db:               Open SQLAlchemy session (managed by pipeline orchestrator).
        structured_topics: List of (paddlex_heading, topic_data_dict) tuples.
        chapter_id:       DB id of the parent Chapter.
        chap_nk:          Chapter natural key prefix (e.g. "NCERT_10_Science_en_2023_ch1").
        chapter_title:    Fallback topic title.
        llm_output_data:  Keyed by "{sec_idx}:{heading}" → {"raw_blocks": [...], "llm_data": {...}}.
        embed_fn:         Callable(text: str) → list[float]. Must be called OUTSIDE session.

    Returns:
        (total_blocks_stored, skipped_count, seen_hashes)
    """
    from app.services.ingestion.models import TOPIC_RE

    total_blocks  = 0
    skipped       = 0
    seen: set[str] = set()
    last_concept_topic: Topic | None = None

    for order, (paddlex_heading, topic_data) in enumerate(structured_topics):
        topic_title    = topic_data.get("heading") or chapter_title
        content_type   = topic_data.get("content_type", "concept")
        topic_summary  = topic_data.get("summary", "")
        topic_prereqs  = topic_data.get("prerequisites", [])
        topic_keywords = topic_data.get("keywords", [])

        from app.services.ingestion.structure_detector import classify_level
        level       = classify_level(paddlex_heading)
        subtopic_obj: Subtopic | None = None

        # Extract topic_number (e.g. "1.2") from the paddleX heading
        topic_number = None
        m = TOPIC_RE.match(paddlex_heading)
        if m:
            topic_number = f"{m.group(1)}.{m.group(2)}" + (
                f".{m.group(3)}" if m.group(3) else ""
            )

        if level == 2 and last_concept_topic:
            subtopic_obj = upsert_subtopic(db, last_concept_topic.id, paddlex_heading, order)
            topic_obj    = last_concept_topic
        else:
            topic_obj = upsert_topic(
                db, chapter_id, chap_nk, topic_title, order, topic_number=topic_number,
            )
            topic_obj.summary        = topic_summary
            topic_obj.content_type   = content_type
            topic_obj.difficulty_level = topic_data.get("difficulty_level")

            if content_type != "activity":
                last_concept_topic = topic_obj

        # Activities → Activity table; skip ContentBlock insert
        if content_type == "activity":
            parent_topic_id = (last_concept_topic.id if last_concept_topic else topic_obj.id)
            db.add(Activity(
                topic_id=parent_topic_id,
                title=topic_title,
                content=topic_data.get("repaired_text", ""),
                summary=topic_summary,
                keywords=topic_data.get("keywords", []),
                difficulty_level=topic_data.get("difficulty_level"),
            ))
            continue

        for prereq in topic_prereqs:
            upsert_topic_prerequisite(db, topic_obj.id, prereq)

        repaired_text = topic_data.get("repaired_text", "")
        if not repaired_text.strip():
            logger.warning(f"[Ingestion] Empty repaired_text for '{topic_title}' — skipped.")
            skipped += 1
            continue

        # Stage 13: content deduplication (MD5)
        content_hash = hashlib.md5(repaired_text.strip().lower().encode()).hexdigest()
        if content_hash in seen:
            logger.debug(f"[Ingestion] Duplicate section skipped: '{topic_title}'")
            continue
        seen.add(content_hash)

        # Embed outside session (caller pre-computes, we just pass it in).
        # If embedding fails, store block without vector — re-run ingest to fix.
        embed_input = topic_summary.strip() if topic_summary.strip() else repaired_text
        try:
            vec = embed_fn(embed_input)
        except Exception as emb_exc:
            logger.warning(
                f"[Ingestion] Embedding failed for '{topic_title}': {emb_exc}. "
                "Block stored without vector — re-run ingest to fix."
            )
            vec = None

        blk_row = upsert_block(
            db, topic_obj.id,
            raw_text=repaired_text,
            block_index=order,
            subtopic_id=subtopic_obj.id if subtopic_obj else None,
            block_type=content_type,
            page_num=None,
            ocr_confidence=None,
            summary=topic_summary,
            keywords=topic_keywords,
            prerequisites=topic_prereqs,
            vec=vec,
        )
        total_blocks += 1

        # Write raw OCR text to audit archive (ContentRawArchive — never used in retrieval)
        sec_key_lookup = f"{order}:{paddlex_heading}"
        if blk_row and not db.query(ContentRawArchive).filter(
            ContentRawArchive.block_id == blk_row.id
        ).first():
            raw_ocr = "\n\n".join(
                llm_output_data.get(sec_key_lookup, {}).get("raw_blocks", [])
            )
            db.add(ContentRawArchive(
                block_id=blk_row.id,
                raw_text=raw_ocr,
                repaired_text=repaired_text,
            ))

    return total_blocks, skipped, seen


# ── Chapter-level LLM summarization ──────────────────────────────────────────

def write_chapter_summary(
    db: Session,
    chapter_id: int,
    chapter_title: str,
    structured_topics: list[tuple[str, dict]],
    llm_client,
    model: str,
) -> None:
    """
    Generates a chapter-level summary using already-produced topic summaries.
    Populates Chapter.summary, Chapter.learning_objectives, Chapter.key_concepts.
    Non-fatal — logs a warning and returns silently on error.
    """
    from app.prompts import CHAPTER_SUMMARY_PROMPT

    topic_summaries = [
        ts for _, td in structured_topics
        if (ts := td.get("summary", "").strip())
    ]
    if not topic_summaries:
        return

    try:
        joined    = "\n".join(f"- {s}" for s in topic_summaries)
        prompt    = CHAPTER_SUMMARY_PROMPT.format(
            chapter_title=chapter_title,
            topic_summaries=joined,
        )
        chap_resp = llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a curriculum summariser. Output only JSON."},
                {"role": "user",   "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        chap_data = json.loads(chap_resp.choices[0].message.content)
        chap_row  = db.query(Chapter).filter(Chapter.id == chapter_id).first()
        if chap_row:
            chap_row.summary             = chap_data.get("summary", "")
            chap_row.learning_objectives = json.dumps(chap_data.get("learning_objectives", []))
            chap_row.key_concepts        = json.dumps(chap_data.get("key_concepts", []))
            chap_row.prompt_version      = PROMPT_VERSION
        logger.info(f"[Ingestion] Chapter summary written for chapter_id={chapter_id}")
    except Exception as exc:
        logger.warning(f"[Ingestion] Chapter summarization failed (non-fatal): {exc}")


# ── BookIngestionLog update ───────────────────────────────────────────────────

def update_ingestion_log(
    db: Session,
    log_id: int | None,
    status: str,
    coverage: dict,
    confidence: float | None,
    error: str | None = None,
) -> None:
    """Updates the BookIngestionLog row status/coverage/confidence after the pipeline run."""
    from datetime import datetime, timezone
    if log_id is None:
        return
    log = db.query(BookIngestionLog).filter(BookIngestionLog.id == log_id).first()
    if log:
        log.status               = status
        log.coverage             = coverage
        log.ingestion_confidence = confidence
        log.error                = error
        log.finished_at          = datetime.now(timezone.utc)
