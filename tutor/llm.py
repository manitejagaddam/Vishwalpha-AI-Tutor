"""
tutor/llm.py
────────────
The generation layer — sends retrieved context + conversation history to the
LLM and produces a personalised tutoring response.

Design decisions for cost/latency:
  - Reuses a single Groq client instance (no reconnection overhead)
  - System prompt is compact but comprehensive (~300 tokens)
  - Uses temperature=0.4 for a balance of accuracy and naturalness
  - max_tokens capped to prevent run-away generation costs
"""

import os
import logging
from groq import Groq
from schemas import ChatMessage

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# System Prompt
# ─────────────────────────────────────────────────────────────────────────────

TUTOR_SYSTEM_PROMPT = """You are VishwAlpha, a warm, knowledgeable AI tutor for Indian school students (NCERT curriculum).

TEACHING STYLE — adapt to what the student needs:

1. **Direct Explanation**: Start with a clear, structured answer. Use bullet points and numbered steps for processes.
2. **Socratic Guidance**: When a student is exploring or confused, ask 1-2 guiding questions to lead them to the answer before revealing it.
3. **Analogy & Examples**: Use real-world analogies and examples familiar to Indian students (everyday objects, Indian context) to make abstract concepts concrete.
4. **Step-by-Step Breakdown**: For numerical problems or multi-step processes, walk through each step clearly.
5. **Encouraging Tone**: Be patient and encouraging. Acknowledge what the student already knows. Never make them feel stupid.

RULES:
- Answer ONLY using the provided TEXTBOOK CONTEXT below. If the context does not cover the question, say: "This topic isn't covered in the materials I have right now. Could you ask about something from your textbook chapters?"
- NEVER fabricate facts, equations, or definitions not present in the context.
- Keep language simple and appropriate for the student's class level.
- Use clear formatting: headers, bullet points, bold for key terms.
- If the student asks a follow-up, reference what was discussed earlier in the conversation.
- Keep answers concise but complete — aim for quality over length."""


class TutorLLM:
    """
    Generates personalised tutoring answers using Groq LLM.

    Usage:
        tutor = TutorLLM()
        answer = tutor.generate(question, context, history, memory_summary)
    """

    def __init__(self):
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            logger.warning("GROQ_API_KEY not set — LLM calls will fail.")
        self.client = Groq(api_key=api_key)
        self.model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

    def generate(
        self,
        question: str,
        context: str,
        history: list[ChatMessage] | None = None,
        memory_summary: str = "",
    ) -> str:
        """
        Builds the prompt and generates a tutoring answer.

        Args:
            question       : The student's current question.
            context        : Retrieved + compressed curriculum context from Qdrant.
            history        : Recent conversation messages (last 2 turns, verbatim).
            memory_summary : Compressed summary of older conversation turns.

        Returns:
            The tutor's answer as a string.
        """
        messages = self._build_messages(question, context, history, memory_summary)

        try:
            response = self.client.chat.completions.create(
                messages=messages,
                model=self.model,
                temperature=0.4,
                max_tokens=1024,
            )
            answer = response.choices[0].message.content.strip()
            logger.info(
                f"Generated answer: {len(answer)} chars, "
                f"tokens used: {response.usage.total_tokens}"
            )
            return answer

        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return (
                "I'm sorry, I'm having trouble generating a response right now. "
                "Please try again in a moment."
            )

    def _build_messages(
        self,
        question: str,
        context: str,
        history: list[ChatMessage] | None,
        memory_summary: str,
    ) -> list[dict]:
        """
        Constructs the chat messages array for the Groq API.

        Structure:
          1. System prompt (tutor personality + rules)
          2. System note with textbook context
          3. (Optional) Compressed memory of older turns
          4. Recent conversation history (last 2 turns, verbatim)
          5. Current student question
        """
        msgs: list[dict] = []

        # 1. System prompt
        msgs.append({"role": "system", "content": TUTOR_SYSTEM_PROMPT})

        # 2. Textbook context as a system-level injection
        if context:
            msgs.append({
                "role": "system",
                "content": (
                    "TEXTBOOK CONTEXT (use this to answer the student's question):\n\n"
                    f"{context}"
                ),
            })

        # 3. Compressed memory of older conversation turns
        if memory_summary:
            msgs.append({
                "role": "system",
                "content": (
                    "CONVERSATION MEMORY (summary of earlier discussion):\n"
                    f"{memory_summary}"
                ),
            })

        # 4. Recent history — last 2 turn pairs, sent verbatim
        if history:
            for msg in history:
                role = "user" if msg.role == "student" else "assistant"
                msgs.append({"role": role, "content": msg.content})

        # 5. Current question
        msgs.append({"role": "user", "content": question})

        return msgs
