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


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2.2 — Algorithmic understanding detection (zero LLM)
# ─────────────────────────────────────────────────────────────────────────────

_CONFUSION_MARKERS = re.compile(
    r"\b(i don'?t know|not sure|no idea|what is|idk|confused|"
    r"i forget|i forgot|not clear|unclear|just tell me|just give me)\b",
    re.IGNORECASE
)

_STRUCTURAL_COHERENCE = re.compile(
    r"\b(because|therefore|which means|this causes|as a result|"
    r"leads to|is defined as|refers to|consists of)\b",
    re.IGNORECASE
)

_GIVE_UP_PATTERN = re.compile(
    r"\b(skip|don'?t care|forget it|never mind|just (tell|give) me|"
    r"move on|i give up|next topic|doesn'?t matter)\b",
    re.IGNORECASE
)


def detect_understanding(student_response: str, expected_keywords: list[str]) -> float:
    """
    Returns 0.0–1.0 understanding score. Purely algorithmic — zero LLM calls.

    Weights:
      40% — keyword overlap with expected concepts
      20% — response length and specificity
      20% — absence of confusion markers
      20% — structural coherence (cause-effect, definition patterns)

    Edge case — empty response: returns 0.0.
    Edge case — no expected keywords: keyword score defaults to 0.5.
    """
    if not student_response or not student_response.strip():
        return 0.0

    response_lower = student_response.lower()
    words = response_lower.split()
    n_words = len(words)

    # 1. Keyword overlap (40%)
    if expected_keywords:
        matched = sum(1 for kw in expected_keywords if kw.lower() in response_lower)
        keyword_score = matched / len(expected_keywords)
    else:
        keyword_score = 0.5  # no keywords to check → neutral

    # 2. Length/specificity (20%)
    if n_words >= 30:   length_score = 1.0
    elif n_words >= 15: length_score = 0.6
    elif n_words >= 5:  length_score = 0.3
    else:               length_score = 0.0

    # 3. Absence of confusion markers (20%)
    confusion_hits = len(_CONFUSION_MARKERS.findall(student_response))
    confusion_score = max(0.0, 1.0 - confusion_hits * 0.5)

    # 4. Structural coherence (20%)
    coherence_hits = len(_STRUCTURAL_COHERENCE.findall(student_response))
    coherence_score = min(1.0, coherence_hits * 0.4)

    score = (
        keyword_score   * 0.40
        + length_score  * 0.20
        + confusion_score * 0.20
        + coherence_score * 0.20
    )
    return round(score, 3)


def detect_give_up(student_response: str) -> bool:
    """
    Detects if the student explicitly gives up or requests to skip.
    Triggers 'adaptive skip': give the full answer with a consolidation nudge
    rather than forcing repeated backtracking.
    """
    return bool(_GIVE_UP_PATTERN.search(student_response))
