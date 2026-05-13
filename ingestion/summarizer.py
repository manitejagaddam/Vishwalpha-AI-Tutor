import os
import json
import time
import logging
from groq import Groq

logger = logging.getLogger(__name__)

# Rate limit config for Groq free tier
RATE_LIMIT_SLEEP = 3  # seconds between LLM calls
MAX_RETRIES = 3
RETRY_SLEEP = 15  # seconds on 429 error

class Summarizer:
    """
    LLM-powered summarization for topic-level summaries.
    
    Design for Groq free tier (30 RPM, 6000 TPM):
    - Adds mandatory sleep between calls to stay under rate limits
    - Retries on 429 with exponential backoff
    - Does NOT polish individual chunks (too many API calls)
    - Chunks are cleaned deterministically by TextCleaner instead
    """
    
    def __init__(self):
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            logger.warning("GROQ_API_KEY not found in environment.")
        self.client = Groq(api_key=api_key)
        self.model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
    
    def summarize_topic(self, topic_title: str, text: str) -> dict:
        """
        Generates a concise summary and keywords for a topic.
        Returns: {"summary": "...", "keywords": ["...", "..."]}
        """
        # Truncate to stay under token limits (~4 chars per token, aim for <4000 tokens total)
        text_sample = text[:6000]
        
        prompt = f"""You are an expert AI tutor. Summarize this educational topic for a student.

Topic: {topic_title}

Content:
{text_sample}

Return ONLY valid JSON:
{{
  "summary": "A concise 2-3 sentence summary covering the key concepts.",
  "keywords": ["keyword1", "keyword2", "keyword3"]
}}"""

        time.sleep(RATE_LIMIT_SLEEP)  # Mandatory rate limit pause
        
        for attempt in range(MAX_RETRIES):
            try:
                chat_completion = self.client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=self.model,
                    temperature=0.2,
                    max_tokens=500,
                    response_format={"type": "json_object"}
                )
                result = json.loads(chat_completion.choices[0].message.content.strip())
                logger.info(f"Summarized topic: {topic_title}")
                return result
            except Exception as e:
                if "429" in str(e) or "Too Many Requests" in str(e) or "rate_limit" in str(e):
                    wait_time = RETRY_SLEEP * (attempt + 1)
                    logger.warning(f"Rate limit hit. Sleeping {wait_time}s... (attempt {attempt+1}/{MAX_RETRIES})")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Error summarizing '{topic_title}': {e}")
                    break
        
        return {"summary": "Summary unavailable.", "keywords": []}
