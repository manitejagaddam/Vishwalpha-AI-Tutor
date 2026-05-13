import os
import time
import logging
from groq import Groq
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Rate limit config for Groq free tier
RATE_LIMIT_SLEEP = 3   # seconds between LLM calls
MAX_RETRIES = 3
RETRY_SLEEP = 15       # seconds on 429 error


class RepairedSection(BaseModel):
    """
    Output from the LLM for a single section of content.
    - heading:       A clean, accurate heading for this section.
    - repaired_text: The full repaired and cleaned content of this section.
    - summary:       A 2-3 sentence summary (used for routing embeddings).
    - keywords:      Key terms extracted from the section.
    """
    heading: str
    repaired_text: str
    summary: str
    keywords: list[str] = Field(default_factory=list)


class LLMStructureRepair:
    """
    Sends each raw content section to an LLM which:
      1. Repairs OCR noise, broken sentences, and garbled text.
      2. Generates an accurate, descriptive heading for the section.
      3. Produces a concise summary suitable for semantic routing.

    This replaces the old approach of validating a list of detected headings.
    The LLM now acts on actual content, not just title strings, giving it full
    context to produce accurate headings and clean text.
    """

    def __init__(self):
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            logger.warning("GROQ_API_KEY not found in environment.")
        self.client = Groq(api_key=api_key)
        self.model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

    def repair_section(self, raw_content: str, section_hint: str = "") -> RepairedSection:
        """
        Sends a single raw content section to the LLM for repair and heading generation.

        Args:
            raw_content:   The raw extracted text of the section (may contain OCR noise).
            section_hint:  An optional preliminary heading detected deterministically
                           (e.g., "1.1 CHEMICAL EQUA AL TIONS"). The LLM uses this
                           as a hint but should derive the real heading from the content.

        Returns:
            RepairedSection with heading, repaired_text, summary, and keywords.
        """
        # Truncate to stay within token budget (~4 chars per token, keep under 3000 tokens)
        content_sample = raw_content[:5000]

        hint_line = (
            f"\nDetected section hint (may have OCR errors, use as reference only): \"{section_hint}\""
            if section_hint else ""
        )

        prompt = f"""You are an expert AI educational content editor specializing in NCERT textbooks.

I will give you a raw chunk of text extracted from a PDF textbook. The text may contain:
- OCR errors (broken words, garbled characters, duplicated fragments)
- Broken sentences split across lines
- Page numbers or footer noise
- Formatting artifacts
{hint_line}

Your tasks:
1. REPAIR the text — fix all OCR errors, re-join broken words/sentences, remove noise.
2. GENERATE a precise, descriptive heading that accurately reflects what this specific content is about. The heading should read like a textbook section title (e.g., "Types of Chemical Reactions", "Photosynthesis and Chlorophyll").
3. SUMMARIZE the repaired content in 2-3 clear sentences for a student.
4. EXTRACT 3-5 key educational terms from the content.

Raw content:
\"\"\"
{content_sample}
\"\"\"

Return ONLY valid JSON matching this exact structure:
{{
  "heading": "Your generated section heading here",
  "repaired_text": "The fully repaired and cleaned content here",
  "summary": "A 2-3 sentence summary of the content",
  "keywords": ["keyword1", "keyword2", "keyword3"]
}}"""

        time.sleep(RATE_LIMIT_SLEEP)  # Mandatory rate limit pause

        for attempt in range(MAX_RETRIES):
            try:
                chat_completion = self.client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=self.model,
                    temperature=0.2,
                    max_tokens=1500,
                    response_format={"type": "json_object"}
                )
                content = chat_completion.choices[0].message.content.strip()
                result = RepairedSection.model_validate_json(content)
                logger.info(f"  ✓ LLM repaired section → heading: \"{result.heading}\"")
                return result

            except Exception as e:
                if "429" in str(e) or "Too Many Requests" in str(e) or "rate_limit" in str(e):
                    wait_time = RETRY_SLEEP * (attempt + 1)
                    logger.warning(
                        f"Rate limit hit. Sleeping {wait_time}s... "
                        f"(attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"LLM repair failed for section \"{section_hint}\": {e}")
                    break

        # Fallback: return content as-is with a generic heading
        logger.warning(f"LLM repair failed after {MAX_RETRIES} attempts. Using raw content.")
        return RepairedSection(
            heading=section_hint if section_hint else "Untitled Section",
            repaired_text=raw_content,
            summary="Summary unavailable.",
            keywords=[]
        )
