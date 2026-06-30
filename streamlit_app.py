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
    # Cache busted to ensure fresh import of tutor.chat
    from tutor.chat import chat
    return chat


@st.cache_resource(show_spinner=False)
def preload_models():
    """Preload embedding and router models to avoid delay on first query."""
    from routing.embedder import Embedder
    # from routing.semantic_router import SemanticRouter
    Embedder()
    # SemanticRouter()

# ─────────────────────────────────────────────────────────────────────────────
# Session State Bootstrap
# ─────────────────────────────────────────────────────────────────────────────

def init_state():
    defaults = {
        "student_id": "",
        "username": "",
        "session_id": "",
        "messages": [],           # list of {"role", "content", "sources", "chunks", "chapter", "topic"}
        "show_context": True,     # toggle for the right panel
        "class_num": 10,
        "subject": "Science",
        "turn_count": 0,
        "memory_summary": "",
        "metrics": {},
        "cognitive_skills": {},
        "metrics_adjustments": {},
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

        # Class is now tied to the student profile, so we only display it, but keep state for reference
        st.markdown(f"**Class:** {st.session_state.get('class_num', 10)}")

        subject_options = ["Science", "Mathematics", "Social Science", "English", "Hindi"]
        st.session_state.subject = st.selectbox(
            "Subject",
            options=subject_options,
            index=subject_options.index(st.session_state.subject)
            if st.session_state.subject in subject_options else 0,
            key="subject_select",
        )

        # New Session button
        if st.button("🆕 New Session", use_container_width=True):
            st.session_state.session_id = ""
            st.session_state.messages = []
            st.session_state.turn_count = 0
            st.session_state.memory_summary = ""
            st.session_state.metrics = {}
            st.session_state.cognitive_skills = {}
            st.session_state.metrics_adjustments = {}
            if "last_applied_profile" in st.session_state:
                del st.session_state.last_applied_profile
            st.success("New session started!")
            st.rerun()

        # Past Sessions Dropdown
        if st.session_state.student_id:
            from db.memory import get_student_sessions, get_full_session_messages
            past_sessions = get_student_sessions(st.session_state.student_id, st.session_state.subject)
            if past_sessions:
                session_options = {s["id"]: f"{s['created_at'].strftime('%Y-%m-%d %H:%M')} ({s['message_count']} msgs)" for s in past_sessions}
                # Add a dummy default option to represent the current unsaved session if no session is active yet
                if not st.session_state.session_id:
                    session_options[""] = "--- Current (Unsaved) ---"
                
                selected_session_id = st.selectbox(
                    "📂 Past Sessions",
                    options=list(session_options.keys()),
                    format_func=lambda x: session_options.get(x, x),
                    index=list(session_options.keys()).index(st.session_state.session_id) if st.session_state.session_id in session_options else 0,
                    key="past_sessions_dropdown"
                )
                
                if selected_session_id and selected_session_id != st.session_state.session_id:
                    # User selected a different past session
                    st.session_state.session_id = selected_session_id
                    st.session_state.messages = get_full_session_messages(selected_session_id)
                    st.session_state.turn_count = len(st.session_state.messages) // 2
                    
                    # Refresh metrics from DB for the newly loaded session
                    from db.profile import get_subject_metrics
                    from db.metrics import compute_cognitive_skills
                    from db.database import SessionLocal
                    _db = SessionLocal()
                    try:
                        metrics = get_subject_metrics(_db, st.session_state.student_id, st.session_state.subject)
                        st.session_state.metrics = metrics
                        st.session_state.cognitive_skills = compute_cognitive_skills(metrics)
                        
                        # Also refresh memory_summary for the old session
                        from db.models import ConversationSession
                        sess = _db.query(ConversationSession).filter(ConversationSession.id == selected_session_id).first()
                        st.session_state.memory_summary = sess.summary if sess else ""
                    finally:
                        _db.close()
                    st.rerun()

        st.markdown("---")

        # Session Stats
        st.markdown("### 📊 Session Stats")
        sid_display = st.session_state.session_id[:8] + "..." if st.session_state.session_id else "—"
        st.markdown(f"""
        <div class="stat-row"><span>Student</span><span class="stat-value">{st.session_state.username}</span></div>
        <div class="stat-row"><span>Session ID</span><span class="stat-value">{sid_display}</span></div>
        <div class="stat-row"><span>Turns</span><span class="stat-value">{st.session_state.turn_count}</span></div>
        <div class="stat-row"><span>Class</span><span class="stat-value">{st.session_state.get('class_num', 10)}</span></div>
        <div class="stat-row"><span>Subject</span><span class="stat-value">{st.session_state.subject}</span></div>
        """, unsafe_allow_html=True)

        # Profile Preset Selector
        if st.session_state.session_id:
            st.markdown("---")
            st.markdown("### 👤 Profile Preset")
            profiles = ["Standard", "Struggling but Persistent", "Fast Learner", "Casual"]
            
            selected_profile = st.selectbox(
                "Select Student Profile Preset",
                options=profiles,
                index=0,
                key="profile_select_box"
            )
            
            if st.button("Apply Preset", use_container_width=True):
                from db.metrics import apply_profile_metrics, compute_cognitive_skills
                from db.database import SessionLocal
                db = SessionLocal()
                try:
                    updated = apply_profile_metrics(
                        st.session_state.student_id,
                        st.session_state.subject,
                        selected_profile,
                        db
                    )
                    st.session_state.metrics = updated
                    st.session_state.cognitive_skills = compute_cognitive_skills(updated)
                    st.success(f"Preset applied: {selected_profile}")
                    st.rerun()
                finally:
                    db.close()

        # Session Remark (teacher-style performance note, updated every 4 turns)
        if st.session_state.session_id:
            st.markdown("---")
            st.markdown("### 📝 Session Remarks")
            from db.memory import get_session_remark
            remark = get_session_remark(st.session_state.session_id)
            if remark:
                st.markdown(
                    f'<div class="memory-card" style="border-left: 3px solid #a0aaf0;">{remark}</div>',
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    "<p style='font-size:11px; color:#707090;'>Remarks will appear after every 4 turns of conversation.</p>",
                    unsafe_allow_html=True
                )

        # Student Memory (persistent cross-session facts)
        if st.session_state.student_id:
            st.markdown("---")
            st.markdown("### 🧠 Learning Memory")
            from db.memory import get_student_memory
            mem = get_student_memory(st.session_state.student_id, st.session_state.subject)
            if mem:
                for entry in mem:
                    st.markdown(
                        f'<div style="font-size:11px; color:#c0c0d8; background:rgba(102,126,234,0.07); '
                        f'border-radius:5px; padding:5px 10px; margin:3px 0;">• {entry}</div>',
                        unsafe_allow_html=True
                    )
            else:
                st.markdown(
                    "<p style='font-size:11px; color:#707090;'>Memory entries will be built from your conversations.</p>",
                    unsafe_allow_html=True
                )

        # Conversation Summary (compressed older turns memory)
        if st.session_state.memory_summary:
            st.markdown("---")
            st.markdown("### 📚 Conversation Summary")
            st.markdown(
                f'<div class="memory-card">{st.session_state.memory_summary}</div>',
                unsafe_allow_html=True
            )

        # Manual Score Control Slider Expander
        if st.session_state.session_id:
            with st.expander("🛠️ Manual Score Control"):
                st.markdown("<p style='font-size:11px; color:#8888a8; margin-bottom: 8px;'>Directly customize student tracking scores.</p>", unsafe_allow_html=True)
                current_metrics = st.session_state.metrics
                if not current_metrics:
                    from db.profile import get_subject_metrics
                    from db.database import SessionLocal
                    _db = SessionLocal()
                    try:
                        current_metrics = get_subject_metrics(_db, st.session_state.student_id, st.session_state.subject)
                    finally:
                        _db.close()
                    st.session_state.metrics = current_metrics

                new_metrics = {}
                metrics_def = [
                    ("Concept Mastery Score", "concept_master_score", 0.0, 100.0, 1.0),
                    ("Error Repetition Rate", "error_repetition_rate", 0.0, 1.0, 0.05),
                    ("Attempt Persistence", "attempt_persistence", 0.0, 100.0, 1.0),
                    ("Struggle Recovery Rate", "struggle_recovery_rate", 0.0, 100.0, 1.0),
                    ("Practice Intensity", "practice_intensity", 0.0, 100.0, 1.0),
                    ("Learning Velocity", "learning_velocity", 0.0, 100.0, 1.0),
                    ("Knowledge Retention", "knowledge_retention", 0.0, 100.0, 1.0),
                    ("Cognitive Thinking Level", "cognitive_thinking_level", 0.0, 100.0, 1.0),
                    ("Engagement Frequency", "engagement_frequency", 0.0, 100.0, 1.0),
                    ("Assessment Accuracy", "assessment_accuracy", 0.0, 100.0, 1.0),
                ]

                changed = False
                for label, key, min_v, max_v, step in metrics_def:
                    cur_val = current_metrics.get(key, 50.0 if min_v == 0.0 else 0.2)
                    val = st.slider(label, min_value=min_v, max_value=max_v, value=float(cur_val), step=step, key=f"slider_{key}")
                    new_metrics[key] = val
                    if val != float(cur_val):
                        changed = True

                if changed:
                    from db.profile import update_subject_profile
                    from db.metrics import compute_cognitive_skills
                    from db.database import SessionLocal
                    db = SessionLocal()
                    try:
                        update_subject_profile(db, st.session_state.student_id, st.session_state.subject, new_metrics, source="manual")
                    finally:
                        db.close()
                    st.session_state.metrics = new_metrics
                    st.session_state.cognitive_skills = compute_cognitive_skills(new_metrics)
                    st.rerun()

        # Student Insights Dashboard
        if st.session_state.session_id:
            st.markdown("---")
            st.markdown("### 🎓 Student Insights")
            
            metrics = st.session_state.metrics
            if not metrics:
                from db.profile import get_subject_metrics
                from db.database import SessionLocal
                db = SessionLocal()
                try:
                    metrics = get_subject_metrics(db, st.session_state.student_id, st.session_state.subject)
                finally:
                    db.close()
                st.session_state.metrics = metrics

            cognitive_skills = st.session_state.cognitive_skills
            if not cognitive_skills:
                from db.metrics import compute_cognitive_skills
                cognitive_skills = compute_cognitive_skills(metrics)
                st.session_state.cognitive_skills = cognitive_skills

            view_mode = st.radio(
                "Display Level",
                options=["Cognitive Skills (High-Level)", "Raw Tracking Scores (Detailed)"],
                index=0,
                key="insights_view_mode"
            )

            if metrics:
                cog_val = metrics.get("cognitive_thinking_level", 50.0)
                if cog_val <= 20:
                    cog_level = "Remember (Recall)"
                    cog_desc = "Identifying and recalling textbook facts."
                    cog_badge = "#6c72cb"
                elif cog_val <= 40:
                    cog_level = "Understand"
                    cog_desc = "Explaining concepts and summaries."
                    cog_badge = "#a78bfa"
                elif cog_val <= 60:
                    cog_level = "Apply"
                    cog_desc = "Using concepts in new situations/problems."
                    cog_badge = "#3b82f6"
                elif cog_val <= 80:
                    cog_level = "Analyze"
                    cog_desc = "Drawing connections and breaking down topics."
                    cog_badge = "#ec4899"
                else:
                    cog_level = "Evaluate & Create"
                    cog_desc = "Critiquing theories and proposing original ideas."
                    cog_badge = "#38ef7d"

                st.markdown(f"""
                <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 12px; margin-bottom: 15px;">
                    <div style="font-size: 11px; text-transform: uppercase; color: #8888a8; font-weight: 600; letter-spacing: 0.05em;">Bloom's Taxonomy Level</div>
                    <div style="font-size: 16px; font-weight: 700; color: {cog_badge}; margin: 4px 0 2px 0;">{cog_level}</div>
                    <div style="font-size: 11px; color: #707090; line-height: 1.3;">{cog_desc}</div>
                </div>
                """, unsafe_allow_html=True)

                def render_metric_bar(label, val, is_rate=False, description=None):
                    percentage = val if not is_rate else val * 100
                    percentage = max(0.0, min(100.0, percentage))
                    if is_rate:
                        hue = max(0.0, min(120.0, (1.0 - val) * 120.0))
                    else:
                        hue = max(0.0, min(120.0, (val / 100.0) * 120.0))
                    color = f"hsl({hue}, 80%, 50%)"
                    
                    desc_html = f"<div style='font-size:10px; color:#707090; margin-top:2px;'>{description}</div>" if description else ""
                    
                    st.markdown(f"""
                    <div style="margin-bottom: 12px;">
                        <div style="display: flex; justify-content: space-between; font-size: 12px; color: #a0aaf0;">
                            <span>{label}</span>
                            <strong>{percentage:.1f}%</strong>
                        </div>
                        <div style="background: rgba(255,255,255,0.05); border-radius: 4px; height: 6px; width: 100%; overflow: hidden; margin-top: 4px; border: 1px solid rgba(255,255,255,0.08);">
                            <div style="background: {color}; width: {percentage}%; height: 100%; border-radius: 4px;"></div>
                        </div>
                        {desc_html}
                    </div>
                    """, unsafe_allow_html=True)

                if "High-Level" in view_mode:
                    render_metric_bar("Concept Understanding", cognitive_skills.get("concept_understanding", 50.0), description="Concept mastery and assessment accuracy")
                    render_metric_bar("Learning Effort", cognitive_skills.get("learning_effort", 50.0), description="Practice intensity, persistence, and engagement")
                    render_metric_bar("Learning Adaptability", cognitive_skills.get("learning_adaptability", 50.0), description="Struggle recovery and low error repetition")
                    render_metric_bar("Knowledge Stability", cognitive_skills.get("knowledge_stability", 50.0), description="Knowledge retention and learning velocity")
                    render_metric_bar("Cognitive Depth", cognitive_skills.get("cognitive_depth", 50.0), description="Bloom's taxonomy thinking stage")
                else:
                    render_metric_bar("Concept Mastery Score", metrics.get("concept_master_score", 50.0))
                    render_metric_bar("Error Repetition Rate", metrics.get("error_repetition_rate", 0.0), is_rate=True)
                    render_metric_bar("Attempt Persistence", metrics.get("attempt_persistence", 50.0))
                    render_metric_bar("Struggle Recovery Rate", metrics.get("struggle_recovery_rate", 50.0))
                    render_metric_bar("Practice Intensity", metrics.get("practice_intensity", 50.0))
                    render_metric_bar("Learning Velocity", metrics.get("learning_velocity", 50.0))
                    render_metric_bar("Knowledge Retention", metrics.get("knowledge_retention", 50.0))
                    render_metric_bar("Engagement Frequency", metrics.get("engagement_frequency", 50.0))
                    render_metric_bar("Assessment Accuracy", metrics.get("assessment_accuracy", 50.0))

        # Cognitive Layer Feed
        if st.session_state.session_id and st.session_state.metrics_adjustments:
            st.markdown("---")
            st.markdown("### 🧠 Cognitive Layer Feed")
            
            adjusts = st.session_state.metrics_adjustments
            has_changes = False
            for k, val in adjusts.items():
                adj_type = val.get("adjustment", "constant")
                if adj_type in ("increase", "decrease"):
                    has_changes = True
                    delta_sign = "+" if adj_type == "increase" else "-"
                    color = "#38ef7d" if adj_type == "increase" else "#ff4b4b"
                    label = k.replace("_", " ").title()
                    
                    st.markdown(f"""
                    <div style="background: rgba(255,255,255,0.03); border-left: 3px solid {color}; border-radius: 6px; padding: 8px 10px; margin-bottom: 8px;">
                        <div style="display: flex; justify-content: space-between; font-size: 12px;">
                            <strong style="color: #c0c0e0;">{label}</strong>
                            <span style="color: {color}; font-weight: bold;">{delta_sign}{abs(val.get('delta', 0.0)):.1f}</span>
                        </div>
                        <div style="font-size: 11px; color: #8888a8; line-height: 1.3; margin-top: 4px;">{val.get('reason', '')}</div>
                    </div>
                    """, unsafe_allow_html=True)
            
            if not has_changes:
                st.markdown("<p style='font-size:11px; color:#707090;'>Metrics kept constant for the latest input.</p>", unsafe_allow_html=True)

        st.markdown("---")
        st.markdown(
            "<div style='text-align:center; color:#404060; font-size:11px;'>Powered by Groq · PostgreSQL (pgvector)</div>",
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
        q_type = msg.get("question_type", "curriculum")

        # Agent mode badge
        if q_type == "conversational":
            mode_badge = "<span style='background:rgba(56,239,125,0.15);color:#38ef7d;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;margin-left:4px;'>💬 Conversational</span>"
        else:
            mode_badge = "<span style='background:rgba(102,126,234,0.15);color:#a0aaf0;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;margin-left:4px;'>📚 Curriculum</span>"

        st.markdown(f"""
        <div class="avatar-row">
          <div class="avatar tutor-avatar">🤖</div>
          <div class="tutor-bubble">
            <div style='margin-bottom:8px;'>{mode_badge}</div>
            {content}
          </div>
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
    """Three-tab right panel: Retrieved Chunks + Prompt Inspector + Cognitive Evaluation."""

    # Find the last tutor message
    last_tutor = None
    for msg in reversed(st.session_state.messages):
        if msg["role"] == "tutor":
            last_tutor = msg
            break

    tab_chunks, tab_prompt, tab_cognitive = st.tabs([
        "📖 Retrieved Context", 
        "🔬 Prompt Inspector",
        "🧠 Cognitive Evaluation"
    ])

    # ── Tab 1: Retrieved Chunks ───────────────────────────────────────────────
    with tab_chunks:
        if not last_tutor:
            st.markdown("""
            <div style='color:#505070; font-size:13px; text-align:center; padding:40px 0;'>
                Ask a question to see the retrieved context here.
            </div>
            """, unsafe_allow_html=True)
        else:
            chunks = last_tutor.get("chunks", [])
            chapter = last_tutor.get("chapter", "")
            topic   = last_tutor.get("topic", "")
            q_type  = last_tutor.get("question_type", "curriculum")

            # Routing metadata row
            if chapter or topic:
                st.markdown(f"""
                <div style='font-size:12px; color:#8888b8; margin-bottom:10px;'>
                     <b style='color:#667eea;'>Routed to:</b>
                     {f"<span style='color:#c0c0e0;'>{chapter}</span>" if chapter else ""}
                     {f" › <span style='color:#a0aaf0;'>{topic}</span>" if topic else ""}
                </div>
                """, unsafe_allow_html=True)

            if not chunks:
                color = "#38ef7d" if q_type == "conversational" else "#e0c97a"
                label = (
                    "💬 Conversational — no Qdrant retrieval performed."
                    if q_type == "conversational"
                    else "⚠️ No chunks passed the confidence threshold. Polite refusal was returned."
                )
                st.markdown(
                    f"<div style='color:{color}; font-size:13px; padding:16px 0;'>{label}</div>",
                    unsafe_allow_html=True
                )
            else:
                # Confidence threshold indicator
                passed = [c for c in chunks if c.get("score", 0) >= 0.60]
                blocked = len(chunks) - len(passed)
                st.markdown(f"""
                <div style='font-size:12px; color:#606080; margin-bottom:10px;'>
                    {len(chunks)} chunk{"s" if len(chunks) != 1 else ""} retrieved ·
                    <span style='color:#38ef7d;'>{len(passed)} passed</span> ·
                    <span style='color:#f87171;'>{blocked} blocked</span>
                    <span style='color:#404060;'>(threshold 0.60)</span>
                </div>
                """, unsafe_allow_html=True)

                for i, chunk in enumerate(chunks):
                    meta  = chunk.get("metadata", {})
                    score = chunk.get("score", 0)
                    text  = chunk.get("content", "")
                    ctopic = meta.get("topic", "")
                    passed_gate = score >= 0.60
                    border_color = "#667eea" if passed_gate else "#f87171"
                    status_icon  = "✅" if passed_gate else "🚫"

                    st.markdown(f"""
                    <div class="chunk-card" style='border-left-color:{border_color};'>
                        <div class="chunk-meta">
                            {status_icon} Chunk {i+1}
                            <span class="score-pill">score {score:.3f}</span>
                            {f"<span style='color:#8888b8; font-weight:400; margin-left:8px;'>· {ctopic}</span>" if ctopic else ""}
                        </div>
                        <div style='white-space:pre-wrap;'>{text[:600]}{"..." if len(text) > 600 else ""}</div>
                    </div>
                    """, unsafe_allow_html=True)

    # ── Tab 2: Prompt Inspector ───────────────────────────────────────────────
    with tab_prompt:
        if not last_tutor:
            st.markdown("""
            <div style='color:#505070; font-size:13px; text-align:center; padding:40px 0;'>
                Ask a question to inspect the LLM prompt here.
            </div>
            """, unsafe_allow_html=True)
        else:
            prompt_msgs = last_tutor.get("prompt_messages", [])

            if not prompt_msgs:
                st.markdown(
                    "<div style='color:#606080; font-size:13px;'>No prompt data (polite refusal — LLM was not called).</div>",
                    unsafe_allow_html=True
                )
            else:
                # Summary header
                role_counts = {}
                total_chars = 0
                for m in prompt_msgs:
                    r = m.get("role", "")
                    role_counts[r] = role_counts.get(r, 0) + 1
                    total_chars += len(m.get("content", ""))

                parts = " · ".join(f"<b>{r}</b>×{n}" for r, n in role_counts.items())
                st.markdown(f"""
                <div style='font-size:12px; color:#8888b8; margin-bottom:12px;'>
                    {len(prompt_msgs)} messages · ~{total_chars // 4} tokens · {parts}
                </div>
                """, unsafe_allow_html=True)

                # Render each message in the prompt
                role_colours = {
                    "system":    ("#6c72cb", "rgba(108,114,203,0.08)", "⚙️"),
                    "user":      ("#667eea", "rgba(102,126,234,0.08)", "👤"),
                    "assistant": ("#38ef7d", "rgba(56,239,125,0.08)",  "🤖"),
                }

                for i, msg in enumerate(prompt_msgs):
                    role    = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    col, bg, icon = role_colours.get(role, ("#9090b0", "rgba(144,144,176,0.08)", "❓"))

                    # Truncate very long system prompts in the view (user can expand)
                    display_content = content
                    is_long = len(content) > 800
                    if is_long:
                        display_content = content[:800] + "\n\n[...truncated for display...]"

                    st.markdown(f"""
                    <div style='background:{bg}; border:1px solid {col}33;
                                border-left:3px solid {col}; border-radius:8px;
                                padding:10px 14px; margin:8px 0;'>
                        <div style='font-size:11px; color:{col}; font-weight:700;
                                    text-transform:uppercase; letter-spacing:0.06em;
                                    margin-bottom:8px;'>
                            {icon} [{i+1}] {role} · {len(content)} chars
                        </div>
                        <div style='font-family:"Fira Code",monospace; font-size:12px;
                                    color:#c0c0d8; line-height:1.7;
                                    white-space:pre-wrap; word-break:break-word;'
                        >{display_content}</div>
                    </div>
                    """, unsafe_allow_html=True)

                    if is_long:
                        with st.expander(f"Show full message [{i+1}] ({len(content)} chars)"):
                            st.code(content, language=None)

    # ── Tab 3: Cognitive Evaluation ───────────────────────────────────────────
    with tab_cognitive:
        if not last_tutor:
            st.markdown("""
            <div style='color:#505070; font-size:13px; text-align:center; padding:40px 0;'>
                Ask a question to see the cognitive layer evaluation here.
            </div>
            """, unsafe_allow_html=True)
        else:
            # Fallback to st.session_state values since they can be updated via sliders/presets in real-time
            metrics = st.session_state.metrics or last_tutor.get("metrics", {})
            cognitive_skills = st.session_state.cognitive_skills or last_tutor.get("cognitive_skills", {})
            adjusts = last_tutor.get("metrics_adjustments", {})

            # 1. High-level Cognitive Skills Dashboard
            st.markdown("### 🏆 Mapped Cognitive Skills")
            st.markdown("<p style='font-size:11px; color:#8888a8; margin-top:-10px; margin-bottom: 12px;'>Derived from the 10 raw scores to track student segments.</p>", unsafe_allow_html=True)
            
            def render_panel_metric_bar(label, val, is_rate=False, description=None):
                percentage = val if not is_rate else val * 100
                percentage = max(0.0, min(100.0, percentage))
                if is_rate:
                    hue = max(0.0, min(120.0, (1.0 - val) * 120.0))
                else:
                    hue = max(0.0, min(120.0, (val / 100.0) * 120.0))
                color = f"hsl({hue}, 80%, 50%)"
                
                desc_html = f"<div style='font-size:10px; color:#707090; margin-top:2px;'>{description}</div>" if description else ""
                
                st.markdown(f"""
                <div style="margin-bottom: 12px; background: rgba(255,255,255,0.02); padding: 8px 12px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04);">
                    <div style="display: flex; justify-content: space-between; font-size: 12px; color: #a0aaf0;">
                        <strong>{label}</strong>
                        <strong style="color: {color};">{percentage:.1f}%</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.05); border-radius: 4px; height: 6px; width: 100%; overflow: hidden; margin-top: 4px; border: 1px solid rgba(255,255,255,0.08);">
                        <div style="background: {color}; width: {percentage}%; height: 100%; border-radius: 4px;"></div>
                    </div>
                    {desc_html}
                </div>
                """, unsafe_allow_html=True)

            render_panel_metric_bar("Concept Understanding", cognitive_skills.get("concept_understanding", 50.0), description="Concept mastery and assessment accuracy")
            render_panel_metric_bar("Learning Effort", cognitive_skills.get("learning_effort", 50.0), description="Practice intensity, persistence, and engagement")
            render_panel_metric_bar("Learning Adaptability", cognitive_skills.get("learning_adaptability", 50.0), description="Struggle recovery and low error repetition")
            render_panel_metric_bar("Knowledge Stability", cognitive_skills.get("knowledge_stability", 50.0), description="Knowledge retention and learning velocity")
            render_panel_metric_bar("Cognitive Depth", cognitive_skills.get("cognitive_depth", 50.0), description="Bloom's taxonomy thinking stage")

            # 2. Detailed Adjustments and Raw Scores
            st.markdown("### 📊 Raw Tracking Scores")
            with st.expander("Show Detailed 10 Scores & Adjustments", expanded=False):
                # Bloom's level
                cog_val = metrics.get("cognitive_thinking_level", 50.0)
                if cog_val <= 20:
                    cog_level = "Remember (Recall)"
                    cog_badge = "#6c72cb"
                elif cog_val <= 40:
                    cog_level = "Understand"
                    cog_desc = "Explaining concepts and summaries."
                    cog_badge = "#a78bfa"
                elif cog_val <= 60:
                    cog_level = "Apply"
                    cog_desc = "Using concepts in new situations/problems."
                    cog_badge = "#3b82f6"
                elif cog_val <= 80:
                    cog_level = "Analyze"
                    cog_desc = "Drawing connections and breaking down topics."
                    cog_badge = "#ec4899"
                else:
                    cog_level = "Evaluate & Create"
                    cog_desc = "Critiquing theories and proposing original ideas."
                    cog_badge = "#38ef7d"

                st.markdown(f"""
                <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 12px; margin-bottom: 15px; text-align: center;">
                    <div style="font-size: 11px; text-transform: uppercase; color: #8888a8; font-weight: 600; letter-spacing: 0.05em;">Bloom's Taxonomy Level</div>
                    <div style="font-size: 16px; font-weight: 700; color: {cog_badge}; margin: 4px 0 2px 0;">{cog_level} ({cog_val:.1f}%)</div>
                </div>
                """, unsafe_allow_html=True)

                for k, v in metrics.items():
                    label = k.replace("_", " ").title()
                    is_rate = (k == "error_repetition_rate")
                    percentage = v if not is_rate else v * 100.0
                    
                    # Check if there was an adjustment on this turn
                    adj_info = adjusts.get(k, {})
                    adj_type = adj_info.get("adjustment", "constant")
                    delta = adj_info.get("delta", 0.0)
                    
                    adj_badge = ""
                    if adj_type == "increase":
                        adj_badge = f"<span style='color:#38ef7d; font-size:10px; margin-left: 8px;'>▲ +{delta:.1f}</span>"
                    elif adj_type == "decrease":
                        adj_badge = f"<span style='color:#ff4b4b; font-size:10px; margin-left: 8px;'>▼ -{abs(delta):.1f}</span>"
                    
                    if is_rate:
                        hue = max(0.0, min(120.0, (1.0 - v) * 120.0))
                    else:
                        hue = max(0.0, min(120.0, (v / 100.0) * 120.0))
                    color = f"hsl({hue}, 80%, 50%)"

                    st.markdown(f"""
                    <div style="margin-bottom: 10px; background: rgba(0,0,0,0.15); padding: 8px 10px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.04);">
                        <div style="display: flex; justify-content: space-between; font-size: 11px; color: #a0aaf0;">
                            <span>{label} {adj_badge}</span>
                            <strong>{percentage:.1f}%</strong>
                        </div>
                        <div style="background: rgba(255,255,255,0.05); border-radius: 4px; height: 5px; width: 100%; overflow: hidden; margin-top: 4px;">
                            <div style="background: {color}; width: {percentage}%; height: 100%; border-radius: 4px;"></div>
                        </div>
                        {f"<div style='font-size:10px; color:#8888a8; margin-top:6px; font-style:italic; border-top: 1px dashed rgba(255,255,255,0.05); padding-top: 4px;'>{adj_info.get('reason')}</div>" if adj_info.get('reason') else ""}
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
                student_id=st.session_state.student_id,
                session_id=st.session_state.session_id,
                question=question,
                subject=st.session_state.subject,
            )
            response = chat_fn(request)

            # Update session state
            st.session_state.session_id = response.session_id
            st.session_state.turn_count = response.conversation_length // 2
            st.session_state.metrics = response.metrics
            st.session_state.cognitive_skills = getattr(response, "cognitive_skills", {})
            st.session_state.metrics_adjustments = getattr(response, "metrics_adjustments", {})

            # Store tutor response with all metadata for rendering
            st.session_state.messages.append({
                "role": "tutor",
                "content": response.answer,
                "sources": [s.model_dump() for s in response.sources],
                "chunks": response.raw_chunks,
                "chapter": response.routed_chapter,
                "topic": response.routed_topic,
                "question_type": response.question_type,
                "prompt_messages": response.prompt_messages,
                "metrics": response.metrics,
                "metrics_adjustments": response.metrics_adjustments,
                "cognitive_skills": response.cognitive_skills,
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
# App Entry & Authentication
# ─────────────────────────────────────────────────────────────────────────────

def render_auth():
    st.markdown("""
    <div class="app-header" style="text-align:center;">
        <h1 class="app-title">Welcome to VishwAlpha</h1>
        <p class="app-subtitle">Log in or create an account to start learning</p>
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["Login", "Register"])
    from db.database import SessionLocal
    from db.auth import login_student, register_student

    with tab1:
        st.subheader("Login")
        log_user = st.text_input("Username", key="login_username")
        log_pass = st.text_input("Password", type="password", key="login_password")
        if st.button("Login", use_container_width=True):
            db = SessionLocal()
            try:
                student = login_student(db, log_user, log_pass)
                if student:
                    st.session_state.student_id = student.id
                    st.session_state.username = student.username
                    st.session_state.class_num = student.class_num
                    with st.spinner("Loading AI models into cache (this happens only once)..."):
                        preload_models()
                    st.success("Login successful!")
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
            finally:
                db.close()

    with tab2:
        st.subheader("Register")
        reg_user = st.text_input("Username", key="reg_username")
        reg_email = st.text_input("Email", key="reg_email")
        reg_pass = st.text_input("Password", type="password", key="reg_password")
        reg_class = st.selectbox("Class", [6, 7, 8, 9, 10, 11, 12], index=4)
        if st.button("Register", use_container_width=True):
            db = SessionLocal()
            try:
                if reg_user and reg_email and reg_pass:
                    student = register_student(db, reg_user, reg_email, reg_pass, reg_class)
                    st.session_state.student_id = student.id
                    st.session_state.username = student.username
                    st.session_state.class_num = student.class_num
                    with st.spinner("Loading AI models into cache (this happens only once)..."):
                        preload_models()
                    st.success("Registration successful! Logging you in...")
                    st.rerun()
                else:
                    st.error("Please fill in all fields.")
            except ValueError as e:
                st.error(str(e))
            finally:
                db.close()


def main():
    init_state()
    init_backend()

    if not st.session_state.student_id:
        render_auth()
        return

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
