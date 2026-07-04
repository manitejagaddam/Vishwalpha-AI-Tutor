"""
tutor/socratic.py
─────────────────
Socratic Deep Learning Mode for VishwAlpha.

Two-phase flow (per question in deep mode):
  Phase 1 — start_diagnostic():
    - Reads prerequisites for the routed topic from the DB.
    - If no prerequisites exist, calls the LLM to infer simpler prerequisite
      concepts on the fly.
    - Picks the best prerequisite to probe based on the student cognitive scores.
    - Returns a single warm diagnostic question (NOT the answer).

  Phase 2 — evaluate_and_explain():
    - Reads the student diagnostic answer.
    - Evaluates their actual understanding level.
    - Generates a Socratic, adaptive explanation bridging their knowledge to the new concept.
"""
import os
import json
import time
import logging
from groq import Groq
from schemas import ChatMessage

logger = logging.getLogger(__name__)

RATE_LIMIT_SLEEP = 0.3  # small courtesy delay; ingestion uses its own 2-3s delay

# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────

INFER_PREREQUISITES_PROMPT = """You are an NCERT curriculum expert.
A student is about to study this topic: "{topic}" (from: {chapter}, Class {class_num} {subject}).

The topic has no prerequisites stored. Infer 3-5 simpler prerequisite concepts or topics
a student must understand BEFORE studying this topic, based on standard NCERT syllabus progression.

Return ONLY a JSON array of strings:
["prerequisite 1", "prerequisite 2", "prerequisite 3"]"""

PICK_PREREQUISITE_PROMPT = """You are a NCERT tutor making a personalized diagnostic plan.

The student is about to ask about: "{question}"
Topic: "{topic}"
Available prerequisite concepts: {prerequisites}

Student cognitive profile:
- Concept Understanding: {concept_pct}%
- Cognitive Depth: {depth_pct}%
- Knowledge Stability: {stability_pct}%

Based on this profile, pick the SINGLE most important prerequisite to probe.
If concept understanding is LOW (<40%), pick the most foundational one.
If concept understanding is HIGH (>70%), pick the one that bridges most directly to the new topic.

Return ONLY a JSON object:
{{"chosen_prerequisite": "the chosen prerequisite concept", "reason": "brief reason"}}"""

DIAGNOSTIC_QUESTION_PROMPT = """You are VishwAlpha, a warm and encouraging AI tutor for Indian school students studying NCERT curriculum.

The student has just asked about: "{question}"

Before explaining this topic, you want to understand what they already know about a foundational prerequisite: "{prerequisite}"

Write a single, friendly diagnostic question that:
1. Seamlessly bridges from their question to the prerequisite. (e.g., "That's a great question about [topic]! To help me explain it best, could you first tell me...")
2. Does NOT reveal the answer to their original question.
3. Naturally checks their understanding of "{prerequisite}".
4. Sounds like a human tutor casually chatting, not an examiner giving a test.

Write ONLY the conversational response and diagnostic question, no extra text."""

EVALUATE_AND_EXPLAIN_PROMPT = """You are VishwAlpha, a conversational and highly adaptive Socratic AI tutor for Indian school students (NCERT curriculum).

ORIGINAL QUESTION from the student: "{original_question}"
PREREQUISITE CONCEPT that was probed: "{prerequisite}"
STUDENT RESPONSE to the diagnostic: "{student_response}"
TEXTBOOK CONTEXT (your ONLY factual source):
{context}

STUDENT COGNITIVE PROFILE:
- Concept Understanding: {concept_pct}%
- Cognitive Depth: {depth_pct}%
- Learning Effort: {effort_pct}%

YOUR TASK:
Act as a supportive peer-tutor. Write a single, cohesive, conversational response that does the following smoothly:
1. React naturally to their diagnostic response (warmly validating what they got right, or gently clarifying any confusion without making them feel bad).
2. Transition smoothly into explaining their original question.
3. Teach the topic using the textbook context, but tailor your depth based on their cognitive profile:
   - If Concept Understanding < 40%: use very simple language, everyday analogies, and avoid jargon.
   - If Cognitive Depth > 70%: challenge them slightly with the "why" behind the facts.
4. End your explanation with a light, thought-provoking question to keep the conversation flowing.

STRICT GROUNDING RULE: ONLY use facts from the TEXTBOOK CONTEXT. Do not hallucinate external facts. Make it feel like a natural conversation, not a structured list of bullet points."""

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
# Prerequisite helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_prerequisites_from_db(topic_title: str, chapter_title: str) -> list:
    """Fetches stored prerequisites for a topic from the topics table."""
    try:
        from core.db_session import managed_session
        from db.models import Topic, Chapter
        with managed_session() as db:
            topic = (
                db.query(Topic)
                .join(Chapter, Topic.chapter_id == Chapter.id)
                .filter(
                    Topic.title == topic_title,
                    Chapter.title == chapter_title,
                )
                .first()
            )
            if topic and topic.prerequisites:
                prereqs = json.loads(topic.prerequisites)
                if isinstance(prereqs, list) and prereqs:
                    return prereqs
    except Exception as e:
        logger.warning(f"Could not fetch prerequisites from DB: {e}")
    return []


def _infer_prerequisites_via_llm(topic, chapter, class_num, subject, client, model) -> list:
    """Calls the LLM to infer prerequisite concepts when none are stored in the DB."""
    time.sleep(RATE_LIMIT_SLEEP)
    prompt = INFER_PREREQUISITES_PROMPT.format(
        topic=topic, chapter=chapter, class_num=class_num, subject=subject
    )
    try:
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.3,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed[:5]
        for key in ["prerequisites", "concepts", "topics"]:
            if key in parsed and isinstance(parsed[key], list):
                return parsed[key][:5]
    except Exception as e:
        logger.warning(f"LLM prerequisite inference failed: {e}")
    return [f"Basic concepts of {subject}", f"Introduction to {topic}"]


def _pick_best_prerequisite(question, topic, prerequisites, metrics, client, model) -> str:
    """Uses the LLM to pick the most relevant prerequisite given the cognitive profile."""
    if len(prerequisites) == 1:
        return prerequisites[0]
    time.sleep(RATE_LIMIT_SLEEP)
    concept_pct = metrics.get("concept_master_score", 50.0)
    depth_pct = metrics.get("cognitive_thinking_level", 50.0)
    stability_pct = metrics.get("knowledge_retention", 50.0)
    prompt = PICK_PREREQUISITE_PROMPT.format(
        question=question,
        topic=topic,
        prerequisites=json.dumps(prerequisites),
        concept_pct=round(concept_pct, 1),
        depth_pct=round(depth_pct, 1),
        stability_pct=round(stability_pct, 1),
    )
    try:
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.2,
            max_tokens=150,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content.strip())
        chosen = data.get("chosen_prerequisite", prerequisites[0])
        logger.info(f"  Socratic: chose prerequisite '{chosen}' — {data.get('reason', '')}")
        return chosen
    except Exception as e:
        logger.warning(f"Prerequisite selection LLM call failed: {e}")
        if metrics.get("concept_master_score", 50.0) < 40:
            return prerequisites[0]
        return prerequisites[-1]


# ─────────────────────────────────────────────────────────────────────────────
# Main SocraticTutor class
# ─────────────────────────────────────────────────────────────────────────────

class SocraticTutor:
    """Handles the Socratic Deep Learning Mode two-phase flow."""

    def __init__(self):
        api_key = os.environ.get("GROQ_API_KEY")
        self.client = Groq(api_key=api_key)
        self.model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

    def generate_session_opener(self, class_num, subject, student_memory, tasks) -> str:
        """Generates a warm session-start greeting that surfaces memory and pending tasks."""
        time.sleep(RATE_LIMIT_SLEEP)
        memory_section = (
            "\n".join(f"- {m}" for m in student_memory) if student_memory else "(No previous memory yet)"
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
            return f"Welcome back! Ready to continue with {subject}? What would you like to learn today? :)"

    def start_diagnostic(self, question, topic, chapter, class_num, subject, context, metrics) -> tuple:
        """
        Phase 1: Picks a prerequisite and generates a single diagnostic question.
        Returns (diagnostic_question_text, state_dict_to_save).
        """
        # 1. Try DB first
        prerequisites = _fetch_prerequisites_from_db(topic, chapter)
        source = "db"

        # 2. If none stored, infer via LLM
        if not prerequisites:
            logger.info(f"  Socratic: no stored prerequisites for '{topic}'. Inferring via LLM...")
            prerequisites = _infer_prerequisites_via_llm(
                topic=topic, chapter=chapter, class_num=class_num, subject=subject,
                client=self.client, model=self.model,
            )
            source = "inferred"

        logger.info(f"  Socratic: prerequisites ({source}): {prerequisites}")

        # 3. Pick best to probe
        chosen = _pick_best_prerequisite(
            question=question, topic=topic, prerequisites=prerequisites,
            metrics=metrics, client=self.client, model=self.model,
        )

        # 4. Generate the diagnostic question
        time.sleep(RATE_LIMIT_SLEEP)
        prompt = DIAGNOSTIC_QUESTION_PROMPT.format(
            question=question, prerequisite=chosen, class_num=class_num,
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
                f"know about **{chosen}**? Even a rough idea helps! :)"
            )

        state = {
            "phase": "awaiting_response",
            "original_question": question,
            "topic": topic,
            "chapter": chapter,
            "prerequisite": chosen,
            "context": context[:3000],
        }

        logger.info(f"  Socratic: diagnostic question generated for prerequisite '{chosen}'")
        return diag_question, state

    def evaluate_and_explain(self, student_response, state, metrics, history=None) -> str:
        """
        Phase 2: Evaluates the student diagnostic response and generates
        a tailored Socratic explanation of the original topic.
        """
        time.sleep(RATE_LIMIT_SLEEP)

        concept_pct = round(metrics.get("concept_master_score", 50.0), 1)
        depth_pct = round(metrics.get("cognitive_thinking_level", 50.0), 1)
        effort_pct = round(metrics.get("practice_intensity", 50.0), 1)

        prompt = EVALUATE_AND_EXPLAIN_PROMPT.format(
            original_question=state.get("original_question", ""),
            prerequisite=state.get("prerequisite", ""),
            student_response=student_response,
            context=state.get("context", "No context available."),
            concept_pct=concept_pct,
            depth_pct=depth_pct,
            effort_pct=effort_pct,
        )
        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.3,
                max_tokens=900,
            )
            answer = response.choices[0].message.content.strip()
            logger.info(f"  Socratic: evaluated + explained ({len(answer)} chars)")
            return answer
        except Exception as e:
            logger.error(f"Evaluate-and-explain generation failed: {e}")
            return "I had trouble generating a response right now. Please try asking your question again!"
