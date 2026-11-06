"""
tests/test_v4_core.py
──────────────────────
Unit tests for Version 4 Core:
  1. Grade-adaptive pedagogical boundary generation (Classes 6-8, 9-10, 11-12)
  2. V4 direct tutor prompt formatting without RAG context
  3. Fast syllabus topic resolution
"""
import pytest
from app.prompts import get_grade_boundary_instructions, V4_DIRECT_TUTOR_PROMPT
from app.services.chat_orchestrator import _fast_resolve_topic_from_syllabus


def test_grade_boundaries_class_tiers():
    # Tier 1: Middle School (Classes 6-8)
    b_6 = get_grade_boundary_instructions(6)
    assert "Class 6 - Middle School" in b_6
    assert "DO NOT use advanced mathematical formulas" in b_6

    b_8 = get_grade_boundary_instructions(8)
    assert "Class 8 - Middle School" in b_8

    # Tier 2: Secondary / Board Foundation (Classes 9-10)
    b_9 = get_grade_boundary_instructions(9)
    assert "Class 9 - Secondary / Board Foundation" in b_9
    assert "balanced chemical equations" in b_9

    b_10 = get_grade_boundary_instructions(10)
    assert "Class 10 - Secondary / Board Foundation" in b_10

    # Tier 3: Senior Secondary / Competitive (Classes 11-12)
    b_11 = get_grade_boundary_instructions(11)
    assert "Class 11 - Senior Secondary / Competitive Prep" in b_11
    assert "JEE Main/Advanced, NEET" in b_11

    b_12 = get_grade_boundary_instructions(12)
    assert "Class 12 - Senior Secondary / Competitive Prep" in b_12


def test_v4_direct_tutor_prompt_formatting():
    bounds = get_grade_boundary_instructions(10)
    formatted = V4_DIRECT_TUTOR_PROMPT.format(
        grade_boundaries=bounds,
        subject_context="Class 10, Subject: Science\n- Ch 1: Chemical Reactions and Equations",
        student_progress="✅ Mastered: Chemical Reactions (90%)",
        student_memory="- Exam in March",
        teaching_style="- Student prefers analogies",
        weak_topics_section="- Weak in balancing equations",
        review_section="- Review acids and bases",
        attachment_section="",
    )
    assert "VishwAlpha" in formatted
    assert "Class 10 - Secondary / Board Foundation" in formatted
    assert "Chemical Reactions and Equations" in formatted
    assert "Exam in March" in formatted
    assert "{context}" not in formatted


def test_fast_resolve_topic_fallback():
    # If subject_id is None, returns last topic or empty
    ch, top, tid = _fast_resolve_topic_from_syllabus(
        question="Tell me about something",
        subject_id=None,
        class_num=10,
        conv_last_topic="Electricity"
    )
    assert top == "Electricity"
    assert tid is None

