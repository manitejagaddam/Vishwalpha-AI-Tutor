# summarizer.py
#
# NOTE: Summarization is now handled inside LLMStructureRepair.repair_section().
# The LLM produces the heading, repaired text, summary, and keywords in a single
# call per section, reducing total API usage significantly.
#
# This file is kept as a placeholder to avoid breaking any existing imports.
# It can be safely deleted once you confirm no other code references it.

import logging
logger = logging.getLogger(__name__)

class Summarizer:
    """Deprecated — see ingestion/llm_repair.py → LLMStructureRepair.repair_section()."""
    def summarize_topic(self, topic_title: str, text: str):
        logger.warning(
            "Summarizer.summarize_topic() is deprecated. "
            "Use LLMStructureRepair.repair_section() instead."
        )
        raise DeprecationWarning(
            "Summarizer is deprecated. Use LLMStructureRepair.repair_section()."
        )
