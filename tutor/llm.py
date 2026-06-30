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


def format_personalization_instructions(metrics: dict | None, cognitive_skills: dict | None) -> str:
    if not metrics or not cognitive_skills:
        return ""

    # Extract the 5 mapped skills
    concept_under = cognitive_skills.get("concept_understanding", 50.0)
    effort = cognitive_skills.get("learning_effort", 50.0)
    adaptability = cognitive_skills.get("learning_adaptability", 50.0)
    stability = cognitive_skills.get("knowledge_stability", 50.0)
    depth = cognitive_skills.get("cognitive_depth", 50.0)

    # Extract specific raw metrics for fine-tuning
    err_rep = metrics.get("error_repetition_rate", 0.2)

    instructions = f"""
━━━━━━━━ STUDENT PROFILE & PERSONALIZATION RULES ━━━━━━━━
Current Cognitive Skill Levels:
- Concept Understanding: {concept_under}% (Grasp of factual and textbook knowledge)
- Learning Effort: {effort}% (Engagement depth, question complexity, persistence)
- Learning Adaptability: {adaptability}% (Ability to recover from mistakes and process corrections)
- Knowledge Stability: {stability}% (Memory retention of concepts and progress speed)
- Cognitive Depth: {depth}% (Bloom's Taxonomy stage, e.g., Recall -> Analyze)

Pedagogy Adaptation Guidelines:
"""
    # 1. Concept Understanding rules
    if concept_under < 40:
        instructions += "- Concept Understanding is LOW. Explain definitions in very basic terms. Avoid complex jargon. Use simple analogies first.\n"
    elif concept_under > 75:
        instructions += "- Concept Understanding is HIGH. Do not over-explain basic terms. Introduce advanced terms and deeper context.\n"

    # 2. Learning Effort rules
    if effort < 40:
        instructions += "- Learning Effort is LOW. Keep explanations punchy and brief to maintain interest. Do not write massive paragraphs.\n"
    elif effort > 75:
        instructions += "- Learning Effort is HIGH. Provide detailed, comprehensive answers with rich academic depth.\n"

    # 3. Learning Adaptability / Error repetition rules
    if adaptability < 40 or err_rep > 0.4:
        instructions += "- Learning Adaptability is LOW / Error Repetition is HIGH. Repeat key corrective points clearly. Highlight common mistakes to watch out for. Walk through corrections step-by-step.\n"
    elif adaptability > 75:
        instructions += "- Learning Adaptability is HIGH. Highlight only subtle nuances; the student processes corrections easily.\n"

    # 4. Cognitive Depth rules (Bloom's Taxonomy)
    if depth < 30:
        instructions += "- Cognitive Depth is Recall-level. Provide clear definitions, facts, and structure. Use bullet points.\n"
    elif depth > 70:
        instructions += "- Cognitive Depth is analytical/evaluative. Guide the student using Socratic prompting, challenge their assumptions, and ask them to analyze or compare concepts.\n"

    instructions += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    return instructions


class TutorLLM:
    """
    Generates personalised tutoring answers using Groq LLM.

    Usage:
        tutor = TutorLLM()
        answer = tutor.generate(question, context, history, memory_summary,
                                question_type, is_grounded, metrics, cognitive_skills)
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
        metrics: dict | None = None,
        cognitive_skills: dict | None = None,
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
            class_num, subject, metrics, cognitive_skills
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
        metrics: dict | None = None,
        cognitive_skills: dict | None = None,
    ) -> list[dict]:
        """
        Builds the Groq messages array based on question type.
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

        # 1b. Injected Personalization Prompt based on cognitive metrics and skills
        pers_prompt = format_personalization_instructions(metrics, cognitive_skills)
        if pers_prompt:
            msgs.append({"role": "system", "content": pers_prompt})

        # 2. Textbook context (curriculum only) — injected as system turn BEFORE history
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

