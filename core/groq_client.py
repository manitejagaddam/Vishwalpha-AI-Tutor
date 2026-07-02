"""
core/groq_client.py
───────────────────
Provides a shared singleton instance of the Groq client.
"""

import os
from groq import Groq

_groq_client: Groq | None = None

def get_groq() -> Groq:
    """
    Returns a singleton instance of the Groq client.
    Initializes the client on the first call using GROQ_API_KEY from the environment.
    """
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    return _groq_client
