"""
app/services/ingestion_pipeline.py
───────────────────────────────────
Unified ingestion pipeline: PDF → Parse → Structure → Repair → Summarize → Store.

Replaces the 6 fragmented files in the old ingestion/ folder.
Uses pure pgvector for both CurriculumRouting (semantic routing) and CurriculumContent (RAG).
"""
import os
import json
import logging
from PyPDF2 import PdfReader

from app.infra.groq_client import get_groq
from app.infra.vector_router import VectorRouter
from app.services.retrieval_service import upsert_chunk
from app.schemas import CanonicalCurriculum, ProcessedSection

logger = logging.getLogger(__name__)


class IngestionPipeline:
    def __init__(self):
        self.llm = get_groq()
        self.router = VectorRouter()

    def process_pdf(
        self, pdf_path: str, class_num: int, subject: str, chapter: str
    ) -> dict:
        """
        Main entry point for the pipeline.
        1. Parse PDF to raw text
        2. Chunk text and use LLM to structure/repair/summarise it
        3. Upsert semantic routing vectors (Topic → summary)
        4. Upsert retrieval vectors (Chunk → full text)
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        logger.info(f"Starting ingestion: {pdf_path}")
        raw_text = self._extract_text(pdf_path)
        logger.info(f"Extracted {len(raw_text)} chars from PDF.")

        # In a real production system, this chunking would be more robust.
        # Here we split into rough chunks of 4000 characters to feed the LLM.
        raw_chunks = [raw_text[i : i + 4000] for i in range(0, len(raw_text), 4000)]
        
        total_sections = 0
        for i, chunk in enumerate(raw_chunks):
            logger.info(f"Processing chunk {i+1}/{len(raw_chunks)}...")
            structured = self._structure_and_repair(chunk, chapter)
            if not structured:
                continue

            for section in structured.get("sections", []):
                topic = section.get("heading", "General")
                summary = section.get("summary", "")
                repaired_text = section.get("repaired_text", "")

                if not summary or not repaired_text:
                    continue

                # 1. Upsert routing vector (topic summary)
                self.router.upsert_topic(
                    class_num=class_num,
                    subject=subject,
                    chapter=chapter,
                    topic=topic,
                    summary=summary,
                )

                # 2. Upsert retrieval vector (repaired content)
                metadata = {
                    "class": class_num,
                    "subject": subject,
                    "chapter": chapter,
                    "topic": topic,
                }
                upsert_chunk(metadata, repaired_text)
                total_sections += 1

        logger.info(f"Ingestion complete: {total_sections} sections stored.")
        
        # Invalidate the cache for this subject/class
        from app.infra.redis_cache import RetrievalCache
        try:
            RetrievalCache().invalidate_chapter(class_num, subject)
        except Exception as e:
            logger.warning(f"Cache invalidation failed: {e}")

        return {
            "status": "success",
            "sections_ingested": total_sections,
            "message": f"Successfully ingested {pdf_path}",
        }

    def _extract_text(self, pdf_path: str) -> str:
        """Extracts raw text from a PDF file."""
        try:
            reader = PdfReader(pdf_path)
            text = []
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text.append(extracted)
            return "\n\n".join(text)
        except Exception as exc:
            logger.error(f"Failed to read PDF {pdf_path}: {exc}")
            raise

    def _structure_and_repair(self, text: str, chapter: str) -> dict | None:
        """
        Uses Llama 3.3 (or 3.1) to clean OCR errors, structure into topics,
        and generate summaries for each topic. Returns JSON.
        """
        prompt = f"""You are a textbook ingestion pipeline.
I will give you a raw text chunk extracted from a PDF via OCR. The chapter is '{chapter}'.
Your task is to fix OCR errors, split the text into logical sub-topics (sections), and generate a summary for each.

Output EXACTLY a JSON object matching this schema:
{{
  "sections": [
    {{
      "heading": "String - the topic title",
      "repaired_text": "String - the clean, unbroken text of this section",
      "summary": "String - a dense 2-3 sentence summary of the core concepts in this section"
    }}
  ]
}}

Raw text to process:
{text}
"""
        try:
            response = self.llm.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant",  # using instant for fast structuring
                temperature=0.1,
                max_tokens=4000,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content.strip()
            return json.loads(raw)
        except Exception as exc:
            logger.error(f"LLM structuring failed: {exc}")
            return None
