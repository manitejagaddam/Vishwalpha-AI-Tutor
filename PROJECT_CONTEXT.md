# VishwAlpha AI Tutor - Project Context

## Project Overview
VishwAlpha is a premium, AI-powered personalised tutoring system designed specifically for the Indian NCERT curriculum (Class 6-12). It uses a sophisticated RAG (Retrieval-Augmented Generation) pipeline to provide grounded, syllabus-accurate support for students.

## Tech Stack
- **Core Logic**: Python 3.10+
- **LLM Brain**: Llama 3.1 via Groq (for ultra-low latency)
- **Vector DB**: Pg-Vector (semantic search)
- **Relational DB**: PostgreSQL (via SQLAlchemy)
- **Frameworks**: FastAPI (Backend) & Streamlit (Frontend)
- **Embeddings**: Sentence-Transformers (local)

## Recently Completed Architecture & Database Upgrades
The database and core logic have been fully upgraded to the "Final" Schema to make the AI tutor understand student cognition, behaviour, and learning trajectories.

**Implemented Database Enhancements:**
- Added `student_learning_preferences` (AI-detected/self-declared learning styles), `student_streaks`, `student_goals`, and `session_insights` tables.
- Enhanced `students` with `board_id` and language/learning style preferences.
- Enhanced `student_subject_profiles` with `bloom_level_avg`, session durations, turn/quiz counts, and emotional indexes (frustration/confidence).
- Fully wired `student_topic_mastery` to track Bloom's level, spaced repetition review dates, and decay rates.
- Enhanced analytics on `conversation_sessions` and `conversation_messages` (response times, sentiment, Bloom's level tracking).
- Upgraded `quiz_questions` with difficulty tags and Bloom's level tracking.
- Fixed ORM vs. DB column mismatches for runtime stability.

**Implemented Code Logic:**
- `cognitive_repo.py`: Topic mastery is fully wired and student streaks are updated on activity.
- `chat_orchestrator.py`: The orchestrator actively tracks session lengths, response times, message sentiments, passes topic mastery and learning preferences to the LLM, and fetches spaced repetition topics due for review.
- `tutor_llm.py`: Injects weak-topic awareness and learning styles directly into the system prompt.
- `quiz_service.py`: Concept completions automatically trigger quiz suggestions, and quizzes include difficulty and Bloom's level parameters.

## Current Status & Active Tasks
- *To be determined — waiting for next feature or bug fix assignment.*

## Open Architectural Decisions
1. **Board Support Routing**: The database supports `boards`, `classes`, `subjects`, `chapters`, and `topics`, but routing currently relies on a flat string-based approach (`curriculum_routing` and `curriculum_content`). 
   - *Decision needed*: Should we wire the curriculum hierarchy tables into the routing/retrieval pipeline for future multi-board support, or drop them and stick to the current string-based approach?
