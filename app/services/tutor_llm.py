"""
app/services/tutor_llm.py
──────────────────────────
LLM generation service — builds prompts and calls Groq.

Supports 3 generation modes:
  curriculum      — strict RAG: answers ONLY from retrieved context
  open_curriculum — free: uses LLM knowledge for general academic questions
  conversational  — short: small talk / meta replies without RAG context

Enhanced with:
  - Learning preference injection (step-by-step, analogies, length)
  - Weak topic awareness (tutor knows which topics need extra care)
  - Spaced repetition review prompting (gently reminds on new sessions)
"""
import json
import logging
from app.infra.groq_client import get_groq
from app.config import settings

logger = logging.getLogger(__name__)

# ── System Prompts ────────────────────────────────────────────────────────────

_CURRICULUM_PROMPT = """You are VishwAlpha, an expert NCERT curriculum tutor for Indian students.
Your goal is to deeply explain concepts with clarity and real-world examples.

STRICT RULES:
1. Answer ONLY using the provided curriculum context.
2. If the context doesn't contain enough information, clearly say so.
3. Always structure your answer with:
   - A direct answer to the question
   - Step-by-step explanation where applicable
   - At least one real-world analogy or example (preferably India-relevant)
   - Connection back to the NCERT concept
4. Use markdown formatting: **bold** for key terms, ## for sections, bullet lists.
5. End with a motivating sentence encouraging the student to explore further.
6. DO NOT hallucinate or add information not in the context.

{teaching_style}

STUDENT CONTEXT (persistent memory):
{student_memory}

{weak_topics_section}

{review_section}

CURRICULUM CONTEXT:
{context}"""

_OPEN_CURRICULUM_PROMPT = """You are VishwAlpha, an expert academic tutor for Indian students following the NCERT curriculum.
A student has asked an academic question that requires your full knowledge — not just the textbook.

Your goal is to provide a COMPLETE, DETAILED explanation:
1. Start with a clear, direct answer.
2. Break it down step-by-step.
3. Use real-world analogies (preferably India-relevant: cricket, festivals, daily life).
4. Explain the underlying science/math/history/logic.
5. Connect it to what students learn in NCERT if applicable.
6. Use markdown: **bold** for key terms, ## for sections, bullet lists, tables if comparing things.
7. Always end with an encouraging sentence.

Do NOT give a short 3-4 line answer. Give a FULL EDUCATIONAL explanation that makes the student truly understand.

{teaching_style}

STUDENT CONTEXT (persistent memory):
{student_memory}

{weak_topics_section}

{review_section}"""

_CONVERSATIONAL_PROMPT = """You are VishwAlpha, a friendly and encouraging AI tutor.
The student has sent you a short conversational message. Respond naturally and briefly.
Stay warm, positive, and encouraging. Keep it under 3 sentences.
Reference the student's context if relevant.

{teaching_style}

STUDENT CONTEXT (persistent memory):
{student_memory}"""


def _build_teaching_style(prefs: dict) -> str:
    """
    Converts learning preferences into natural-language teaching instructions
    that steer the LLM's response style.
    """
    if not prefs:
        return ""

    instructions = ["TEACHING STYLE ADAPTATIONS (based on this student's learning profile):"]

    # Example preference
    ex = prefs.get("prefers_examples", 0.5)
    if ex > 0.7:
        instructions.append("- Student learns best with MANY examples. Include 2-3 worked examples.")
    elif ex < 0.3:
        instructions.append("- Student prefers concise explanations with minimal examples. Keep to 1 example.")

    # Analogy preference
    an = prefs.get("prefers_analogies", 0.5)
    if an > 0.7:
        instructions.append("- Student responds well to analogies. Use creative, relatable analogies.")
    elif an < 0.3:
        instructions.append("- Student prefers direct, technical explanations over analogies.")

    # Step-by-step preference
    ss = prefs.get("prefers_step_by_step", 0.5)
    if ss > 0.7:
        instructions.append("- Student needs detailed step-by-step breakdowns. Number each step clearly.")
    elif ss < 0.3:
        instructions.append("- Student grasps concepts quickly. Give a summary-style explanation.")

    # Explanation length
    length = prefs.get("preferred_explanation_length", "medium")
    if length == "short":
        instructions.append("- Keep explanations brief and to the point.")
    elif length == "detailed":
        instructions.append("- Give thorough, detailed explanations. The student prefers depth.")

    # Encouragement
    enc = prefs.get("responds_to_encouragement", 0.5)
    if enc > 0.7:
        instructions.append("- Student is motivated by encouragement. Add praise and motivational language.")

    # Hindi mix
    hindi = prefs.get("prefers_hindi_mix", 0.0)
    if hindi > 0.5:
        instructions.append("- Student is comfortable with Hindi-English mix. You may use common Hindi terms.")

    # Visual preference
    vis = prefs.get("prefers_visuals", 0.5)
    if vis > 0.7:
        instructions.append("- Student is a visual learner. Use tables, ASCII diagrams, or structured layouts.")

    if len(instructions) <= 1:
        return ""

    return "\n".join(instructions)


def _build_weak_topics_section(weak_topics_str: str) -> str:
    """Formats weak topics into a prompt section."""
    if not weak_topics_str:
        return ""
    return f"""STUDENT'S WEAK AREAS (topics needing extra attention):
{weak_topics_str}
If the current question relates to any weak topic, provide extra-detailed explanations and check understanding."""


def _build_review_section(review_topics: list[dict]) -> str:
    """Formats spaced repetition review topics into a prompt section."""
    if not review_topics:
        return ""
    topics_str = "\n".join(
        f"- {t['topic_title']} (last score: {t.get('last_quiz_score', 'N/A')})"
        for t in review_topics[:3]
    )
    return f"""TOPICS DUE FOR REVIEW (spaced repetition):
{topics_str}
If this is a new session, gently remind the student about these topics and suggest a quick review."""


class TutorLLM:
    """
    LLM generation layer. Stateless — safe to use as a module-level singleton.
    """

    def __init__(self, model: str | None = None):
        self.model = model or settings.GROQ_MODEL
        self.client = get_groq()

    def generate(
        self,
        mode: str,
        question: str,
        history: list,
        context: str = "",
        student_memory: str = "",
        learning_preferences: dict | None = None,
        weak_topics: str = "",
        review_topics: list[dict] | None = None,
    ) -> tuple[str, list[dict]]:
        """
        Generates a tutor response.

        Args:
            mode:                  "curriculum" | "open_curriculum" | "conversational"
            question:              The student's question
            history:               List of ChatMessage objects (recent conversation)
            context:               Retrieved RAG context (curriculum mode only)
            student_memory:        Persistent memory facts about the student
            learning_preferences:  Dict of learning style preferences
            weak_topics:           Formatted string of weak topics
            review_topics:         List of topics due for spaced repetition review

        Returns:
            (answer_text, prompt_messages_list)
        """
        system_map = {
            "curriculum":      _CURRICULUM_PROMPT,
            "open_curriculum": _OPEN_CURRICULUM_PROMPT,
            "conversational":  _CONVERSATIONAL_PROMPT,
        }

        teaching_style = _build_teaching_style(learning_preferences or {})
        weak_section = _build_weak_topics_section(weak_topics)
        review_section = _build_review_section(review_topics or [])

        system_template = system_map.get(mode, _OPEN_CURRICULUM_PROMPT)
        system_content = system_template.format(
            context=context or "(no additional context)",
            student_memory=student_memory or "(no memory yet)",
            teaching_style=teaching_style,
            weak_topics_section=weak_section,
            review_section=review_section,
        )

        # Temperature and token config per mode
        if mode == "curriculum":
            temp, max_tok = 0.3, 1500
        elif mode == "open_curriculum":
            temp, max_tok = 0.5, 2000
        else:
            temp, max_tok = 0.7, 400

        messages = [{"role": "system", "content": system_content}]

        # Add conversation history
        for msg in history:
            messages.append({
                "role": "user" if msg.role == "student" else "assistant",
                "content": msg.content,
            })

        messages.append({"role": "user", "content": question})

        response = self.client.chat.completions.create(
            messages=messages,
            model=self.model,
            temperature=temp,
            max_tokens=max_tok,
        )

        answer = response.choices[0].message.content.strip()
        return answer, messages

    def classify_question(self, question: str, history: list) -> str:
        """
        LLM-based classifier: returns 'curriculum' or 'conversational'.
        Used as a fallback when the heuristic classifier is uncertain.
        """
        history_snippet = "\n".join(
            f"{m.role.upper()}: {m.content}" for m in history[-4:]
        )
        prompt = f"""Classify this student message for an educational AI tutor.

Recent conversation:
{history_snippet}

Student message: "{question}"

Does this require looking up textbook content?
Answer with ONLY one word: 'curriculum' or 'conversational'"""

        response = self.client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            temperature=0.0,
            max_tokens=5,
        )
        raw = response.choices[0].message.content.strip().lower()
        return "curriculum" if "curriculum" in raw else "conversational"

    def generate_remark(self, conversation_context: str) -> str:
        """Generates a brief teacher-style remark about the session."""
        prompt = f"""You are an AI teaching assistant reviewing a tutoring session.
Write a brief, honest teacher's remark about the student's performance and engagement.
2-3 sentences max. Be specific, constructive, and encouraging.

Session summary:
{conversation_context[:800]}"""

        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant",
                temperature=0.4,
                max_tokens=150,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.warning(f"Remark generation failed: {exc}")
            return ""
