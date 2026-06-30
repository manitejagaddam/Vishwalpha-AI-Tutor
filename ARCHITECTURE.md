# VishwAlpha AI Tutor: System Architecture & Data Flow

This document provides a comprehensive overview of the VishwAlpha AI Tutor application. It explains the purpose of each file, the high-level architecture, and the step-by-step data flow of how a user's question is processed.

---

## 🏗️ 1. High-Level Architecture

The application is built on a modern AI/RAG (Retrieval-Augmented Generation) stack with a specialized "Cognitive Middleware" layer to track and adapt to the student's learning state.

*   **Frontend**: Streamlit (Interactive Chat, Developer Panels, Cognitive Dashboards).
*   **Backend/Orchestration**: Python (FastAPI available, though Streamlit currently imports the orchestrator directly for speed).
*   **Database (Relational & State)**: PostgreSQL (via SQLAlchemy) stores user sessions, chat history, and cognitive tracking scores.
*   **Vector Database (Retrieval)**: Qdrant stores embedded textbook chunks for semantic search.
*   **LLM Provider**: Groq (Llama 3) used for question classification, cognitive metric evaluation, and final tutor response generation.
*   **Embeddings**: Sentence-Transformers (running locally) converts text to vector embeddings.

---

## 📂 2. Directory & File Breakdown

### Root Directory
*   `main.py`: The entry point for running backend services. It contains commands to start the FastAPI server (`--serve`), run the ingestion pipeline (`--ingest`), or start a CLI chat (`--chat`).
*   `api.py`: FastAPI application definition. Contains REST endpoints (e.g., `POST /chat`, `POST /session/{id}/metrics`) for external clients.
*   `streamlit_app.py`: The Streamlit frontend. It renders the chat UI, the sidebar (profile presets, sliders), and the right-hand developer panel (Chunks, Prompt Inspector, Cognitive Evaluation).
*   `schemas.py`: Pydantic models. Defines the exact data structures (e.g., `ChatRequest`, `ChatResponse`, `CognitiveSkills`) passed between functions, ensuring type safety.

### `tutor/` (The Brain & Orchestrator)
*   `chat.py`: **The Orchestrator.** This is the core pipeline. It receives a question, runs the cognitive middleware, classifies the intent, retrieves data from Qdrant, calls the LLM, and saves the result to the database.
*   `llm.py`: **The Generator.** Constructs the final prompt sent to Groq. It dynamically injects textbook context, conversation history, and the student's personalized cognitive skills to force the LLM to adapt its teaching style.

### `db/` (Database & State Management)
*   `database.py`: Handles PostgreSQL connection pooling and engine initialization via SQLAlchemy.
*   `models.py`: Defines the SQL tables: `ConversationSession` (stores the 10 raw cognitive scores) and `Turn` (stores message history).
*   `memory.py`: Functions to fetch chat history, create sessions, and save turns.
*   `metrics.py`: **The Cognitive Middleware.** Contains the logic that evaluates a student's input using a fast LLM call, determines how to adjust their 10 raw tracking scores (e.g., increase `concept_master_score`), and maps those raw scores into 5 high-level `Cognitive Skills`.

### `retrieval/` & `routing/` (RAG Engine)
*   `routing/router.py` (`SemanticRouter`): Analyzes a student's question to determine the target Class, Subject, Chapter, and Topic.
*   `routing/vector_store.py`: Wraps the Qdrant client, handling collection creation, payload formatting, and similarity search.
*   `retrieval/engine.py` (`RetrievalEngine`): Executes the search against Qdrant using the constraints provided by the router.
*   `retrieval/reranker.py`: Compresses and formats the retrieved chunks into a clean context string for the LLM.

### `ingestion/` (Data Pipeline)
*   `pipeline.py`: The script that reads PDF textbooks, extracts text (using tools like `pdfminer.six` or `PaddleOCR`), splits the text into logical chunks, generates vector embeddings via `SentenceTransformers`, and uploads them to Qdrant.

---

## 🔄 3. Information Passing Architecture (The Data Flow)

When a student types a question in the Streamlit app, here is the exact sequence of events:

### Step 1: User Input & Initialization
1.  **Frontend (`streamlit_app.py`)**: The user submits a question. The app calls `chat()` from `tutor/chat.py`, passing a `ChatRequest` (containing `session_id`, `question`, `class_num`, `subject`).
2.  **Memory Load (`db/memory.py`)**: The system fetches the active `ConversationSession` from PostgreSQL and loads the recent chat history.

### Step 2: Cognitive Middleware Evaluation
3.  **Metrics Update (`db/metrics.py`)**: 
    *   The `adjust_student_metrics_pre_generation()` function runs a fast LLM call analyzing the *student's question* against their *history*.
    *   It outputs adjustments (increase, decrease, or constant) for 10 raw tracking metrics (e.g., `attempt_persistence`, `cognitive_thinking_level`).
    *   These updates are immediately committed to the PostgreSQL session row.
4.  **Skill Mapping (`db/metrics.py`)**: The 10 updated raw scores are mathematically aggregated into 5 core **Cognitive Skills** (e.g., Concept Understanding, Learning Adaptability).

### Step 3: Intent Classification
5.  **Classifier (`tutor/chat.py`)**: A fast LLM call determines if the question is `"conversational"` (e.g., "Yes I understand") or `"curriculum"` (e.g., "What is an acid?").

### Step 4: Retrieval (If Curriculum)
6.  **Semantic Routing (`routing/router.py`)**: The question is parsed to extract metadata constraints (e.g., Chapter: "Acids, Bases and Salts").
7.  **Vector Search (`retrieval/engine.py`)**: The system embeds the question and queries Qdrant.
8.  **Confidence Gating**: The retrieved chunks are filtered. If no chunk has a cosine similarity score above `0.60`, the system blocks the LLM and returns a polite refusal to prevent hallucinations.
9.  **Compression (`retrieval/reranker.py`)**: Valid chunks are combined into a `context` string.

### Step 5: Personalized Generation
10. **Prompt Construction (`tutor/llm.py`)**: `TutorLLM` builds a massive system prompt. It injects:
    *   The retrieved textbook `context`.
    *   The previous conversation `history`.
    *   The student's 5 `Cognitive Skills` (from Step 2).
    *   Strict pedagogical rules based on those skills (e.g., "Student's Learning Adaptability is low (30%), break steps down into smaller pieces").
11. **LLM Inference**: The prompt is sent to Groq (Llama 3), which streams back the personalized educational response.

### Step 6: Persistence & Display
12. **Database Save (`db/memory.py`)**: The student's question and the tutor's answer are saved as a new `Turn` in PostgreSQL.
13. **UI Render (`streamlit_app.py`)**: The response is displayed to the user. Simultaneously, the right-hand panel updates to show the retrieved chunks, the exact prompt sent, and the real-time cognitive score adjustments.
