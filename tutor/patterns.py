"""
tutor/patterns.py
─────────────────
Conversational patterns and heuristics for the chat orchestrator.
"""

import re

# List of regex patterns for conversational inputs that should skip pgvector retrieval
CONVERSATIONAL_PATTERNS = [
    # Greetings / Farewells / Politeness
    r"^(hi|hello|hey|greetings|good morning|good afternoon|good evening|bye|goodbye|see ya|see you)[\s.!]*$",
    r"^(thanks|thank you|thx|tysm|appreciate it)[\s.!]*$",
    # Acknowledgements / short replies
    r"^(yes|no|ok|okay|sure|yep|nope|got it|makes sense|i see|alright|fine|cool|indeed)[\s.!]*$",
    r"^(correct|wrong|true|false|exactly|absolutely)[\s.!]*$",
    # Meta questions / navigation
    r"^(what did we discuss|what did we talk about|what was the last thing|recap the last part|what did you say)[\s.!]*$",
    r"^(can we (do a quiz|start a quiz|do a test|practice|start|stop|continue|pause|resume|reset))[\s.!]*$",
    r"^(give me a (quiz|test|question|summary|recap))[\s.!]*$",
    r"^(what is the plan|what should we do next|what's next)[\s.!]*$",
    # Clarifications & feedback
    r"^(can you (explain that again|repeat that|say that again|rephrase that|explain in more detail))[\s.!]*$",
    r"^(i (don't understand|do not understand|get it|don't get it|understand))[\s.!]*$",
]

# Set of specific single words or short phrases that are definitely conversational
CONVERSATIONAL_KEYWORDS = {
    "yes", "no", "ok", "okay", "sure", "yep", "nope", "thanks", "thank you", "hi", "hello",
    "hey", "correct", "wrong", "got it", "i see", "undestood", "understood", "makes sense",
    "bye", "goodbye", "help", "next", "continue", "reset", "clear"
}

def heuristic_is_conversational(question: str) -> bool:
    """
    Algorithmic heuristic to identify conversational messages.
    Returns True if the message is conversational (skips pgvector RAG),
    False if it requires pgvector textbook retrieval.
    """
    clean_question = question.strip().lower()
    
    # 1. Very short messages are almost always conversational (e.g. "ok", "why?", "yes")
    if len(clean_question) < 15:
        # If it contains "?" and is at least 8 chars, it could be a very short question like "What is pH?"
        if "?" in clean_question:
            # Check if it has textbook keywords to avoid false positives
            keywords = ["what", "why", "how", "define", "acid", "base", "salt", "metal", "reaction", "ph", "formula", "atom", "molecule"]
            if any(kw in clean_question for kw in keywords):
                return False
        return True
        
    # 2. Check exact matches in our common keyword set (removing punctuation)
    cleaned_words = re.sub(r"[^\w\s]", "", clean_question).strip()
    if cleaned_words in CONVERSATIONAL_KEYWORDS:
        return True
        
    # 3. Check regular expression patterns
    for pattern in CONVERSATIONAL_PATTERNS:
        if re.search(pattern, clean_question):
            return True
            
    return False
