# VishwAlpha Database Schema Guide

This document provides a detailed breakdown of every table in your PostgreSQL (Supabase) database. The database is designed specifically for an AI-powered personalized tutoring system. It is logically divided into five major domains:

---

## 1. Platform & Identity (`platform.py`)
These tables handle user authentication, roles, and core profiles.

### `users`
- **What it stores**: The core identity of every person logging into the app.
- **Key Columns**: `id` (UUID), `username`, `email`, `password_hash`, `role` (student/admin), `class_num` (their current grade level).
- **Usage**: Used for authentication (login/register) and acts as the root node that everything else (chats, quizzes, preferences) links back to.

### `student_profiles`
- **What it stores**: Additional non-authentication profile data specific to students.
- **Key Columns**: `user_id` (FK to users), `board_id` (e.g., NCERT), `preferred_lang` (e.g., 'en', 'hi'), `learning_style`.
- **Usage**: Used to customize the app interface and initial AI system prompts based on their board and language.

---

## 2. Curriculum & Content (`content.py`)
These tables represent the textbook data, structuring it hierarchically so the RAG (Retrieval-Augmented Generation) system can find specific textbook sections.

**The Golden Hierarchy**: `Board` → `SchoolClass` → `Subject` → `Book` → `Chapter` → `Topic` → `ContentBlock`

### `boards`, `school_classes`, `subjects`
- **What they store**: The top-level academic structure (e.g., NCERT -> Class 10 -> Science).
- **Relationships**: A Board has many Classes; a Class has many Subjects.

### `books` & `chapters`
- **What they store**: The actual textbooks and their chapters.
- **Key Columns**: `book_id`, `chapter_number`, `natural_key`.
- **Note**: A `Chapter` resolves its subject and class by joining back up to `Book` -> `Subject`. It does not store `subject_id` directly.

### `topics`
- **What it stores**: Sub-sections of a chapter. This is the primary unit of learning and tracking.
- **Usage**: When a student takes a quiz or the AI detects mastery, it updates their mastery score specifically for a `Topic`.

### `content_blocks` & `block_embeddings`
- **What they store**: The actual paragraphs, text, and images extracted from the textbook PDFs. 
- **Block Embeddings**: Stores the `pgvector` vector data (`text-embedding-3-small`).
- **Usage**: When a student asks a question, their query is converted to a vector and matched against `block_embeddings`. The retrieved `content_blocks` are sent to GPT-4 to generate the answer.

---

## 3. Cognitive & Learning Metrics (`learning.py`)
These tables track *how* the student learns, what they are good at, and their study habits.

### `topic_mastery`
- **What it stores**: The student's real-time mastery level (0-100) for a specific `Topic`.
- **Key Columns**: `mastery_level`, `bloom_level_reached`, `understood_concepts`, `common_mistakes`.
- **Usage**: The AI tutor reads this to know if it should give the student an advanced question (if mastery is high) or break things down simply (if mastery is low).

### `student_learning_preferences`
- **What it stores**: The AI's ongoing observation of the student's preferred learning style.
- **Key Columns**: `prefers_examples`, `preferred_length` (short/medium), `attention_span`, `responds_to_encouragement`.
- **Usage**: Injected into the AI's system prompt behind the scenes so the AI naturally adjusts its tone, length, and explanation style (e.g., using more analogies if `prefers_analogies` is high).

### `student_streaks`
- **What it stores**: Gamification data (how many days in a row they studied).
- **Usage**: Used to show streaks on the dashboard and trigger motivational messages.

### `subject_quiz_feedback`
- **What it stores**: High-level aggregated statistics for a specific subject (e.g., overall Science accuracy).

---

## 4. Chat & Conversation (`chat.py`)
These tables store the actual chat history, but in a highly structured "tree" format to allow for branching (like ChatGPT's "regenerate" or "edit" buttons).

### `conversations`
- **What it stores**: The metadata container for a chat session.
- **Key Columns**: `title` (AI-generated), `session_mood`, `memory_summary`.
- **Usage**: Populates the sidebar list of previous chats.

### `messages` & `message_content_blocks`
- **What they store**: `messages` stores the tree structure (who said it and who their `parent_message_id` is). `message_content_blocks` stores the actual payload (text, code, or images).
- **Usage**: Sent to the LLM as conversation history.

### `message_sources`
- **What it stores**: The exact `content_blocks` (textbook paragraphs) that were used to generate a specific AI message.
- **Usage**: Used to show citations in the UI (e.g., "Source: NCERT Science, Chapter 10, Page 4").

### `artifacts` & `artifact_versions`
- **What they store**: Claude-style generated UI components (like a set of AI-generated flashcards, a mindmap, or study notes) that sit next to the chat.
- **Usage**: Allows the student to generate and edit structured study materials during a chat.

### `tool_call_log`
- **What it stores**: An audit trail of every time the AI decided to use a tool (like querying the textbook or running a calculator).

---

## 5. Quiz & Assessment (`quiz.py`)
These tables handle the AI-generated quizzes used to test the student.

### `quiz_attempts`
- **What it stores**: The metadata for a single quiz session.
- **Key Columns**: `score`, `passed`, `topic`, `num_questions`.

### `quiz_questions`
- **What it stores**: The individual questions generated by the AI for that attempt, along with the student's chosen answer.
- **Key Columns**: `question`, `options` (JSON array), `correct_answer`, `student_answer`, `is_correct`, `explanation`.
- **Usage**: When a quiz finishes, these results are analyzed by the `compute_quiz_cognitive_signals` service to update the student's `topic_mastery`.

---

### How they all connect (The Core Loop)
1. A **`User`** creates a **`Conversation`**.
2. They ask a question, generating a **`Message`**.
3. The system searches **`block_embeddings`** and retrieves **`content_blocks`** from the **`Chapter`**/**`Topic`**.
4. The AI looks at the user's **`student_learning_preferences`** and **`topic_mastery`** to decide how to answer.
5. The AI answers, creating a new **`Message`** and linking the sources in **`message_sources`**.
6. Periodically, the AI gives them a **`QuizAttempt`**. When they finish it, their **`topic_mastery`** and **`subject_quiz_feedback`** are automatically updated.
