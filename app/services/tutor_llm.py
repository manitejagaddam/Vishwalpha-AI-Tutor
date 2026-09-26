"""
app/services/tutor_llm.py
──────────────────────────
LLM generation service — builds prompts and calls the Azure OpenAI
chat completions endpoint.

All prompt templates live in app/prompts.py.
This module handles:
  - Prompt assembly (teaching style + memory + weak topics)
  - A/B prompt experiment injection
  - Per-mode temperature / max_token config
  - Structured LLM calls (classify, title, remark, insight, metrics, memory)

Supports 3 generation modes:
  curriculum      — strict RAG: answers ONLY from retrieved context
  open_curriculum — free: uses LLM knowledge for general academic questions
  conversational  — short: small talk / meta replies without RAG context
"""
import json
import logging

from app.config import settings
from app.data.database import managed_session
from app.infra.azure_openai_client import get_openai
from app.prompts import (
    CHAT_TITLE_PROMPT,
    CLASSIFY_QUESTION_PROMPT,
    CONVERSATIONAL_PROMPT,
    CURRICULUM_PROMPT,
    DURABLE_MEMORY_PROMPT,
    LLM_METRIC_SIGNALS_PROMPT,
    OPEN_CURRICULUM_PROMPT,
    SESSION_INSIGHT_PROMPT,
    SESSION_REMARK_PROMPT,
)
from app.services.ab_testing import get_active_prompt

logger = logging.getLogger(__name__)

# Re-export prompts for legacy import paths used in chat_orchestrator.py streaming path
_CURRICULUM_PROMPT      = CURRICULUM_PROMPT
_OPEN_CURRICULUM_PROMPT = OPEN_CURRICULUM_PROMPT
_CONVERSATIONAL_PROMPT  = CONVERSATIONAL_PROMPT


# ── Teaching style / weak topic / review section builders ────────────────────

def _build_teaching_style(prefs: dict) -> str:
    """
    Converts learning preferences into natural-language teaching instructions
    that steer the LLM's response style.
    Returns an empty string when prefs is empty or has no actionable values.
    """
    if not prefs:
        return ""

    instructions = ["TEACHING STYLE ADAPTATIONS (based on this student's learning profile):"]

    ex = prefs.get("prefers_examples", 0.5)
    if ex > 0.7:
        instructions.append("- Student learns best with MANY examples. Include 2-3 worked examples.")
    elif ex < 0.3:
        instructions.append("- Student prefers concise explanations with minimal examples. Keep to 1 example.")

    an = prefs.get("prefers_analogies", 0.5)
    if an > 0.7:
        instructions.append("- Student responds well to analogies. Use creative, relatable analogies.")
    elif an < 0.3:
        instructions.append("- Student prefers direct, technical explanations over analogies.")

    ss = prefs.get("prefers_step_by_step", 0.5)
    if ss > 0.7:
        instructions.append("- Student needs detailed step-by-step breakdowns. Number each step clearly.")
    elif ss < 0.3:
        instructions.append("- Student grasps concepts quickly. Give a summary-style explanation.")

    length = prefs.get("preferred_length", "medium")
    if length == "short":
        instructions.append("- Keep explanations brief and to the point.")
    elif length == "detailed":
        instructions.append("- Give thorough, detailed explanations. The student prefers depth.")

    enc = prefs.get("responds_to_encouragement", True)
    if enc:
        instructions.append("- Student is motivated by encouragement. Add praise and motivational language.")

    vis = prefs.get("prefers_visuals", 0.5)
    if vis > 0.7:
        instructions.append("- Student is a visual learner. Use tables, ASCII diagrams, or structured layouts.")

    if len(instructions) <= 1:
        return ""
    return "\n".join(instructions)


def _build_weak_topics_section(weak_topics_str: str) -> str:
    """Formats the weak topics list into a prompt section."""
    if not weak_topics_str:
        return ""
    return (
        "STUDENT'S WEAK AREAS (topics needing extra attention):\n"
        f"{weak_topics_str}\n"
        "If the current question relates to any weak topic, "
        "provide extra-detailed explanations and check understanding."
    )


def _build_review_section(review_topics: list[dict]) -> str:
    """Formats spaced-repetition review topics into a prompt section."""
    if not review_topics:
        return ""
    topics_str = "\n".join(
        f"- {t['topic_title']} (last score: {t.get('last_quiz_score', 'N/A')})"
        for t in review_topics[:3]
    )
    return (
        "TOPICS DUE FOR REVIEW (spaced repetition):\n"
        f"{topics_str}\n"
        "If this is a new session, gently remind the student about these topics "
        "and suggest a quick review."
    )


# ── TutorLLM class ────────────────────────────────────────────────────────────

class TutorLLM:
    """
    LLM generation layer. Stateless — safe to use as a module-level singleton.
    All prompt templates are imported from app.prompts.
    """

    def __init__(self, model: str | None = None) -> None:
        self.model  = model or settings.AZURE_OPENAI_CHAT_DEPLOYMENT
        self.client = get_openai()

    # ── Main generation ───────────────────────────────────────────────────────

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
        subject_context: str = "",
        user_id: str | None = None,
        conversation_id: str | None = None,
    ) -> tuple[str, list[dict]]:
        """
        Generates a tutor response.

        Args:
            mode:                 "curriculum" | "open_curriculum" | "conversational"
            question:             The student's question
            history:              List of Msg objects (recent conversation)
            context:              Retrieved RAG context (curriculum mode only)
            student_memory:       Persistent memory facts about the student
            learning_preferences: Dict of learning style preferences
            weak_topics:          Formatted string of weak topics
            review_topics:        List of topics due for spaced repetition review
            subject_context:      String detailing class, subject, and syllabus
            user_id:              For A/B experiment assignment
            conversation_id:      For logging (unused currently)

        Returns:
            (answer_text, prompt_messages_list)
        """
        system_map = {
            "curriculum":      CURRICULUM_PROMPT,
            "open_curriculum": OPEN_CURRICULUM_PROMPT,
            "conversational":  CONVERSATIONAL_PROMPT,
        }

        teaching_style = _build_teaching_style(learning_preferences or {})
        weak_section   = _build_weak_topics_section(weak_topics)
        review_section = _build_review_section(review_topics or [])

        # A/B Testing — override system template if an active experiment exists
        ab_template, _ab_exp_id = None, None
        if user_id:
            ab_template, _ab_exp_id = get_active_prompt(f"{mode}_prompt", str(user_id))

        system_template = ab_template or system_map.get(mode, OPEN_CURRICULUM_PROMPT)

        try:
            system_content = system_template.format(
                context=context or "(no additional context)",
                student_memory=student_memory or "(no memory yet)",
                teaching_style=teaching_style,
                weak_topics_section=weak_section,
                review_section=review_section,
                subject_context=subject_context,
            )
        except KeyError as ke:
            logger.warning(
                f"[TutorLLM] A/B prompt template missing placeholder {ke} — falling back to default."
            )
            fallback_template = system_map.get(mode, OPEN_CURRICULUM_PROMPT)
            system_content = fallback_template.format(
                context=context or "(no additional context)",
                student_memory=student_memory or "(no memory yet)",
                teaching_style=teaching_style,
                weak_topics_section=weak_section,
                review_section=review_section,
                subject_context=subject_context,
            )

        temp, max_tok = _mode_config(mode)

        messages = [{"role": "system", "content": system_content}]
        for msg in history:
            messages.append({
                "role":    "user" if msg.role == "student" else "assistant",
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

    # ── Classification ────────────────────────────────────────────────────────

    def classify_question(self, question: str, history: list) -> str:
        """
        LLM-based classifier: returns 'curriculum' or 'conversational'.
        Used as a fallback when the heuristic classifier is uncertain.
        """
        history_snippet = "\n".join(
            f"{m.role.upper()}: {m.content}" for m in history[-4:]
        )
        prompt = CLASSIFY_QUESTION_PROMPT.format(
            history_snippet=history_snippet,
            question=question,
        )
        response = self.client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=self.model,
            temperature=0.0,
            max_tokens=5,
        )
        raw = response.choices[0].message.content.strip().lower()
        return "curriculum" if "curriculum" in raw else "conversational"

    # ── Chat title ────────────────────────────────────────────────────────────

    def generate_chat_title(self, first_message: str) -> str:
        """
        Generates a concise chat heading (3-6 words) from the first student message.
        Claude-style sidebar title format — specific, no filler.
        """
        prompt = CHAT_TITLE_PROMPT.format(first_message=first_message[:300])
        try:
            client   = get_openai()
            response = client.chat.completions.create(
                model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=20,
                temperature=0.2,
            )
            title = response.choices[0].message.content.strip().strip('"').strip("'")
            title = title.rstrip(".!?,;:").strip()
            return title if title else "New Conversation"
        except Exception as exc:
            logger.error(f"Failed to generate chat title: {exc}")
            words = first_message.split()
            return " ".join(words[:5]) + ("..." if len(words) > 5 else "")

    # ── Session remark ────────────────────────────────────────────────────────

    def generate_remark(self, conversation_context: str) -> str:
        """Generates a brief teacher-style remark about the session (2-3 sentences)."""
        prompt = SESSION_REMARK_PROMPT.format(
            conversation_context=conversation_context[:800]
        )
        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.4,
                max_tokens=150,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.warning(f"Remark generation failed: {exc}")
            return ""

    # ── Session insight ───────────────────────────────────────────────────────

    def generate_session_insight(
        self, conversation_history: list[dict], subject: str = ""
    ) -> dict:
        """
        Generates a structured end-of-session analysis from the conversation history.
        Returns a dict matching the SessionInsight model fields.
        """
        history_text = "\n".join(
            f"{m.get('role','?').upper()}: {m.get('content','')[:300]}"
            for m in conversation_history[-20:]
        )
        prompt = SESSION_INSIGHT_PROMPT.format(subject=subject, history_text=history_text)
        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.2,
                max_tokens=600,
            )
            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1:
                return json.loads(raw[start:end + 1])
        except Exception as exc:
            logger.warning(f"Session insight generation failed: {exc}")
        return {}

    # ── LLM metric signals ────────────────────────────────────────────────────

    def generate_llm_metric_signals(self, conversation_history: list[dict]) -> dict:
        """
        Analyses a full conversation and returns delta adjustments for the
        10 cognitive metrics. Supplement to the per-turn regex signals.
        Returns dict of metric_key → delta (float).
        """
        history_text = "\n".join(
            f"{m.get('role','?').upper()}: {m.get('content','')[:200]}"
            for m in conversation_history[-16:]
        )
        prompt = LLM_METRIC_SIGNALS_PROMPT.format(history_text=history_text)
        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.1,
                max_tokens=300,
            )
            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1:
                signals = json.loads(raw[start:end + 1])
                from app.data.cognitive_repo import METRICS_KEYS
                return {
                    k: float(v)
                    for k, v in signals.items()
                    if k in METRICS_KEYS and v != 0
                }
        except Exception as exc:
            logger.warning(f"LLM metric signal generation failed: {exc}")
        return {}

    # ── Durable memory extraction ─────────────────────────────────────────────

    def extract_durable_memories(
        self,
        existing_memories: list[str],
        conversation_history: list[dict],
        subject: str = "",
    ) -> dict:
        """
        Consolidates long-term memory from the full conversation history.
        Preserves all historical context (even facts from a year ago).

        Returns:
          {
            "new_facts":       [...],
            "resolved_facts":  [...],
            "preference_nudges": {...}
          }
        """
        history_text = "\n".join(
            f"{m.get('role','?').upper()}: {m.get('content','')[:250]}"
            for m in conversation_history[-24:]
        )
        existing_str = (
            "\n".join(f"- {m}" for m in existing_memories)
            if existing_memories
            else "(none yet)"
        )
        prompt = DURABLE_MEMORY_PROMPT.format(
            existing_str=existing_str,
            history_text=history_text,
            subject=subject or "General",
        )
        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.2,
                max_tokens=400,
            )
            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1:
                data = json.loads(raw[start:end + 1])
                return {
                    "new_facts":        data.get("new_facts", [])        or [],
                    "resolved_facts":   data.get("resolved_facts", [])   or [],
                    "preference_nudges":data.get("preference_nudges", {}) or {},
                }
        except Exception as exc:
            logger.warning(f"Durable memory extraction failed: {exc}")
        return {"new_facts": [], "resolved_facts": [], "preference_nudges": {}}


# ── Module-level helpers ──────────────────────────────────────────────────────

def _mode_config(mode: str) -> tuple[float, int]:
    """Returns (temperature, max_tokens) for the given generation mode."""
    return {
        "curriculum":      (0.3, 1500),
        "open_curriculum": (0.5, 2000),
        "conversational":  (0.7, 400),
    }.get(mode, (0.5, 2000))
