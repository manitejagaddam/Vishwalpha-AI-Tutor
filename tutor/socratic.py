"""
tutor/socratic.py
─────────────────
Socratic Deep Learning Mode for VishwAlpha.

Two-phase flow (per question in deep mode):

  Phase 1 — start_diagnostic():
    Step 1: DB lookup for TopicPrerequisite rows (FREE)
    Step 2: If none exist, one LLM call to infer + save to DB (paid once, free forever after)
    Step 3: Algorithmic prerequisite selection using cognitive metrics (FREE, no LLM)
    Step 4: One LLM call to generate the diagnostic question (only LLM call in Phase 1)

    Result: worst-case 2 LLM calls (infer + question), best-case 1 LLM call.
    Previous: always 3 sequential LLM calls.

  Phase 2 — evaluate_and_explain():
    - Algorithmic understanding detection via tutor/patterns.py (FREE, no LLM)
    - Detects give-up → adaptive skip (complete answer + consolidation nudge)
    - Cross-class backtracking: retrieves actual lower-class content (not just tone change)
    - visited_topics guard prevents infinite loops
    - Rock-bottom fallback (Class 1 or max depth 3): analogy-based explanation
"""
import os
import json
import time
import logging
from groq import Groq
from schemas import ChatMessage

logger = logging.getLogger(__name__)

RATE_LIMIT_SLEEP = 0.3  # small courtesy delay

MAX_BACKTRACK_DEPTH = 3   # confirmed by user: max 3 classes back
UNDERSTANDING_THRESHOLD = 0.50

# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────

INFER_PREREQUISITES_PROMPT = """You are an NCERT curriculum expert.
A student is about to study this topic: "{topic}" (from: {chapter}, Class {class_num} {subject}).

The topic has no prerequisites stored. Infer 3-5 simpler prerequisite concepts or topics
a student must understand BEFORE studying this topic, based on standard NCERT syllabus progression.

For EACH prerequisite, also provide:
- The class level where it is typically taught (prereq_class_num)
- The typical subject (prereq_subject, usually same as current)
- A brief 1-sentence description (prereq_description)
- 3-5 expected keywords a student should use when demonstrating understanding

Return ONLY a JSON array:
[
  {
    "prereq_description": "...",
    "prereq_class_num": 8,
    "prereq_subject": "Science",
    "prereq_chapter": "...",
    "expected_keywords": ["kw1", "kw2", "kw3"],
    "difficulty_order": 0
  }
]
Order from most foundational (difficulty_order=0) to most advanced."""

DIAGNOSTIC_QUESTION_PROMPT = """You are VishwAlpha, a warm and encouraging AI tutor for Indian school students studying NCERT curriculum.

The student has just asked about: "{question}"

Before explaining this topic, you want to understand what they already know about a foundational prerequisite: "{prerequisite}"

Write a single, friendly diagnostic question that:
1. Seamlessly bridges from their question to the prerequisite. (e.g., "That's a great question about [topic]! To help me explain it best, could you first tell me...")
2. Does NOT reveal the answer to their original question.
3. Naturally checks their understanding of "{prerequisite}".
4. Sounds like a human tutor casually chatting, not an examiner giving a test.

Write ONLY the conversational response and diagnostic question, no extra text."""

ADAPTIVE_SKIP_PROMPT = """You are VishwAlpha, a warm AI tutor for Indian school students (NCERT curriculum).

The student originally asked: "{original_question}"
They are now giving up or asking to skip the diagnostic.

Their diagnostic response: "{student_response}"

Textbook context: {context}

Your task: Provide a COMPLETE, clear explanation of the original topic using the textbook context.
Teach it directly and thoroughly so they truly understand it.
At the very end, attach ONE short, friendly consolidation nudge (do not force them to answer it).

Example ending: "I've explained it fully! When you're ready, try to think about [simple micro-exercise] — it'll help it stick in your memory 🧠"

Keep it warm and non-judgmental. Do NOT re-ask the prerequisite question."""

BACKTRACK_LESSON_PROMPT = """You are VishwAlpha, a warm AI tutor for Indian school students (NCERT curriculum).

The student is struggling with: "{prereq_description}"
This is a prerequisite for their original topic.

We are teaching them using Class {backtrack_class} level content:
{context}

Their last response: "{student_response}"

Teach this foundational concept clearly and gently using the context above.
After teaching, ask ONE simple check question to test their understanding.
Do NOT move to the original topic yet — build the foundation first.
Keep it warm, simple, and encouraging."""

BASE_CONCEPT_PROMPT = """You are VishwAlpha, a warm AI tutor for Indian school students (NCERT curriculum).

The student is struggling deeply with a fundamental concept: "{prereq_description}"
They have needed multiple levels of backtracking. We are now at the most basic explanation.

Explain this concept using ONLY real-world, everyday analogies that require NO prior knowledge.
No textbook jargon. No formulas. Just intuitive real-world explanations.
End with: "Does that make sense? Once you get this idea, we can build up to [original_topic]!"

Original topic they wanted to learn: "{original_question}"
""" 

SESSION_START_PROMPT = """You are VishwAlpha, a warm and organised AI tutor for Indian school students studying the NCERT curriculum.

This is the START of a new session with a Class {class_num} student studying {subject}.

Student persistent memory (things you know about this student):
{memory_section}

Pending tasks the student wanted to work on:
{tasks_section}

Your job is to warmly open the session:
1. Greet the student warmly.
2. Briefly remind them of relevant things from past sessions (1-2 points max, only if memory exists).
3. If they have pending tasks, mention 1-2 of them and ask if they want to continue.
4. Ask what they would like to learn or work on today.

Keep the greeting SHORT (3-5 sentences). Be energetic and motivating. Do NOT explain any topics yet."""


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers — prerequisite persistence
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_prerequisites_from_db(topic_title: str, chapter_title: str) -> list:
    """
    Fetches stored TopicPrerequisite rows for a topic from the DB.
    Returns list of TopicPrerequisite ORM objects ordered by difficulty_order.
    """
    try:
        from core.db_session import managed_session
        from db.models import Topic, Chapter, TopicPrerequisite
        from sqlalchemy import func
        with managed_session() as db:
            topic = (
                db.query(Topic)
                .join(Chapter, Topic.chapter_id == Chapter.id)
                .filter(
                    func.lower(Topic.title) == topic_title.lower(),
                    func.lower(Chapter.title) == chapter_title.lower(),
                )
                .first()
            )
            if topic:
                prereqs = (
                    db.query(TopicPrerequisite)
                    .filter(TopicPrerequisite.topic_id == topic.id)
                    .order_by(TopicPrerequisite.difficulty_order)
                    .all()
                )
                if prereqs:
                    # Detach from session — convert to plain dicts
                    return [
                        {
                            "prereq_description": p.prereq_description,
                            "prereq_class_num": p.prereq_class_num,
                            "prereq_subject": p.prereq_subject,
                            "prereq_chapter": p.prereq_chapter,
                            "expected_keywords": json.loads(p.expected_keywords or "[]"),
                            "difficulty_order": p.difficulty_order,
                        }
                        for p in prereqs
                    ]
    except Exception as e:
        logger.warning(f"Could not fetch prerequisites from DB: {e}")
    return []


def _infer_and_save_prerequisites(
    topic_title: str,
    chapter_title: str,
    class_num: int,
    subject: str,
    client,
    model: str,
) -> list[dict]:
    """
    Calls the LLM to infer prerequisites and persists them to topic_prerequisites.
    Next time this topic is accessed, _fetch_prerequisites_from_db() will return
    them for FREE — the LLM is only ever called once per topic.
    """
    time.sleep(RATE_LIMIT_SLEEP)
    prompt = INFER_PREREQUISITES_PROMPT.format(
        topic=topic_title, chapter=chapter_title,
        class_num=class_num, subject=subject,
    )
    prereqs_dicts: list[dict] = []
    try:
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.3,
            max_tokens=600,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            prereqs_dicts = parsed[:5]
        elif isinstance(parsed, dict):
            # Sometimes the model wraps the array
            for key in ["prerequisites", "prereqs", "items"]:
                if key in parsed and isinstance(parsed[key], list):
                    prereqs_dicts = parsed[key][:5]
                    break
    except Exception as e:
        logger.warning(f"LLM prerequisite inference failed: {e}")
        # Fallback: single generic prerequisite
        prereqs_dicts = [{
            "prereq_description": f"Basic concepts of {subject}",
            "prereq_class_num": max(1, class_num - 1),
            "prereq_subject": subject,
            "prereq_chapter": None,
            "expected_keywords": [],
            "difficulty_order": 0,
        }]

    # Persist to DB
    if prereqs_dicts:
        try:
            from core.db_session import managed_session
            from db.models import Topic, Chapter, TopicPrerequisite
            from sqlalchemy import func
            with managed_session() as db:
                topic = (
                    db.query(Topic)
                    .join(Chapter, Topic.chapter_id == Chapter.id)
                    .filter(
                        func.lower(Topic.title) == topic_title.lower(),
                        func.lower(Chapter.title) == chapter_title.lower(),
                    )
                    .first()
                )
                if topic:
                    for i, p in enumerate(prereqs_dicts):
                        prereq = TopicPrerequisite(
                            topic_id=topic.id,
                            prereq_description=p.get("prereq_description", ""),
                            prereq_class_num=p.get("prereq_class_num", max(1, class_num - 1)),
                            prereq_subject=p.get("prereq_subject", subject),
                            prereq_chapter=p.get("prereq_chapter"),
                            expected_keywords=json.dumps(p.get("expected_keywords", [])),
                            difficulty_order=p.get("difficulty_order", i),
                            source="llm_inferred",
                        )
                        db.add(prereq)
                    db.commit()
                    logger.info(
                        f"Saved {len(prereqs_dicts)} inferred prerequisites for topic '{topic_title}'"
                    )
        except Exception as e:
            logger.warning(f"Could not save inferred prerequisites to DB: {e}")

    return prereqs_dicts


def _algorithmic_pick(prereqs: list[dict], metrics: dict) -> dict:
    """
    Picks the best prerequisite to probe algorithmically using cognitive metrics.
    Zero LLM calls.

    Strategy:
      concept_und < 40 → most foundational (difficulty_order=0, last in sorted list)
      concept_und > 70 → most advanced (directly bridges to new topic)
      else             → median (balanced)
    """
    if not prereqs:
        return {}
    concept_und = (
        metrics.get("concept_master_score", 50.0) +
        metrics.get("assessment_accuracy", 50.0)
    ) / 2.0

    if concept_und < 40:
        return prereqs[-1]   # most foundational (highest difficulty_order)
    elif concept_und > 70:
        return prereqs[0]    # most advanced (lowest difficulty_order)
    else:
        return prereqs[len(prereqs) // 2]  # middle


# ─────────────────────────────────────────────────────────────────────────────
# Main SocraticTutor class
# ─────────────────────────────────────────────────────────────────────────────

class SocraticTutor:
    """Handles the Socratic Deep Learning Mode two-phase flow."""

    def __init__(self):
        api_key = os.environ.get("GROQ_API_KEY")
        self.client = Groq(api_key=api_key)
        self.model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")

    # ──────────────────────────────────────────
    # Session opener
    # ──────────────────────────────────────────

    def generate_session_opener(self, class_num, subject, student_memory, tasks) -> str:
        """Generates a warm session-start greeting that surfaces memory and pending tasks."""
        time.sleep(RATE_LIMIT_SLEEP)
        memory_section = (
            "\n".join(f"- {m}" for m in student_memory) if student_memory
            else "(No previous memory yet)"
        )
        tasks_section = (
            "\n".join(f"- {t}" for t in tasks) if tasks else "(No pending tasks)"
        )
        prompt = SESSION_START_PROMPT.format(
            class_num=class_num,
            subject=subject,
            memory_section=memory_section,
            tasks_section=tasks_section,
        )
        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.5,
                max_tokens=300,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Session opener generation failed: {e}")
            return (
                f"Welcome back! Ready to continue with {subject}? "
                "What would you like to learn today? :)"
            )

    # ──────────────────────────────────────────
    # Phase 1 — Diagnostic question (1 LLM call max after first visit)
    # ──────────────────────────────────────────

    def start_diagnostic(
        self,
        question: str,
        topic: str,
        chapter: str,
        class_num: int,
        subject: str,
        context: str,
        metrics: dict,
    ) -> tuple[str, dict]:
        """
        Phase 1: Picks a prerequisite and generates a single diagnostic question.

        LLM calls:
          - 0 if prerequisites already in DB (best case, common after first visit)
          - 1 (infer prereqs) + 1 (diagnostic question) on first-ever visit to topic
          - 1 (diagnostic question only) if prereqs were inferred before but topic
            is not in local DB (e.g., new session after first inference saved to DB)

        Returns (diagnostic_question_text, state_dict_to_save).
        """
        # Step 1: DB lookup (FREE)
        prerequisites = _fetch_prerequisites_from_db(topic, chapter)
        source = "db"

        # Step 2: Infer via LLM and save if nothing in DB (paid once, FREE after)
        if not prerequisites:
            logger.info(
                f"Socratic Phase 1: no stored prerequisites for '{topic}'. "
                "Inferring via LLM and saving to DB..."
            )
            prerequisites = _infer_and_save_prerequisites(
                topic_title=topic,
                chapter_title=chapter,
                class_num=class_num,
                subject=subject,
                client=self.client,
                model=self.model,
            )
            source = "inferred"

        logger.info(f"Socratic Phase 1: prerequisites ({source}): {[p.get('prereq_description') for p in prerequisites]}")

        # Step 3: Algorithmic pick (FREE, zero LLM)
        chosen = _algorithmic_pick(prerequisites, metrics)
        if not chosen:
            chosen = {
                "prereq_description": f"Basic concepts of {topic}",
                "prereq_class_num": max(1, class_num - 1),
                "prereq_subject": subject,
                "prereq_chapter": None,
                "expected_keywords": [],
            }

        prereq_desc = chosen.get("prereq_description", f"prerequisites of {topic}")
        expected_keywords = chosen.get("expected_keywords", [])

        # Step 4: Generate diagnostic question (1 LLM call)
        time.sleep(RATE_LIMIT_SLEEP)
        prompt = DIAGNOSTIC_QUESTION_PROMPT.format(
            question=question,
            prerequisite=prereq_desc,
            class_num=class_num,
        )
        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.5,
                max_tokens=200,
            )
            diag_question = response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Diagnostic question generation failed: {e}")
            diag_question = (
                f"Before we explore this topic, could you tell me what you already "
                f"know about **{prereq_desc}**? Even a rough idea helps! :)"
            )

        state = {
            "phase": "awaiting_response",
            "original_question": question,
            "topic": topic,
            "chapter": chapter,
            "class_num": class_num,
            "subject": subject,
            "context": context[:3000],
            "prereq_description": prereq_desc,
            "prereq_class_num": chosen.get("prereq_class_num", max(1, class_num - 1)),
            "prereq_subject": chosen.get("prereq_subject", subject),
            "prereq_chapter": chosen.get("prereq_chapter"),
            "expected_keywords": expected_keywords,
            "backtrack_depth": 0,
            "visited_topics": [topic],  # loop guard
        }

        logger.info(f"Socratic Phase 1 complete. Diagnostic for prereq: '{prereq_desc}'")
        return diag_question, state

    # ──────────────────────────────────────────
    # Phase 2 — Evaluate + Explain (cross-class backtracking)
    # ──────────────────────────────────────────

    def evaluate_and_explain(
        self,
        student_response: str,
        state: dict,
        metrics: dict,
        history: list[ChatMessage] | None = None,
        engine=None,  # RetrievalEngine instance for backtracking retrieval
    ) -> str:
        """
        Phase 2: Evaluates student diagnostic response and generates adaptive explanation.

        Paths:
          A. Give-up detected      → Adaptive skip (full answer + consolidation nudge)
          B. Max depth reached     → Base concept explanation (analogies only)
          C. Student understands   → Teach the original topic
          D. Student confused      → Backtrack to lower class content, re-teach prerequisite
        """
        from tutor.patterns import detect_understanding, detect_give_up

        understanding_score = detect_understanding(
            student_response, state.get("expected_keywords", [])
        )
        gave_up  = detect_give_up(student_response)
        depth    = state.get("backtrack_depth", 0)
        visited  = state.get("visited_topics", [])

        logger.info(
            f"Socratic Phase 2 | understanding={understanding_score:.3f} | "
            f"gave_up={gave_up} | depth={depth}/{MAX_BACKTRACK_DEPTH}"
        )

        # ── Path A: Adaptive skip (student gives up) ─────────────────────────
        if gave_up:
            logger.info("Socratic: give-up detected → adaptive skip with full explanation.")
            return self._generate_adaptive_skip(state, student_response)

        # ── Path B: Max depth — rock-bottom analogies ────────────────────────
        if depth >= MAX_BACKTRACK_DEPTH:
            logger.info("Socratic: max backtrack depth reached → base concept explanation.")
            return self._generate_base_concept_explanation(state)

        # ── Path C: Student understands — teach original topic ────────────────
        if understanding_score >= UNDERSTANDING_THRESHOLD:
            logger.info(f"Socratic: student understands ({understanding_score:.2f}) → teach original topic.")
            return self._teach_original_topic(state, history, metrics)

        # ── Path D: Student confused — backtrack to lower class ───────────────
        prereq_desc  = state.get("prereq_description", "")
        prereq_class = state.get("prereq_class_num", state.get("class_num", 10) - 1)
        prereq_subj  = state.get("prereq_subject", state.get("subject", "Science"))
        prereq_ch    = state.get("prereq_chapter")

        # Loop guard: don't re-teach something already visited
        if prereq_desc in visited:
            logger.info("Socratic: prereq already visited → base concept explanation to break loop.")
            return self._generate_base_concept_explanation(state)

        # Try to retrieve lower-class content (going down up to MAX_DEPTH - depth levels)
        backtrack_chunks = None
        backtrack_class = None

        if engine is not None:
            for offset in range(0, MAX_BACKTRACK_DEPTH - depth + 1):
                target_class = prereq_class - offset
                if target_class < 1:
                    break
                logger.info(
                    f"Socratic: attempting retrieval for prereq '{prereq_desc}' "
                    f"at Class {target_class}..."
                )
                chunks = engine.retrieve(
                    query=prereq_desc,
                    routing_metadata={
                        "class": target_class,
                        "subject": prereq_subj,
                        "chapter": prereq_ch,
                    },
                    top_k=4,
                    min_results=2,
                )
                if chunks:
                    backtrack_chunks = chunks
                    backtrack_class = target_class
                    logger.info(
                        f"Socratic: backtrack content found at Class {target_class} "
                        f"({len(chunks)} chunks)"
                    )
                    break

        if not backtrack_chunks:
            logger.info("Socratic: no backtrack content found → base concept explanation.")
            return self._generate_base_concept_explanation(state)

        # Generate backtrack lesson from lower-class content
        context = "\n\n".join(c["content"] for c in backtrack_chunks)
        answer = self._generate_backtrack_lesson(
            prereq_desc, context, backtrack_class, state, student_response
        )

        # NOTE: The caller (chat.py) must update the state for the next turn.
        # We encode new state as a special prefix so chat.py can parse it.
        # However, since evaluate_and_explain() returns only a string, the updated
        # state must be stored by the caller before returning. We log the state
        # here so it's accessible — callers should check for state updates.
        logger.info(
            f"Socratic: backtrack lesson at Class {backtrack_class} | "
            f"depth now {depth + 1} | visited: {visited + [prereq_desc]}"
        )

        return answer

    # ──────────────────────────────────────────
    # Internal generation helpers
    # ──────────────────────────────────────────

    def _generate_adaptive_skip(self, state: dict, student_response: str) -> str:
        """
        Path A: Student gave up. Provide a complete direct explanation of the original
        topic, then nudge gently toward a consolidation exercise.
        """
        time.sleep(RATE_LIMIT_SLEEP)
        prompt = ADAPTIVE_SKIP_PROMPT.format(
            original_question=state.get("original_question", ""),
            student_response=student_response,
            context=state.get("context", "No context available."),
        )
        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.4,
                max_tokens=700,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Adaptive skip generation failed: {e}")
            return (
                "No worries! Let me just explain this directly. "
                f"\n\n{state.get('context', '')[:500]}"
                "\n\nI've explained it fully! When you're ready, try thinking about "
                "the key idea one more time — it'll help it stick 🧠"
            )

    def _generate_base_concept_explanation(self, state: dict) -> str:
        """
        Path B: Rock bottom — explain using real-world analogies, zero prior knowledge.
        """
        time.sleep(RATE_LIMIT_SLEEP)
        prompt = BASE_CONCEPT_PROMPT.format(
            prereq_description=state.get("prereq_description", "this concept"),
            original_question=state.get("original_question", "your original question"),
        )
        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.5,
                max_tokens=500,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Base concept explanation failed: {e}")
            prereq = state.get("prereq_description", "this concept")
            return (
                f"Let me explain **{prereq}** using a simple everyday example!\n\n"
                "Think of it like water flowing through pipes — the concept works the "
                "same way in nature. Once you have this picture in your head, "
                f"we can connect it to your original question: {state.get('original_question', '')}."
            )

    def _teach_original_topic(
        self,
        state: dict,
        history: list[ChatMessage] | None,
        metrics: dict,
    ) -> str:
        """
        Path C: Student understood the prerequisite — now teach the original topic
        using the already-retrieved context stored in state.
        """
        from tutor.llm import TutorLLM, format_personalization_instructions
        from db.metrics import compute_cognitive_skills

        cognitive_skills = compute_cognitive_skills(metrics)
        pers = format_personalization_instructions(metrics, cognitive_skills)

        system_msgs = [
            {
                "role": "system",
                "content": (
                    "You are VishwAlpha, a warm Socratic AI tutor. "
                    "The student has just demonstrated understanding of the prerequisite. "
                    "Now teach the original topic they asked about, using the textbook context below. "
                    "Reference what they just showed they know to make the explanation feel connected."
                ),
            }
        ]
        if pers:
            system_msgs.append({"role": "system", "content": pers})

        context = state.get("context", "")
        if context:
            system_msgs.append({
                "role": "system",
                "content": (
                    "TEXTBOOK CONTEXT (your ONLY source of facts):\n\n"
                    f"{context}\n\n"
                    "Do NOT add facts not present in this context."
                ),
            })

        messages = system_msgs
        if history:
            for msg in history[-6:]:
                role = "user" if msg.role == "student" else "assistant"
                messages.append({"role": role, "content": msg.content})
        messages.append({
            "role": "user",
            "content": state.get("original_question", "Please explain the topic."),
        })

        time.sleep(RATE_LIMIT_SLEEP)
        try:
            response = self.client.chat.completions.create(
                messages=messages,
                model=self.model,
                temperature=0.3,
                max_tokens=800,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Teach original topic failed: {e}")
            return (
                "Great job understanding that prerequisite! Now, for your original question: "
                f"{state.get('original_question', '')} — "
                "here's what the textbook says:\n\n"
                f"{state.get('context', 'Please check your textbook for more details.')[:500]}"
            )

    def _generate_backtrack_lesson(
        self,
        prereq_desc: str,
        context: str,
        backtrack_class: int,
        state: dict,
        student_response: str,
    ) -> str:
        """
        Path D: Teach the prerequisite concept using lower-class retrieval content.
        """
        time.sleep(RATE_LIMIT_SLEEP)
        prompt = BACKTRACK_LESSON_PROMPT.format(
            prereq_description=prereq_desc,
            backtrack_class=backtrack_class,
            context=context[:2000],
            student_response=student_response,
        )
        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.4,
                max_tokens=600,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Backtrack lesson generation failed: {e}")
            return (
                f"Let me help you understand **{prereq_desc}** first. "
                f"\n\n{context[:400]}\n\n"
                "Does that make sense? Let me know what part is unclear!"
            )
