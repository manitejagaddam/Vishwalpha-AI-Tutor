"""
app/services/tutor_llm.py
──────────────────────────
LLM generation service — builds prompts and calls the Azure OpenAI
chat completions endpoint (viswalpha-gpt-4.1-mini).

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
import time
from app.infra.azure_openai_client import get_openai
from app.config import settings
from app.services.ab_testing import get_active_prompt
from app.data.database import managed_session
from app.data.models.platform_ops import LLMCallLog

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

_CONVERSATIONAL_PROMPT = """You are VishwAlpha, a friendly and encouraging AI tutor for Indian school students.
The student has sent you a short conversational message. Respond naturally and briefly.
Stay warm, positive, and encouraging. Keep it under 3-4 sentences.
Reference the student's context if relevant — use what you know about them to personalise.

{teaching_style}

STUDENT CONTEXT (persistent memory — what you know about this student):
{student_memory}

{weak_topics_section}"""


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
    length = prefs.get("preferred_length", "medium")
    if length == "short":
        instructions.append("- Keep explanations brief and to the point.")
    elif length == "detailed":
        instructions.append("- Give thorough, detailed explanations. The student prefers depth.")

    # Encouragement
    enc = prefs.get("responds_to_encouragement", True)
    if enc:
        instructions.append("- Student is motivated by encouragement. Add praise and motivational language.")

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
        self.model = model or settings.AZURE_OPENAI_CHAT_DEPLOYMENT
        self.client = get_openai()

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
        user_id: str | None = None,
        conversation_id: str | None = None,
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

        # ── A/B Testing ───────────────────────────────────────────────────────
        experiment_name = f"{mode}_prompt"
        ab_template, ab_exp_id = None, None
        if user_id:
            ab_template, ab_exp_id = get_active_prompt(experiment_name, str(user_id))

        system_template = ab_template if ab_template else system_map.get(mode, _OPEN_CURRICULUM_PROMPT)
        
        try:
            system_content = system_template.format(
                context=context or "(no additional context)",
                student_memory=student_memory or "(no memory yet)",
                teaching_style=teaching_style,
                weak_topics_section=weak_section,
                review_section=review_section,
            )
        except KeyError as ke:
            logger.warning(
                f"[TutorLLM] A/B prompt template missing placeholder {ke} — falling back to default."
            )
            fallback_template = system_map.get(mode, _OPEN_CURRICULUM_PROMPT)
            system_content = fallback_template.format(
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
            model=self.model,
            temperature=0.0,
            max_tokens=5,
        )
        raw = response.choices[0].message.content.strip().lower()
        return "curriculum" if "curriculum" in raw else "conversational"

    def generate_chat_title(self, first_message: str) -> str:
        """
        Generates a Claude-style concise chat heading from the first student message.
        Short (3-6 words), topic-specific, no filler, no punctuation.
        """
        prompt = (
            "Generate a short, specific heading (3-6 words, no punctuation, no quotes, no filler words like 'question about' or 'help with') "
            "for a tutoring chat that starts with this student message. "
            "Be as specific as possible about the concept — like Claude's sidebar titles.\n\n"
            f"Student: {first_message[:300]}\n\n"
            "Title:"
        )
        try:
            client = get_openai()
            response = client.chat.completions.create(
                model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=20,
                temperature=0.2,
            )
            title = response.choices[0].message.content.strip().strip('"').strip("'")
            # Capitalise first letter of each word, drop trailing punctuation
            title = title.rstrip(".!?,;:").strip()
            return title if title else "New Conversation"
        except Exception as e:
            logger.error(f"Failed to generate chat title: {e}")
            words = first_message.split()
            return " ".join(words[:5]) + ("..." if len(words) > 5 else "")

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
                model=self.model,
                temperature=0.4,
                max_tokens=150,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            logger.warning(f"Remark generation failed: {exc}")
            return ""

    def generate_session_insight(self, conversation_history: list[dict], subject: str = "") -> dict:
        """
        Generates a structured end-of-session analysis from the conversation history.
        Returns a dict matching the SessionInsight model fields:
          topics_mastered, topics_struggled, misconceptions_found,
          bloom_levels_achieved, engagement_rating, session_summary, recommendations
        """
        history_text = "\n".join(
            f"{m.get('role','?').upper()}: {m.get('content','')[:300]}"
            for m in conversation_history[-20:]  # last 20 messages
        )
        prompt = f"""You are an expert educational analyst reviewing a tutoring session.
Analyse the following conversation and return a JSON object with EXACTLY this structure:
{{
  "topics_mastered": ["topic1", "topic2"],
  "topics_struggled": ["topic3"],
  "misconceptions_found": ["specific misconception text"],
  "bloom_levels_achieved": {{"remember": 2, "understand": 3, "apply": 1, "analyze": 0, "evaluate": 0, "create": 0}},
  "engagement_rating": 7.5,
  "session_summary": "2-3 sentence summary of what the student learned and how they engaged.",
  "recommendations": ["Specific action 1", "Specific action 2", "Specific action 3"]
}}

Rules:
- topics_mastered: topics the student clearly understood (based on follow-up questions showing comprehension)
- topics_struggled: topics where student showed confusion, repeated questions, or frustration
- misconceptions_found: specific wrong beliefs or misunderstandings the student showed
- bloom_levels_achieved: count of questions at each Bloom's level in this session
- engagement_rating: 1-10 score (10 = highly engaged, curious, many follow-ups)
- session_summary: honest, specific, encouraging 2-3 sentence summary
- recommendations: 2-3 concrete next steps for the student

Return ONLY the JSON object, no other text.

Subject: {subject}
Conversation:
{history_text}"""

        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.2,
                max_tokens=600,
            )
            raw = response.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1:
                return json.loads(raw[start:end + 1])
        except Exception as exc:
            logger.warning(f"Session insight generation failed: {exc}")
        return {}

    def generate_llm_metric_signals(self, conversation_history: list[dict]) -> dict:
        """
        Uses LLM to analyse a conversation and return delta adjustments for the
        10 cognitive metrics. Supplement to the per-turn regex signals.
        Returns dict of metric_key → delta (float, can be negative).
        """
        history_text = "\n".join(
            f"{m.get('role','?').upper()}: {m.get('content','')[:200]}"
            for m in conversation_history[-16:]
        )
        prompt = f"""You are an educational psychologist analysing a student's cognitive patterns.
Review this tutoring conversation and return a JSON object with delta adjustments
for each of these 10 cognitive metrics (all values must be floats, positive or negative):

{{
  "concept_master_score": <float, -5 to +10>,
  "error_repetition_rate": <float, -0.05 to +0.05>,
  "attempt_persistence": <float, -5 to +10>,
  "struggle_recovery_rate": <float, -5 to +10>,
  "practice_intensity": <float, -3 to +8>,
  "learning_velocity": <float, -5 to +10>,
  "knowledge_retention": <float, -5 to +8>,
  "cognitive_thinking_level": <float, -5 to +10>,
  "engagement_frequency": <float, -5 to +10>,
  "assessment_accuracy": <float, 0 to 0>
}}

Metric definitions:
- concept_master_score: did the student show genuine conceptual understanding?
- error_repetition_rate: did the student repeat the same mistakes? (positive = more errors)
- attempt_persistence: did the student keep trying after confusion?
- struggle_recovery_rate: did the student recover quickly from confusion?
- practice_intensity: how actively did the student engage/practice?
- learning_velocity: how quickly did the student grasp new ideas?
- knowledge_retention: did the student recall previously discussed concepts?
- cognitive_thinking_level: did the student ask higher-order thinking questions?
- engagement_frequency: how frequently and actively did the student engage?
- assessment_accuracy: leave as 0 (only updated by actual quizzes)

Return ONLY the JSON object. Be conservative — use 0 for metrics you cannot determine.

Conversation:
{history_text}"""

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
                # Validate: only keep known metric keys, cast to float
                from app.data.cognitive_repo import METRICS_KEYS
                return {
                    k: float(v)
                    for k, v in signals.items()
                    if k in METRICS_KEYS and v != 0
                }
        except Exception as exc:
            logger.warning(f"LLM metric signal generation failed: {exc}")
        return {}

    def extract_durable_memories(
        self,
        existing_memories: list[str],
        conversation_history: list[dict],
        subject: str = "",
    ) -> dict:
        """
        Consolidates long-term memory from full conversation history.
        Preserves all historical context (even facts from a year ago).
        Returns a dict:
          {
            "new_facts": ["fact 1", "fact 2"],
            "resolved_facts": ["fact resolved"],
            "preference_nudges": {"prefers_examples": 0.1, "prefers_step_by_step": 0.1, "preferred_length": "short"}
          }
        """
        history_text = "\n".join(
            f"{m.get('role','?').upper()}: {m.get('content','')[:250]}"
            for m in conversation_history[-24:]
        )
        existing_str = "\n".join(f"- {m}" for m in existing_memories) if existing_memories else "(none yet)"

        prompt = f"""You are the long-term memory consolidation system for an AI tutor.
Review this tutoring conversation against the student's existing persistent memory.

Existing Long-Term Memories (from student's history):
{existing_str}

Recent Conversation:
{history_text}

Subject: {subject or "General"}

Identify:
1. "new_facts": 1-3 new durable, high-signal facts about the student learned in this session.
   - Good examples: "Struggles with balancing redox reactions", "Targeting 95% in Board exams", "Prefers real-life analogies before formulas", "Has science exam on Monday"
   - Bad examples (DO NOT include): Trivial chit-chat ("said thank you"), ephemeral questions ("asked question 3"), or facts ALREADY in existing memory.
2. "resolved_facts": Any existing memory facts that the student has now clearly mastered or resolved in this session.
3. "preference_nudges": Any learning style adjustments detected:
   - "prefers_examples": float delta (-0.1 to +0.2)
   - "prefers_step_by_step": float delta (-0.1 to +0.2)
   - "prefers_analogies": float delta (-0.1 to +0.2)
   - "prefers_visuals": float delta (-0.1 to +0.2)
   - "preferred_length": "short" | "medium" | "detailed" (or omit)

Return ONLY a JSON object with keys "new_facts", "resolved_facts", and "preference_nudges":
{{
  "new_facts": [],
  "resolved_facts": [],
  "preference_nudges": {{}}
}}"""

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
                    "new_facts": data.get("new_facts", []) or [],
                    "resolved_facts": data.get("resolved_facts", []) or [],
                    "preference_nudges": data.get("preference_nudges", {}) or {},
                }
        except Exception as exc:
            logger.warning(f"Durable memory extraction failed: {exc}")
        return {"new_facts": [], "resolved_facts": [], "preference_nudges": {}}
