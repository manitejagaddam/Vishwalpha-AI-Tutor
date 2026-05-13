# VishwAlpha AI Tutor 🎓

VishwAlpha is a premium, AI-powered personalised tutoring system designed specifically for the Indian NCERT curriculum (Class 6-12). It uses a sophisticated **RAG (Retrieval-Augmented Generation)** pipeline to provide grounded, syllabus-accurate support for students.

![VishwAlpha UI](https://img.shields.io/badge/UI-Streamlit-FF4B4B?style=for-the-badge&logo=streamlit)
![Backend](https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge&logo=fastapi)
![LLM](https://img.shields.io/badge/LLM-Groq_Llama_3.1-orange?style=for-the-badge&logo=groq)
![Database](https://img.shields.io/badge/Database-PostgreSQL_|_Qdrant-blue?style=for-the-badge&logo=postgresql)

## 🚀 Key Features

- **Personalised RAG Engine**: Strictly grounded in NCERT textbooks. The tutor won't hallucinate; if the answer isn't in the book, it politely directs the student to their teacher.
- **Adaptive Teaching Styles**: Toggle between **Socratic Guidance** (leading the student with questions) or **Direct Explanation** based on the query.
- **Agentic Routing**: Uses a **Semantic Router** to classify student questions and route them to the correct chapter and topic with high precision.
- **Smart Memory Compression**: Maintains long conversation history without blowing up token costs by automatically summarising older turns while keeping recent ones verbatim.
- **Premium Student Dashboard**: A dark-themed, glassmorphic Streamlit UI featuring:
  - **Context Panel**: Real-time view of the textbook chunks retrieved.
  - **Prompt Inspector**: Deep-dive into the exact logic and system prompts being sent to the LLM.
  - **Session Persistence**: Continue your learning journey exactly where you left off.
- **Modular Pipeline**: Decoupled ingestion (PDF → Markdown → Cleaned Chunks) and retrieval engines.

## 🛠 Tech Stack

- **Core Logic**: Python 3.10+
- **LLM Brain**: Llama 3.1 via **Groq** (for ultra-low latency)
- **Vector DB**: **Qdrant** (semantic search)
- **Relational DB**: **PostgreSQL** (session & audit logs)
- **Frameworks**: FastAPI (Backend) & Streamlit (Frontend)
- **Deployment**: Docker & Docker Compose

## 📦 Installation & Setup

### Prerequisites
- Docker & Docker Compose
- Groq API Key
- Qdrant Cloud (or local container)

### Quick Start (Local Docker)
1. Clone the repository:
   ```bash
   git clone https://github.com/manitejagaddam/Vishwalpha-AI-Tutor.git
   cd Vishwalpha-AI-Tutor
   ```
2. Create a `.env` file from the example:
   ```env
   GROQ_API_KEY=your_key_here
   DATABASE_URL=postgresql://vishwalpha:password@db:5432/vishwalpha_tutor
   QDRANT_URL=http://qdrant:6333
   REDIS_URL=redis://redis:6379/0
   ```
3. Run the entire stack:
   ```bash
   docker-compose up --build
   ```
4. Access the tutor at: **http://localhost:8501**

## 📖 How it Works

1. **Ingestion**: Upload NCERT PDFs. The pipeline parses text using `PaddleOCR` and `PyMuPDF`, structures it into topics, and embeds it into Qdrant.
2. **Retrieval**: When a student asks a question, the **Semantic Router** identifies the subject and chapter. **Retrieval Engine** fetches the top-K most relevant chunks.
3. **Generation**: The **TutorLLM** processes the context and history using a hardened "NCERT Pedagogy" system prompt to generate the answer.

---
Built with ❤️ by Maniteja Gaddam for VishwAlpha.
