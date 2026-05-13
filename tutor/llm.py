"""
tutor/llm.py
────────────
The generation layer — mode-aware, strictly grounded.

Two operating modes controlled by the chat orchestrator:
  "curriculum"     — Context is injected. System prompt FORBIDS any answer
                     not explicitly present in the provided context.
  "conversational" — No context. System prompt handles chitchat, follow-ups,
                     and meta-questions using conversation history only.
"""

import os
import logging
from groq import Groq
from schemas import ChatMessage

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# System Prompts
# ─────────────────────────────────────────────────────────────────────────────

# Used when a curriculum question was asked AND confident context was retrieved.
# Every rule is a hard constraint — the LLM must not deviate.
CURRICULUM_SYSTEM_PROMPT = """You are VishwAlpha, a personalised AI tutor for Indian school students studying NCERT curriculum.

TEACHING STYLES (adapt to what the student needs):
1. **Direct Explanation** — clear, structured answers with bullet points or numbered steps.
2. **Socratic Guidance** — ask 1-2 guiding questions to lead the student toward the answer.
3. **Analogy & Examples** — use real-world, India-relevant examples to make concepts concrete.
4. **Step-by-Step Breakdown** — walk through multi-step processes or problems one step at a time.
5. **Encouraging Tone** — be patient and positive. Never make the student feel bad for not knowing.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT GROUNDING RULES — YOU MUST FOLLOW THESE WITHOUT EXCEPTION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Answer ONLY using the TEXTBOOK CONTEXT provided below.
2. If a fact, equation, definition, or example is NOT in the context — do NOT include it.
3. Do NOT use your own training knowledge to supplement, expand, or "help" the answer.
4. Do NOT invent examples, equations, or processes that are not explicitly in the context.
5. If the context does not fully answer the question, say exactly:
   "The textbook material I have doesn't cover this fully. Please ask your teacher or check your chapter."
6. Never say things like "as we know" or "generally speaking" to introduce non-context facts.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FORMAT:
- Use **bold** for key terms that appear in the context.
- Use bullet points or numbered lists for processes and lists.
- Keep answers concise — aim for quality, not length."""


# Used for conversational messages ("yes", "ok", "what did we discuss?", follow-ups).
# Much lighter — no strict grounding needed since there's no injected context.
CONVERSATIONAL_SYSTEM_PROMPT = """You are VishwAlpha, a friendly, organised AI tutor for Indian school students studying the NCERT curriculum.

The student has sent a conversational or planning message (a greeting, acknowledgement, follow-up, asking what to study, asking for a quiz, etc.).
You are currently helping a Class {class_num} student studying {subject}.

RULES:
1. **Be a Helpful Guide**: If the student asks "what should I learn today?", "suggest a topic", or "what's the plan?", look at their Class ({class_num}) and Subject ({subject}) and suggest 2-3 standard NCERT topics or chapters for them to choose from. Make it sound exciting!
2. **Follow-ups**: If the student says "yes" or "ok", acknowledge it and either ask a follow-up question related to what you were just discussing, or suggest moving to the next topic.
3. **Summaries**: If asked "what did we discuss?", summarise the earlier conversation.
4. **No Hallucinated Facts**: Do NOT introduce complex new factual/textbook content here. If they pick a topic, say "Great! Let's start with [Topic]. What do you already know about it?" (This will prompt them to ask a specific question, which will trigger the curriculum mode).
5. Keep your response short, friendly, and structured. Use bullet points if suggesting topics."""


class TutorLLM:
    """
    Generates personalised tutoring answers using Groq LLM.

    Usage:
        tutor = TutorLLM()
        answer = tutor.generate(question, context, history, memory_summary,
                                question_type, is_grounded)
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
        question_type: str = "curriculum",
        is_grounded: bool = True,
        class_num: int = 10,
        subject: str = "Science",
    ) -> tuple[str, list[dict]]:
        """
        Builds the prompt and generates a tutoring answer.

        Returns:
            (answer_string, prompt_messages)
            prompt_messages is the exact list of dicts sent to the Groq API —
            useful for debugging and the Streamlit "Prompt Inspector" panel.
        """
        messages = self._build_messages(
            question, context, history, memory_summary, question_type,
            class_num, subject
        )

        try:
            response = self.client.chat.completions.create(
                messages=messages,
                model=self.model,
                temperature=0.3 if question_type == "curriculum" else 0.5,
                max_tokens=800 if question_type == "curriculum" else 300,
            )
            answer = response.choices[0].message.content.strip()
            logger.info(
                f"Generated ({question_type}): {len(answer)} chars | "
                f"tokens: {response.usage.total_tokens}"
            )
            return answer, messages

        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            fallback = "I'm having trouble responding right now. Please try again in a moment."
            return fallback, messages

    def _build_messages(
        self,
        question: str,
        context: str,
        history: list[ChatMessage] | None,
        memory_summary: str,
        question_type: str,
        class_num: int,
        subject: str,
    ) -> list[dict]:
        """
        Builds the Groq messages array based on question type.

        For CURRICULUM:
          [system: strict grounding prompt]
          [system: textbook context]          ← injected as a system turn
          [system: memory summary]            ← if available
          [user/assistant: recent history]
          [user: current question]

        For CONVERSATIONAL:
          [system: conversational prompt]
          [system: memory summary]            ← if available
          [user/assistant: recent history]
          [user: current message]
        """
        msgs: list[dict] = []

        # 1. System prompt — chosen based on question type
        if question_type == "curriculum":
            msgs.append({"role": "system", "content": CURRICULUM_SYSTEM_PROMPT})
        else:
            prompt = CONVERSATIONAL_SYSTEM_PROMPT.format(
                class_num=class_num, subject=subject
            )
            msgs.append({"role": "system", "content": prompt})

        # 2. Textbook context (curriculum only) — injected as system turn BEFORE history
        #    so it is clearly separated from the conversation.
        if question_type == "curriculum" and context:
            msgs.append({
                "role": "system",
                "content": (
                    "━━━━━━━━ TEXTBOOK CONTEXT (your ONLY source of facts) ━━━━━━━━\n\n"
                    f"{context}\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                ),
            })

        # 3. Compressed memory of older turns (both modes can use this)
        if memory_summary:
            msgs.append({
                "role": "system",
                "content": (
                    "EARLIER CONVERSATION SUMMARY:\n"
                    f"{memory_summary}"
                ),
            })

        # 4. Recent history — last 2 turn pairs, verbatim
        if history:
            for msg in history:
                role = "user" if msg.role == "student" else "assistant"
                msgs.append({"role": role, "content": msg.content})

        # 5. Current question
        msgs.append({"role": "user", "content": question})

        return msgs
