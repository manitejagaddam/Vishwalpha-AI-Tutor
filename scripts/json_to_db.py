"""
scripts/json_to_db.py
─────────────────────
Stage 2 of the two-step ingestion pipeline.

Reads a pre-generated debug JSON file (produced by the ingestion pipeline's
debug dump) and inserts the structured content into the Supabase database.

NO OCR, NO LLM structuring calls are made. Only:
  - One Azure OpenAI embedding call per ContentBlock (cheap, fast).
  - One Azure OpenAI chat call for chapter-level summarization (from topic summaries).

Usage:
  python -m scripts.json_to_db path/to/ingest_debug_chapter_1.json \
      --board NCERT --class 10 --subject Science \
      --book-title "NCERT Science Class 10" \
      --book-key "NCERT_10_Science_en_2023" \
      --chapter "Chemical Reactions and Equations" --chapter-num 1
"""
import argparse
import hashlib
import json
import logging
import re
import sys

from sqlalchemy import text

from app.config import settings
from app.data.database import managed_session
from app.data.models.content import (
    Activity,
    BlockEmbedding,
    Board,
    Book,
    Chapter,
    ContentBlock,
    ContentRawArchive,
    SchoolClass,
    Subject,
    Subtopic,
    Topic,
)
from app.data.models.learning import TopicPrerequisite
from app.infra.azure_openai_client import get_openai

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_TOPIC_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?\s+(.*)", re.DOTALL)
PROMPT_VERSION = "json_to_db_v1"


def _get_or_create_board(db, name):
    obj = db.query(Board).filter(Board.name == name).first()
    if not obj:
        obj = Board(name=name); db.add(obj); db.flush()
    return obj

def _get_or_create_class(db, board_id, level):
    obj = db.query(SchoolClass).filter(SchoolClass.board_id == board_id, SchoolClass.level == level).first()
    if not obj:
        obj = SchoolClass(board_id=board_id, level=level, display_name=f"Class {level}")
        db.add(obj); db.flush()
    return obj

def _get_or_create_subject(db, class_id, name):
    obj = db.query(Subject).filter(Subject.class_id == class_id, Subject.name == name).first()
    if not obj:
        obj = Subject(class_id=class_id, name=name, display_name=name)
        db.add(obj); db.flush()
    return obj

def _get_or_create_book(db, subject_id, title, natural_key):
    obj = db.query(Book).filter(Book.natural_key == natural_key).first()
    if not obj:
        obj = Book(subject_id=subject_id, title=title, natural_key=natural_key)
        db.add(obj); db.flush()
    return obj

def _get_or_create_chapter(db, book_id, title, chapter_number, natural_key):
    obj = db.query(Chapter).filter(Chapter.natural_key == natural_key).first()
    if not obj:
        obj = Chapter(book_id=book_id, title=title, chapter_number=chapter_number, natural_key=natural_key)
        db.add(obj); db.flush()
    return obj

def _upsert_topic(db, chapter_id, chap_nk, title, order, topic_number=None):
    """
    Upsert a Topic row.

    natural_key = "{chap_nk}_{slug}" where chap_nk is the chapter's own
    natural_key (e.g. NCERT_10_Science_en_2023_ch1).  This makes the topic
    natural_key globally unique across ALL classes, subjects, and boards.

    Using bare chapter_num (1, 2, 13) as a prefix would collide the moment two
    different subjects have a topic with the same title in the same chapter
    number — e.g. both Class 9 History Ch1 and Class 10 Maths Ch1 produce
    a topic called 'Introduction' → ch1_introduction conflicts.

    Two-step approach to avoid hitting two different unique constraints
    simultaneously (natural_key AND uq_topics_chapter_num):
      Step 1 — INSERT without topic_number; ON CONFLICT (natural_key) DO UPDATE.
      Step 2 — UPDATE topic_number only if no other row in the chapter already
               holds that value (avoids uq_topics_chapter_num violation).
    """
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower())[:80]
    nk   = f"{chap_nk}_{slug}"

    # Step 1: idempotent upsert — topic_number excluded to avoid the
    # uq_topics_chapter_num constraint firing on the same INSERT.
    db.execute(text("""
        INSERT INTO topics
            (chapter_id, title, natural_key, display_order, prompt_version)
        VALUES
            (:chapter_id, :title, :nk, :display_order, :prompt_version)
        ON CONFLICT (natural_key)
        DO UPDATE SET
            title         = EXCLUDED.title,
            display_order = EXCLUDED.display_order
    """), {
        "chapter_id":    chapter_id,
        "title":         title,
        "nk":            nk,
        "display_order": order,
        "prompt_version": PROMPT_VERSION,
    })
    db.flush()

    # Step 2: set topic_number only if no other row in this chapter already
    # owns that value — silently skips if there would be a collision.
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


def _upsert_subtopic(db, topic_id, title, order):
    obj = db.query(Subtopic).filter(Subtopic.topic_id == topic_id, Subtopic.title == title).first()
    if not obj:
        obj = Subtopic(topic_id=topic_id, title=title, display_order=order)
        db.add(obj); db.flush()
    return obj

def _upsert_topic_prerequisite(db, topic_id, prereq):
    obj = db.query(TopicPrerequisite).filter(
        TopicPrerequisite.topic_id == topic_id, TopicPrerequisite.prereq_description == prereq
    ).first()
    if not obj:
        obj = TopicPrerequisite(topic_id=topic_id, prereq_class_num=0, prereq_subject_id=None, prereq_description=prereq)
        db.add(obj); db.flush()
    return obj

def _upsert_block(db, topic_id, raw_text, block_index, subtopic_id=None, block_type="text",
                  summary="", keywords=None, prerequisites=None, vec=None):
    ch  = hashlib.md5(raw_text.strip().lower().encode()).hexdigest()
    blk = db.query(ContentBlock).filter(
        ContentBlock.topic_id == topic_id, ContentBlock.block_index == block_index
    ).first()
    if not blk:
        blk = ContentBlock(
            topic_id=topic_id, subtopic_id=subtopic_id, block_type=block_type,
            raw_text=raw_text, block_index=block_index, page_num=None,
            ocr_confidence=None, content_hash=ch,
            enriched_summary=summary or None,
            enriched_keywords=keywords or None,
            enriched_prerequisites=prerequisites or None,
            prompt_version=PROMPT_VERSION,
        )
        db.add(blk); db.flush()
    else:
        blk.raw_text = raw_text; blk.content_hash = ch; blk.subtopic_id = subtopic_id
        if summary:       blk.enriched_summary      = summary
        if keywords:      blk.enriched_keywords      = keywords
        if prerequisites: blk.enriched_prerequisites = prerequisites
        db.flush()  # ensure blk.id is committed before embedding upsert
    if vec is not None:
        # Inline the vector literal to avoid SQLAlchemy text() parser conflict
        # with :param_name::vector (it can't distinguish param-name from cast).
        # Safe: vec is a machine-generated list of floats — no user input.
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

def _embed(text_input):
    client = get_openai()
    resp = client.embeddings.create(input=text_input[:8000], model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT)
    return resp.data[0].embedding

def _extract_topic_number(sec_key):
    parts = sec_key.split(":", 1)
    if len(parts) < 2:
        return None
    m = _TOPIC_RE.match(parts[1].strip())
    if m:
        return f"{m.group(1)}.{m.group(2)}" + (f".{m.group(3)}" if m.group(3) else "")
    return None

def _classify_level(paddlex_heading):
    m = _TOPIC_RE.match(paddlex_heading)
    return 2 if (m and m.group(3)) else 1

def run(args):
    with open(args.json_path, encoding="utf-8") as f:
        llm_output_data = json.load(f)
    logger.info(f"Loaded {len(llm_output_data)} sections from {args.json_path}")

    structured_topics = []
    for sec_key, entry in llm_output_data.items():
        sections = entry.get("llm_data", {}).get("sections", [])
        if not sections:
            logger.warning(f"No LLM sections for key '{sec_key}' — skipping.")
            continue
        paddlex_heading = sec_key.split(":", 1)[-1].strip()
        for llm_sec in sections:
            structured_topics.append((sec_key, paddlex_heading, llm_sec))

    seen_titles = set()
    deduped = []
    for item in structured_topics:
        sec_key, paddlex_heading, td = item
        title = (td.get("heading") or args.chapter).strip()
        if title not in seen_titles:
            seen_titles.add(title)
            deduped.append(item)
        else:
            logger.warning(f"Duplicate title '{title}' — skipping.")
    structured_topics = deduped
    logger.info(f"Total unique topics to insert: {len(structured_topics)}")

    # chap_nk is deterministic from CLI args — compute outside the session so
    # it is available both here (for _get_or_create_chapter) and later in the
    # main loop (for _upsert_topic).  Format must match ingestion_pipeline.py.
    chap_nk = f"{args.book_key}_ch{args.chapter_num}"

    with managed_session() as db:
        board_obj   = _get_or_create_board(db, args.board)
        class_obj   = _get_or_create_class(db, board_obj.id, args.class_num)
        subject_obj = _get_or_create_subject(db, class_obj.id, args.subject)
        book_obj    = _get_or_create_book(db, subject_obj.id, args.book_title, args.book_key)
        chapter_obj = _get_or_create_chapter(db, book_obj.id, args.chapter, args.chapter_num, chap_nk)
        chapter_id  = chapter_obj.id
    logger.info(f"Chapter resolved: id={chapter_id}, nk='{chap_nk}', title='{args.chapter}'")

    # Pre-compute embeddings OUTSIDE DB session to avoid rollback on OpenAI timeout
    embeddings = []
    for sec_key, paddlex_heading, td in structured_topics:
        if td.get("content_type", "concept") == "activity":
            embeddings.append(None); continue
        repaired_text = (td.get("repaired_text") or "").strip()
        if not repaired_text:
            embeddings.append(None); continue
        embed_input = (td.get("summary") or "").strip() or repaired_text
        try:
            embeddings.append(_embed(embed_input))
        except Exception as e:
            logger.warning(f"Embedding failed for '{td.get('heading')}': {e}")
            embeddings.append(None)

    total_blocks = 0; skipped = 0; seen_hashes: set = set()

    with managed_session() as db:
        last_concept_topic = None
        for order, ((sec_key, paddlex_heading, td), vec) in enumerate(zip(structured_topics, embeddings)):
            topic_title    = (td.get("heading") or args.chapter).strip()
            content_type   = td.get("content_type", "concept")
            topic_summary  = (td.get("summary") or "").strip()
            topic_prereqs  = td.get("prerequisites", [])
            topic_keywords = td.get("keywords", [])
            repaired_text  = (td.get("repaired_text") or "").strip()
            topic_number   = _extract_topic_number(sec_key)
            level          = _classify_level(paddlex_heading)

            subtopic_obj = None
            if level == 2 and last_concept_topic:
                subtopic_obj = _upsert_subtopic(db, last_concept_topic.id, paddlex_heading, order)
                topic_obj    = last_concept_topic
            else:
                topic_obj = _upsert_topic(
                    db, chapter_id, chap_nk, topic_title, order,
                    topic_number=topic_number,
                )
                topic_obj.summary          = topic_summary
                topic_obj.content_type     = content_type
                topic_obj.difficulty_level = td.get("difficulty_level")
                if content_type != "activity":
                    last_concept_topic = topic_obj

            if content_type == "activity":
                parent_id = last_concept_topic.id if last_concept_topic else topic_obj.id
                db.add(Activity(
                    topic_id=parent_id, title=topic_title, content=repaired_text,
                    summary=topic_summary, keywords=topic_keywords,
                    difficulty_level=td.get("difficulty_level"),
                ))
                continue

            for prereq in topic_prereqs:
                _upsert_topic_prerequisite(db, topic_obj.id, prereq)

            if not repaired_text:
                logger.warning(f"Empty repaired_text for '{topic_title}' — skipped.")
                skipped += 1; continue

            content_hash = hashlib.md5(repaired_text.strip().lower().encode()).hexdigest()
            if content_hash in seen_hashes:
                logger.debug(f"Duplicate content for '{topic_title}' — skipped.")
                continue
            seen_hashes.add(content_hash)

            blk_row = _upsert_block(
                db, topic_obj.id, raw_text=repaired_text, block_index=order,
                subtopic_id=subtopic_obj.id if subtopic_obj else None,
                block_type=content_type, summary=topic_summary,
                keywords=topic_keywords, prerequisites=topic_prereqs, vec=vec,
            )
            total_blocks += 1

            if blk_row and not db.query(ContentRawArchive).filter(ContentRawArchive.block_id == blk_row.id).first():
                raw_ocr = "\n\n".join(llm_output_data.get(sec_key, {}).get("raw_blocks", []))
                db.add(ContentRawArchive(block_id=blk_row.id, raw_text=raw_ocr, repaired_text=repaired_text))

    logger.info(f"DB write complete: {total_blocks} blocks stored, {skipped} skipped.")

    # Chapter-level LLM summarization (cheap — only uses topic summaries)
    topic_summaries = [td.get("summary", "").strip() for _, _, td in structured_topics if td.get("summary", "").strip()]
    if topic_summaries:
        try:
            client = get_openai()
            joined = "\n".join(f"- {s}" for s in topic_summaries)
            chap_prompt = (
                f"You are summarising a textbook chapter titled '{args.chapter}'.\n"
                f"Below are summaries of each section in the chapter:\n{joined}\n\n"
                "Return ONLY valid JSON with these three keys:\n"
                '{"summary": "3-4 declarative sentences covering the whole chapter", '
                '"learning_objectives": ["objective 1", "objective 2", ...], '
                '"key_concepts": ["concept 1", "concept 2", ...]}'
            )
            resp = client.chat.completions.create(
                model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": "You are a curriculum summariser. Output only JSON."},
                    {"role": "user",   "content": chap_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            chap_data = json.loads(resp.choices[0].message.content)
            with managed_session() as db:
                chap_row = db.query(Chapter).filter(Chapter.id == chapter_id).first()
                if chap_row:
                    chap_row.summary             = chap_data.get("summary", "")
                    chap_row.learning_objectives = json.dumps(chap_data.get("learning_objectives", []))
                    chap_row.key_concepts        = json.dumps(chap_data.get("key_concepts", []))
                    chap_row.prompt_version      = PROMPT_VERSION
            logger.info(f"Chapter summary written for chapter_id={chapter_id}.")
        except Exception as e:
            logger.warning(f"Chapter summarization failed (non-fatal): {e}")

    return {"chapter_id": chapter_id, "blocks_stored": total_blocks, "skipped": skipped,
            "status": "complete" if skipped == 0 else "partial"}


def main():
    parser = argparse.ArgumentParser(description="Insert a pre-generated ingestion JSON into VishwAlpha DB.")
    parser.add_argument("json_path")
    parser.add_argument("--board",       default="NCERT")
    parser.add_argument("--class",       dest="class_num", type=int, required=True)
    parser.add_argument("--subject",     required=True)
    parser.add_argument("--book-title",  required=True)
    parser.add_argument("--book-key",    required=True)
    parser.add_argument("--chapter",     required=True)
    parser.add_argument("--chapter-num", dest="chapter_num", type=int, required=True)
    parser.add_argument("--log-file",    action="store_true")
    args = parser.parse_args()

    if args.log_file:
        import os; from datetime import datetime
        os.makedirs("logs", exist_ok=True)
        log_fn = os.path.join("logs", f"json_to_db_{datetime.now().strftime('%Y%m%d')}.log")
        root = logging.getLogger()
        for h in root.handlers[:]: root.removeHandler(h)
        fh = logging.FileHandler(log_fn, mode="a", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        root.addHandler(fh)
        print(f"Logging redirected to {log_fn}")

    try:
        result = run(args)
        print(f"\n[SUCCESS] JSON-to-DB complete!")
        print(f"   Chapter ID    : {result['chapter_id']}")
        print(f"   Blocks stored : {result['blocks_stored']}")
        print(f"   Skipped       : {result['skipped']}")
        print(f"   Status        : {result['status']}")
    except FileNotFoundError as e:
        print(f"\n[ERROR] File not found: {e}", file=sys.stderr); sys.exit(1)
    except Exception as e:
        import traceback
        print(f"\n[ERROR] {e}", file=sys.stderr); traceback.print_exc(); sys.exit(1)

if __name__ == "__main__":
    main()
