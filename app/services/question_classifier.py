"""
app/services/question_classifier.py
────────────────────────────────────
Heuristic question classifier — determines if a student message is
'conversational' (skip pgvector) or 'curriculum' (needs RAG retrieval).

Also contains understanding and give-up detectors for Socratic mode.
All operations are zero-LLM / pure-regex for maximum speed.

Renamed from: tutor/patterns.py
"""
import re

# ── Conversational patterns ───────────────────────────────────────────────────

_CONVERSATIONAL_PATTERNS = [
    r"^(hi|hello|hey|greetings|good morning|good afternoon|good evening|bye|goodbye|see ya|see you)[\s.!]*$",
    r"^(thanks|thank you|thx|tysm|appreciate it)[\s.!]*$",
    r"^(yes|no|ok|okay|sure|yep|nope|got it|makes sense|i see|alright|fine|cool|indeed)[\s.!]*$",
    r"^(correct|wrong|true|false|exactly|absolutely)[\s.!]*$",
    r"^(what did we discuss|what did we talk about|what was the last thing|recap the last part|what did you say)[\s.!]*$",
    r"^(can we (do a quiz|start a quiz|do a test|practice|start|stop|continue|pause|resume|reset))[\s.!]*$",
    r"^(give me a (quiz|test|question|summary|recap))[\s.!]*$",
    r"^(what is the plan|what should we do next|what's next)[\s.!]*$",
    r"^(can you (explain that again|repeat that|say that again|rephrase that|explain in more detail))[\s.!]*$",
    r"^(i (don't understand|do not understand|get it|don't get it|understand))[\s.!]*$",
]

_CONVERSATIONAL_KEYWORDS = {
    "yes", "no", "ok", "okay", "sure", "yep", "nope", "thanks", "thank you",
    "hi", "hello", "hey", "correct", "wrong", "got it", "i see", "understood",
    "makes sense", "bye", "goodbye", "help", "next", "continue", "reset", "clear",
}

# Academic question keywords (prevent false-positive on short questions)
_ACADEMIC_KEYWORDS = {
    "what", "why", "how", "define", "acid", "base", "salt", "metal",
    "reaction", "ph", "formula", "atom", "molecule", "force", "energy",
    "light", "heat", "wave", "current", "voltage", "cell", "nucleus",
}

_CONFUSION_MARKERS = re.compile(
    r"\b(i don'?t know|not sure|no idea|what is|idk|confused|"
    r"i forget|i forgot|not clear|unclear|just tell me|just give me)\b",
    re.IGNORECASE,
)

_STRUCTURAL_COHERENCE = re.compile(
    r"\b(because|therefore|which means|this causes|as a result|"
    r"leads to|is defined as|refers to|consists of)\b",
    re.IGNORECASE,
)

_GIVE_UP_PATTERN = re.compile(
    r"\b(skip|don'?t care|forget it|never mind|just (tell|give) me|"
    r"move on|i give up|next topic|doesn'?t matter)\b",
    re.IGNORECASE,
)


def is_conversational(question: str) -> bool:
    """
    Returns True if the message is conversational (skip RAG retrieval).
    Returns False if it's an academic question requiring pgvector retrieval.
    """
    text = question.strip().lower()

    # Very short messages: likely conversational
    if len(text) < 15:
        if "?" in text and any(kw in text for kw in _ACADEMIC_KEYWORDS):
            return False
        return True

    # Exact keyword match
    cleaned = re.sub(r"[^\w\s]", "", text).strip()
    if cleaned in _CONVERSATIONAL_KEYWORDS:
        return True

    # Pattern match
    for pattern in _CONVERSATIONAL_PATTERNS:
        if re.search(pattern, text):
            return True

    return False


def detect_understanding(
    student_response: str, expected_keywords: list[str]
) -> float:
    """
    Returns 0.0–1.0 understanding score. Zero LLM calls.

    Weights:
      40% — keyword overlap
      20% — response length
      20% — absence of confusion markers
      20% — structural coherence
    """
    if not student_response or not student_response.strip():
        return 0.0

    text_lower = student_response.lower()
    words = text_lower.split()
    n_words = len(words)

    # Keyword overlap (40%)
    if expected_keywords:
        matched = sum(1 for kw in expected_keywords if kw.lower() in text_lower)
        keyword_score = matched / len(expected_keywords)
    else:
        keyword_score = 0.5

    # Length (20%)
    if n_words >= 30:      length_score = 1.0
    elif n_words >= 15:    length_score = 0.6
    elif n_words >= 5:     length_score = 0.3
    else:                  length_score = 0.0

    # No confusion (20%)
    hits = len(_CONFUSION_MARKERS.findall(student_response))
    no_confusion_score = max(0.0, 1.0 - hits * 0.5)

    # Structural coherence (20%)
    coherence_hits = len(_STRUCTURAL_COHERENCE.findall(student_response))
    coherence_score = min(1.0, coherence_hits * 0.4)

    return round(
        keyword_score * 0.40
        + length_score * 0.20
        + no_confusion_score * 0.20
        + coherence_score * 0.20,
        3,
    )


def detect_give_up(student_response: str) -> bool:
    """
    Detects if the student explicitly gives up.
    Triggers 'adaptive skip': reveal full answer with consolidation nudge.
    """
    return bool(_GIVE_UP_PATTERN.search(student_response))
