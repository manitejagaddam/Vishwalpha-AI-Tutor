"""
streamlit_app.py
────────────────
VishwAlpha AI Tutor — Streamlit Frontend

Layout:
  Left Sidebar  : Session control, class/subject selector, session stats,
                  conversation memory summary
  Main Column   : Chat history + input
  Right Column  : Retrieved Context panel (toggleable)
"""

import sys
import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Page config MUST be first Streamlit call ──────────────────────────────────
st.set_page_config(
    page_title="VishwAlpha AI Tutor",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS Injection ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Fira+Code:wght@400;500&display=swap');

  /* ── Base ───────────────────────────────────────────────────────────────── */
  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

  .stApp {
    background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%);
    min-height: 100vh;
  }

  /* ── Sidebar ────────────────────────────────────────────────────────────── */
  [data-testid="stSidebar"] {
    background: rgba(255,255,255,0.04);
    border-right: 1px solid rgba(255,255,255,0.08);
    backdrop-filter: blur(20px);
  }

  /* ── Chat message bubbles ───────────────────────────────────────────────── */
  .student-bubble {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: #fff;
    padding: 14px 18px;
    border-radius: 18px 18px 4px 18px;
    margin: 8px 0 8px 40px;
    box-shadow: 0 4px 20px rgba(102,126,234,0.3);
    font-size: 15px;
    line-height: 1.6;
  }

  .tutor-bubble {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.1);
    color: #e8e8f0;
    padding: 14px 18px;
    border-radius: 18px 18px 18px 4px;
    margin: 8px 40px 8px 0;
    backdrop-filter: blur(10px);
    font-size: 15px;
    line-height: 1.7;
  }

  .tutor-bubble code {
    font-family: 'Fira Code', monospace;
    background: rgba(255,255,255,0.1);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 13px;
  }

  /* ── Avatar ─────────────────────────────────────────────────────────────── */
  .avatar-row {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    margin-bottom: 4px;
  }

  .avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    flex-shrink: 0;
  }

  .student-avatar { background: linear-gradient(135deg, #667eea, #764ba2); }
  .tutor-avatar   { background: linear-gradient(135deg, #11998e, #38ef7d); }

  /* ── Source badge ───────────────────────────────────────────────────────── */
  .source-badge {
    display: inline-block;
    background: rgba(102,126,234,0.15);
    border: 1px solid rgba(102,126,234,0.3);
    color: #a0aaf0;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 500;
    margin: 2px 3px;
  }

  /* ── Context panel ──────────────────────────────────────────────────────── */
  .context-panel {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 12px;
    backdrop-filter: blur(10px);
  }

  .context-panel-header {
    font-size: 12px;
    font-weight: 600;
    color: #6c72cb;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 10px;
  }

  .chunk-card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.06);
    border-left: 3px solid #667eea;
    border-radius: 8px;
    padding: 12px 14px;
    margin: 8px 0;
    font-size: 13px;
    color: #c0c0d8;
    line-height: 1.6;
  }

  .chunk-meta {
    font-size: 11px;
    color: #667eea;
    font-weight: 600;
    margin-bottom: 6px;
  }

  .score-pill {
    display: inline-block;
    background: rgba(56,239,125,0.15);
    color: #38ef7d;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 10px;
    font-weight: 600;
    margin-left: 6px;
  }

  /* ── Memory summary ─────────────────────────────────────────────────────── */
  .memory-card {
    background: rgba(255,215,0,0.05);
    border: 1px solid rgba(255,215,0,0.15);
    border-radius: 10px;
    padding: 12px;
    color: #e0c97a;
    font-size: 13px;
    line-height: 1.6;
  }

  /* ── Stats card ─────────────────────────────────────────────────────────── */
  .stat-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 6px 0;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    font-size: 13px;
    color: #9090b0;
  }

  .stat-value { color: #c0c0e0; font-weight: 600; }

  /* ── Header ─────────────────────────────────────────────────────────────── */
  .app-header {
    background: linear-gradient(135deg, rgba(102,126,234,0.15), rgba(118,75,162,0.15));
    border: 1px solid rgba(102,126,234,0.2);
    border-radius: 16px;
    padding: 20px 28px;
    margin-bottom: 20px;
  }

  .app-title {
    font-size: 26px;
    font-weight: 700;
    background: linear-gradient(135deg, #667eea, #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0;
  }

  .app-subtitle {
    color: #8888a8;
    font-size: 14px;
    margin-top: 4px;
  }

  /* ── Input box ──────────────────────────────────────────────────────────── */
  .stChatInputContainer {
    border-top: 1px solid rgba(255,255,255,0.08) !important;
    background: rgba(255,255,255,0.03) !important;
    padding: 12px !important;
    border-radius: 0 0 12px 12px !important;
  }

  /* ── Scrollable chat area ───────────────────────────────────────────────── */
  .chat-scroll {
    max-height: 62vh;
    overflow-y: auto;
    padding-right: 4px;
    scrollbar-width: thin;
    scrollbar-color: rgba(102,126,234,0.4) transparent;
  }

  /* ── Buttons ────────────────────────────────────────────────────────────── */
  .stButton > button {
    background: linear-gradient(135deg, #667eea, #764ba2) !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    transition: opacity 0.2s !important;
  }

  .stButton > button:hover { opacity: 0.85 !important; }

  /* ── Toggle button ──────────────────────────────────────────────────────── */
  .toggle-btn > button {
    background: rgba(102,126,234,0.12) !important;
    color: #a0aaf0 !important;
    border: 1px solid rgba(102,126,234,0.3) !important;
    font-size: 12px !important;
    padding: 4px 12px !important;
  }

  /* ── Divider ────────────────────────────────────────────────────────────── */
  hr { border-color: rgba(255,255,255,0.06) !important; }

  /* ── Select boxes ───────────────────────────────────────────────────────── */
  .stSelectbox > div > div {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    color: #c0c0e0 !important;
  }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Backend imports (lazy — avoids startup cost if DB is not ready)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def init_backend():
    """Initialise DB tables once on app start."""
    from db.database import init_db
    init_db()


@st.cache_resource(show_spinner=False)
def get_tutor_chat():
    from tutor.chat import chat
    return chat


# ─────────────────────────────────────────────────────────────────────────────
# Session State Bootstrap
# ─────────────────────────────────────────────────────────────────────────────

def init_state():
    defaults = {
        "session_id": "",
        "messages": [],           # list of {"role", "content", "sources", "chunks", "chapter", "topic"}
        "show_context": True,     # toggle for the right panel
        "class_num": 10,
        "subject": "Science",
        "turn_count": 0,
        "memory_summary": "",
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

def render_sidebar():
    with st.sidebar:
        st.markdown("""
        <div style='text-align:center; padding: 10px 0 20px;'>
            <div style='font-size:48px;'>🎓</div>
            <div style='font-size:18px; font-weight:700; color:#a0aaf0;'>VishwAlpha</div>
            <div style='font-size:12px; color:#6060a0;'>AI Tutor · NCERT</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("### ⚙️ Session Settings")

        class_options = [6, 7, 8, 9, 10, 11, 12]
        st.session_state.class_num = st.selectbox(
            "Class",
            options=class_options,
            index=class_options.index(st.session_state.class_num),
            key="class_select",
        )

        subject_options = ["Science", "Mathematics", "Social Science", "English", "Hindi"]
        st.session_state.subject = st.selectbox(
            "Subject",
            options=subject_options,
            index=subject_options.index(st.session_state.subject)
            if st.session_state.subject in subject_options else 0,
            key="subject_select",
        )

        st.markdown("---")

        # New Session button
        if st.button("🆕 New Session", use_container_width=True):
            st.session_state.session_id = ""
            st.session_state.messages = []
            st.session_state.turn_count = 0
            st.session_state.memory_summary = ""
            st.success("New session started!")
            st.rerun()

        st.markdown("---")

        # Session Stats
        st.markdown("### 📊 Session Stats")
        sid_display = st.session_state.session_id[:8] + "..." if st.session_state.session_id else "—"
        st.markdown(f"""
        <div class="stat-row"><span>Session ID</span><span class="stat-value">{sid_display}</span></div>
        <div class="stat-row"><span>Turns</span><span class="stat-value">{st.session_state.turn_count}</span></div>
        <div class="stat-row"><span>Class</span><span class="stat-value">{st.session_state.class_num}</span></div>
        <div class="stat-row"><span>Subject</span><span class="stat-value">{st.session_state.subject}</span></div>
        """, unsafe_allow_html=True)

        # Memory Summary
        if st.session_state.memory_summary:
            st.markdown("---")
            st.markdown("### 🧠 Conversation Memory")
            st.markdown(
                f'<div class="memory-card">{st.session_state.memory_summary}</div>',
                unsafe_allow_html=True
            )

        st.markdown("---")
        st.markdown(
            "<div style='text-align:center; color:#404060; font-size:11px;'>Powered by Groq · Qdrant · PostgreSQL</div>",
            unsafe_allow_html=True
        )


# ─────────────────────────────────────────────────────────────────────────────
# Message Rendering
# ─────────────────────────────────────────────────────────────────────────────

def render_message(msg: dict):
    role = msg["role"]
    content = msg["content"]

    if role == "student":
        st.markdown(f"""
        <div class="avatar-row" style="justify-content: flex-end;">
          <div class="student-bubble">{content}</div>
          <div class="avatar student-avatar">👤</div>
        </div>
        """, unsafe_allow_html=True)

    else:
        # Tutor message
        sources = msg.get("sources", [])
        chapter = msg.get("chapter", "")
        topic = msg.get("topic", "")

        st.markdown(f"""
        <div class="avatar-row">
          <div class="avatar tutor-avatar">🤖</div>
          <div class="tutor-bubble">{content}</div>
        </div>
        """, unsafe_allow_html=True)

        # Source badges
        if sources:
            badges = "".join(
                f'<span class="source-badge">📚 {s["topic"]} ({s["score"]})</span>'
                for s in sources
            )
            st.markdown(
                f'<div style="margin-left:44px; margin-top:4px;">{badges}</div>',
                unsafe_allow_html=True
            )


# ─────────────────────────────────────────────────────────────────────────────
# Context Panel (Right Column)
# ─────────────────────────────────────────────────────────────────────────────

def render_context_panel():
    """Shows the retrieved textbook chunks for the last tutor response."""
    st.markdown("""
    <div style='font-size:13px; font-weight:700; color:#667eea;
                text-transform:uppercase; letter-spacing:0.08em; margin-bottom:12px;'>
        📖 Retrieved Context
    </div>
    """, unsafe_allow_html=True)

    # Find the last tutor message that has chunks
    last_tutor = None
    for msg in reversed(st.session_state.messages):
        if msg["role"] == "tutor" and msg.get("chunks"):
            last_tutor = msg
            break

    if not last_tutor:
        st.markdown("""
        <div style='color:#505070; font-size:13px; text-align:center; padding:40px 0;'>
            Ask a question to see the retrieved context here.
        </div>
        """, unsafe_allow_html=True)
        return

    chunks = last_tutor["chunks"]
    chapter = last_tutor.get("chapter", "")
    topic = last_tutor.get("topic", "")

    # Routed metadata
    if chapter or topic:
        st.markdown(f"""
        <div style='font-size:12px; color:#8888b8; margin-bottom:12px;'>
            <b style='color:#667eea;'>Routed to:</b>
            {f"<span style='color:#c0c0e0;'>{chapter}</span>" if chapter else ""}
            {f" › <span style='color:#a0aaf0;'>{topic}</span>" if topic else ""}
        </div>
        """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style='font-size:12px; color:#606080; margin-bottom:10px;'>
        {len(chunks)} chunk{"s" if len(chunks) != 1 else ""} retrieved
    </div>
    """, unsafe_allow_html=True)

    for i, chunk in enumerate(chunks):
        meta = chunk.get("metadata", {})
        score = chunk.get("score", 0)
        content_text = chunk.get("content", "")
        chunk_topic = meta.get("topic", "")
        chunk_chapter = meta.get("chapter", "")

        st.markdown(f"""
        <div class="chunk-card">
            <div class="chunk-meta">
                Chunk {i+1}
                <span class="score-pill">score {score:.3f}</span>
                {f"<span style='color:#8888b8; font-weight:400; margin-left:8px;'>· {chunk_topic}</span>" if chunk_topic else ""}
            </div>
            <div style='white-space:pre-wrap;'>{content_text[:600]}{"..." if len(content_text) > 600 else ""}</div>
        </div>
        """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Main Chat Area
# ─────────────────────────────────────────────────────────────────────────────

def render_chat():
    # Header
    st.markdown("""
    <div class="app-header">
        <h1 class="app-title">VishwAlpha AI Tutor</h1>
        <p class="app-subtitle">Personalised NCERT curriculum assistant · Ask anything from your textbook</p>
    </div>
    """, unsafe_allow_html=True)

    # Chat history
    st.markdown('<div class="chat-scroll">', unsafe_allow_html=True)
    for msg in st.session_state.messages:
        render_message(msg)
    st.markdown('</div>', unsafe_allow_html=True)


def handle_input(question: str):
    """Process a student question through the full RAG tutor pipeline."""
    from schemas import ChatRequest

    chat_fn = get_tutor_chat()

    # Add student message immediately
    st.session_state.messages.append({"role": "student", "content": question})

    with st.spinner("🤔 Thinking..."):
        try:
            request = ChatRequest(
                session_id=st.session_state.session_id,
                question=question,
                class_num=st.session_state.class_num,
                subject=st.session_state.subject,
            )
            response = chat_fn(request)

            # Update session state
            st.session_state.session_id = response.session_id
            st.session_state.turn_count = response.conversation_length // 2

            # Store tutor response with all metadata for rendering
            st.session_state.messages.append({
                "role": "tutor",
                "content": response.answer,
                "sources": [s.model_dump() for s in response.sources],
                "chunks": response.raw_chunks,
                "chapter": response.routed_chapter,
                "topic": response.routed_topic,
            })

            # Update memory summary in sidebar
            from db.memory import get_history
            memory_summary, _ = get_history(response.session_id)
            st.session_state.memory_summary = memory_summary

        except Exception as e:
            st.session_state.messages.append({
                "role": "tutor",
                "content": f"⚠️ Error: {str(e)}\n\nPlease check that the API server is running and all environment variables are set.",
                "sources": [],
                "chunks": [],
                "chapter": "",
                "topic": "",
            })


# ─────────────────────────────────────────────────────────────────────────────
# App Entry
# ─────────────────────────────────────────────────────────────────────────────

def main():
    init_state()
    init_backend()

    render_sidebar()

    # ── Layout: chat (left) + context panel (right) ───────────────────────────
    # Toggle button lives above the columns
    col_toggle, col_spacer = st.columns([1, 5])
    with col_toggle:
        toggle_label = "🔍 Hide Context" if st.session_state.show_context else "🔍 Show Context"
        if st.button(toggle_label, key="ctx_toggle"):
            st.session_state.show_context = not st.session_state.show_context
            st.rerun()

    # Column layout depends on toggle state
    if st.session_state.show_context:
        chat_col, ctx_col = st.columns([3, 2], gap="large")
    else:
        chat_col = st.columns(1)[0]
        ctx_col = None

    with chat_col:
        render_chat()

        # Chat input
        question = st.chat_input(
            placeholder="Ask a question from your textbook... (e.g. What is rancidity?)",
            key="chat_input",
        )
        if question and question.strip():
            handle_input(question.strip())
            st.rerun()

    if ctx_col is not None:
        with ctx_col:
            render_context_panel()


if __name__ == "__main__":
    main()
