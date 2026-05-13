import os
import json
import logging
from groq import Groq

logger = logging.getLogger(__name__)

class LLMStructureRepair:
    """
    Validates and cleans the deterministically-detected topic structure.
    
    New role: receives the already-detected list of topics and asks the LLM
    to verify/correct them. This uses far fewer tokens than the old approach
    of sending the entire raw text.
    """
    
    def __init__(self):
        api_key = os.environ.get("GROQ_API_KEY")
        self.client = Groq(api_key=api_key)
        self.model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

    def validate_structure(self, detected_topics: list[str], raw_text_sample: str) -> dict:
        """
        Validates the deterministically-detected topics against a sample of raw text.
        Returns a cleaned structure with the chapter title and corrected topic names.
        """
        topics_str = "\n".join(f"  - {t}" for t in detected_topics)
        
        prompt = f"""You are an expert on NCERT textbooks. I have automatically detected the following section headings from a chapter PDF:

{topics_str}

And here is a sample of the chapter text to help you identify the chapter title:

{raw_text_sample[:3000]}

Please return a JSON object with:
1. "chapter": The full, correct chapter title
2. "topics": The corrected list of topic titles (fix any OCR errors in the titles I detected, keep the section numbers)

Return ONLY valid JSON. Keep it short — just the titles.
{{
  "chapter": "Chapter Title",
  "topics": ["1.1 Topic Name", "1.2 Topic Name"]
}}"""

        try:
            chat_completion = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.1,
                max_tokens=1000,
                response_format={"type": "json_object"}
            )
            content = chat_completion.choices[0].message.content
            result = json.loads(content)
            logger.info(f"LLM validated structure: chapter='{result.get('chapter')}', {len(result.get('topics', []))} topics")
            return result
        except Exception as e:
            logger.error(f"LLM validation failed (non-critical): {e}")
            # Return the detected topics as-is — they are already good enough
            return {
                "chapter": "Unknown Chapter",
                "topics": detected_topics
            }

    # Keep backward compatibility
    def repair_structure(self, extracted_text: str) -> dict:
        """Legacy method — kept for backward compatibility."""
        return self.validate_structure([], extracted_text)
