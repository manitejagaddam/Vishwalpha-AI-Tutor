# VishwAlpha Backend — Phase-Wise Implementation Plan (5 Phases)

> **5 Phases. Each phase is independently deployable and tested before the next begins.**
> **Total files touched**: 15 | **New DB tables**: 2 (`TopicPrerequisite`, `StudentTopicMastery`)

> [!NOTE]
> **Confirmed user decisions (from review):**
> - Curriculum is **static** for at least a year → Redis TTLs set to **30 days**
> - Backtrack depth **max 3** classes confirmed
> - Mastery decay interval controlled via **`.env` variable** (`MASTERY_DECAY_DAYS`)
> - Explicit give-up: use **adaptive skip** (teach the answer with full explanation) instead of forcing loop

---

## Phase Summary Table

| Phase | Focus | LLM Calls Saved | Key Files |
|---|---|---|---|
| **Phase 1** | DB Foundation & Scoped Routing | 0 (fixes correctness) | `models.py`, `schemas.py`, `vector_store.py`, `router.py`, `engine.py`, `query.py`, `chat.py` |
| **Phase 2** | Intelligent Backtracking Engine | Phase 1: 3→1 calls | `models.py`, `patterns.py`, `socratic.py`, `chat.py` |
| **Phase 3** | Topic Mastery & Structured Memory | Irrelevant memories eliminated | `models.py`, `profile.py`, `llm.py`, `chat.py` |
| **Phase 4** | Deterministic Cognitive Profiling | Batch LLM: metrics only | `metrics.py`, `profile.py`, `chat.py` |
| **Phase 5** | Token Budget & Tiered Caching | ~500 tokens/turn saved | `cache.py`, `engine.py`, `llm.py` |

---

## PHASE 1 — Database Foundation & Scoped Routing

> **Goal**: Fix broken query logic. A student's class must constrain ALL retrieval.

### What breaks today (the bug in `chat.py`)

```python
# tutor/chat.py L67-82 — CURRENT BROKEN FLOW
route = router.route_query(question)          # searches ALL classes globally
if class_num:
    route["class"] = class_num                # patches AFTER wrong chapter already selected
```
A Class 7 student asking "What is photosynthesis?" gets routed to Class 12 Biology
because cosine similarity favors the more detailed Class 12 content. Then `class=7`
is forced onto a route pointing to a Class 12 chapter — 0 retrieval results.

---

### 1.1 — Add DB Indexes to Vector Tables

**File**: [`db/models.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/db/models.py) — L209-227

```python
# BEFORE
class CurriculumRouting(Base):
    __tablename__ = "curriculum_routing"
    id        = Column(String(100), primary_key=True)
    class_num = Column(Integer, nullable=True)
    subject   = Column(String(100), nullable=True)
    chapter   = Column(String(200), nullable=True)
    topic     = Column(String(200), nullable=True)
    vector    = Column(Vector(384), nullable=False)

class CurriculumContent(Base):
    __tablename__ = "curriculum_content"
    id        = Column(String(100), primary_key=True)
    class_num = Column(Integer, nullable=True)
    subject   = Column(String(100), nullable=True)
    chapter   = Column(String(200), nullable=True)
    topic     = Column(String(200), nullable=True)
    content   = Column(Text, nullable=False)
    vector    = Column(Vector(384), nullable=False)

# AFTER
class CurriculumRouting(Base):
    __tablename__ = "curriculum_routing"
    id        = Column(String(100), primary_key=True)
    class_num = Column(Integer,     nullable=True, index=True)   # ADD
    subject   = Column(String(100), nullable=True, index=True)   # ADD
    chapter   = Column(String(200), nullable=True, index=True)   # ADD
    topic     = Column(String(200), nullable=True)
    vector    = Column(Vector(384), nullable=False)

class CurriculumContent(Base):
    __tablename__ = "curriculum_content"
    id        = Column(String(100), primary_key=True)
    class_num = Column(Integer,     nullable=True, index=True)   # ADD
    subject   = Column(String(100), nullable=True, index=True)   # ADD
    chapter   = Column(String(200), nullable=True, index=True)   # ADD
    topic     = Column(String(200), nullable=True)
    content   = Column(Text, nullable=False)
    vector    = Column(Vector(384), nullable=False)
```

---

### 1.2 — Scoped `search_routes()` with Pre-Filters

**File**: [`routing/vector_store.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/routing/vector_store.py)

```python
# AFTER — class_num and subject filter BEFORE cosine sort
def search_routes(
    self,
    query_vector: list[float],
    limit: int = 3,
    class_num: int | None = None,    # NEW
    subject: str | None = None,      # NEW
) -> list[dict]:
    with managed_session() as db:
        distance = CurriculumRouting.vector.cosine_distance(query_vector)
        query_obj = db.query(CurriculumRouting, (1 - distance).label("score"))

        if class_num is not None:
            query_obj = query_obj.filter(CurriculumRouting.class_num == class_num)
        if subject is not None:
            query_obj = query_obj.filter(
                func.lower(CurriculumRouting.subject) == subject.lower()
            )

        results = query_obj.order_by(distance).limit(limit).all()

        # Edge Case: scoped search empty -> fallback to global unscoped
        if not results and (class_num or subject):
            logger.warning(f"Scoped search empty for class={class_num}, subject={subject}. Falling back to global.")
            query_obj = db.query(CurriculumRouting, (1 - distance).label("score"))
            results = query_obj.order_by(distance).limit(limit).all()

        return [{"payload": {...}, "score": score} for row, score in results]
```

---

### 1.3 — Pass Filters INTO Router (Not After)

**File**: [`routing/router.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/routing/router.py)

```python
def route_query(
    self,
    query: str,
    class_num: int | None = None,   # NEW
    subject: str | None = None,     # NEW
) -> dict | None:
    query_vector = self.embedder.embed_query(query)
    results = self.vector_store.search_routes(
        query_vector, limit=3,
        class_num=class_num,        # PASS DOWN
        subject=subject,            # PASS DOWN
    )
    if results and results[0]["score"] > 0.4:
        return results[0]["payload"]
    return None
```

---

### 1.4 — Cascading Fallback Retrieval (3 Levels)

**File**: [`retrieval/engine.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/retrieval/engine.py)

```python
def retrieve(self, query, routing_metadata, top_k=5, min_results=3) -> list[dict]:
    """
    Level 1: class + subject + chapter + topic  (most specific)
    Level 2: class + subject + chapter           (chapter fallback)
    Level 3: class + subject                     (subject fallback)
    """
    query_vector = self.embedder.embed_query(query)

    filter_levels = [
        {"class_num": routing_metadata.get("class"), "subject": routing_metadata.get("subject"),
         "chapter": routing_metadata.get("chapter"), "topic": routing_metadata.get("topic")},
        {"class_num": routing_metadata.get("class"), "subject": routing_metadata.get("subject"),
         "chapter": routing_metadata.get("chapter")},
        {"class_num": routing_metadata.get("class"), "subject": routing_metadata.get("subject")},
    ]

    last_results = []
    for idx, filters in enumerate(filter_levels):
        results = self._run_filtered_query(query_vector, filters, top_k)
        last_results = results
        if len(results) >= min_results:
            logger.info(f"Retrieval satisfied at level {idx+1} with {len(results)} chunks.")
            return results
        logger.info(f"Level {idx+1} returned {len(results)} chunks, cascading...")

    return last_results  # best effort
```

**Edge Case — String Mismatch**: Use `func.lower()` on chapter and subject in `_run_filtered_query`.

---

### 1.5 — Add `class_num` to `ChatRequest` (MISSING from plan)

**File**: [`schemas.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/schemas.py) — L81-93

Currently `ChatRequest` has no `class_num` field. The student's class is fetched inside `chat.py` from the DB every single turn. Adding the optional field lets the frontend pass it directly.

```python
# BEFORE
class ChatRequest(BaseModel):
    student_id: str
    session_id: str = Field(default="")
    question: str
    subject: str = Field(default="Science")
    tutor_mode: str = Field(default="standard")
    # ← No class_num!

# AFTER
class ChatRequest(BaseModel):
    student_id: str
    session_id: str = Field(default="")
    question: str
    subject: str = Field(default="Science")
    class_num: int | None = Field(default=None, description="Student's class (optional, resolved from DB if absent")  # ADD
    tutor_mode: str = Field(default="standard")
```

In `chat.py`, resolve with fallback:
```python
# In tutor/chat.py — at the top of chat()
class_num = request.class_num
if class_num is None:
    student = get_student(db, request.student_id)
    class_num = student.class_num if student else 10  # default to Class 10
```

---

### 1.6 — Fix `chat.py` Routing Call

**File**: [`tutor/chat.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/tutor/chat.py) L67

```python
# BEFORE (broken post-patch)
route = router.route_query(question)
if class_num: route["class"] = class_num

# AFTER (pre-filter inside routing)
route = router.route_query(question, class_num=class_num, subject=request.subject)
```

---

### 1.7 — Fix `retrieval/query.py` (MISSING from plan)

**File**: [`retrieval/query.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/retrieval/query.py) — L39-76

This standalone entry point used for direct query testing still calls `router.route_query(question)` with no class/subject — same global-scope bug.

```python
# BEFORE
def query_system(question: str) -> str | None:
    route = router.route_query(question)   # global search
    ...

# AFTER
def query_system(
    question: str,
    class_num: int | None = None,   # NEW
    subject: str | None = None,     # NEW
) -> str | None:
    route = router.route_query(question, class_num=class_num, subject=subject)   # scoped
    ...
    chunks = retrieval_engine.retrieve(question, route, top_k=5)
    ...
```

---

### 1.8 — Curriculum Browse API Endpoints

**File**: [`api.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/api.py)

```python
@app.get("/curriculum/subjects")
def get_subjects(class_num: int, db: Session = Depends(get_db)):
    rows = db.query(CurriculumRouting.subject).filter(
        CurriculumRouting.class_num == class_num
    ).distinct().all()
    return {"subjects": [r[0] for r in rows if r[0]]}

@app.get("/curriculum/chapters")
def get_chapters(class_num: int, subject: str, db: Session = Depends(get_db)):
    rows = db.query(CurriculumRouting.chapter).filter(
        CurriculumRouting.class_num == class_num,
        func.lower(CurriculumRouting.subject) == subject.lower()
    ).distinct().all()
    return {"chapters": [r[0] for r in rows if r[0]]}

@app.get("/curriculum/topics")
def get_topics(class_num: int, subject: str, chapter: str, db: Session = Depends(get_db)):
    rows = db.query(CurriculumRouting.topic).filter(
        CurriculumRouting.class_num == class_num,
        func.lower(CurriculumRouting.subject) == subject.lower(),
        func.lower(CurriculumRouting.chapter) == chapter.lower()
    ).distinct().all()
    return {"topics": [r[0] for r in rows if r[0]]}
```

### Phase 1 Verification

- [ ] Class 7 student asking "photosynthesis" routes to Class 7 Biology, NOT Class 12
- [ ] Zero-result fallback cascade: topic miss → chapter hit tested
- [ ] Case-insensitive chapter filter: "acids, bases and salts" == "Acids, Bases and Salts"
- [ ] All 3 browse endpoints return correct non-empty data
- [ ] `ChatRequest.class_num` is optional — request without it still works (resolved from DB)
- [ ] `query_system()` in `retrieval/query.py` correctly passes class/subject to router
- [ ] No regression on conversational mode

---

## PHASE 2 — Intelligent Backtracking Engine

> **Goal**: When a student can't answer a diagnostic, retrieve ACTUAL lower-class content
> and teach from there. Reduce Phase 1 from 3 LLM calls to 1.

### What breaks today

`socratic.py` Phase 1 makes 3 sequential LLM calls (infer prereqs + pick prereq + generate question) and Phase 2 NEVER retrieves lower-class content — it just adjusts tone.

---

### 2.1 — New DB Model: `TopicPrerequisite`

**File**: [`db/models.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/db/models.py) — append after `Topic`

```python
class TopicPrerequisite(Base):
    """
    Structured prerequisite links between topics.
    Replaces topics.prerequisites unstructured JSON string.
    Enables cross-class backtracking by resolving prerequisites to actual DB content.
    """
    __tablename__ = "topic_prerequisites"
    id = Column(Integer, primary_key=True, index=True)

    topic_id           = Column(Integer, ForeignKey("topics.id"), nullable=False, index=True)
    prereq_topic_id    = Column(Integer, ForeignKey("topics.id"), nullable=True)

    prereq_class_num   = Column(Integer,     nullable=False)
    prereq_subject     = Column(String(100), nullable=False)
    prereq_chapter     = Column(String(200), nullable=True)
    prereq_description = Column(Text,        nullable=False)

    difficulty_order   = Column(Integer, default=0)           # 0 = most foundational
    expected_keywords  = Column(Text, nullable=True)           # JSON list

    source = Column(String(20), default="llm_inferred")       # "manual" | "llm_inferred"

    topic  = relationship("Topic", foreign_keys=[topic_id])
    prereq = relationship("Topic", foreign_keys=[prereq_topic_id])
```

---

### 2.2 — Understanding Detection (Algorithmic, Zero LLM)

**File**: [`tutor/patterns.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/tutor/patterns.py)

```python
_CONFUSION_MARKERS = re.compile(
    r"\b(i don'?t know|not sure|no idea|what is|idk|confused|"
    r"i forget|i forgot|not clear|unclear|just tell me|just give me)\b",
    re.IGNORECASE
)

_STRUCTURAL_COHERENCE = re.compile(
    r"\b(because|therefore|which means|this causes|as a result|"
    r"leads to|is defined as|refers to|consists of)\b",
    re.IGNORECASE
)

def detect_understanding(student_response: str, expected_keywords: list[str]) -> float:
    """
    Returns 0.0-1.0 understanding score. Purely algorithmic, zero LLM.

    Weights:
      40% — keyword overlap with expected concepts
      20% — response length and specificity
      20% — absence of confusion markers
      20% — structural coherence (cause-effect, definition patterns)
    """
    response_lower = student_response.lower()
    words = response_lower.split()
    n_words = len(words)

    # 1. Keyword overlap (40%)
    if expected_keywords:
        matched = sum(1 for kw in expected_keywords if kw.lower() in response_lower)
        keyword_score = matched / len(expected_keywords)
    else:
        keyword_score = 0.5

    # 2. Length/specificity (20%)
    if n_words >= 30:   length_score = 1.0
    elif n_words >= 15: length_score = 0.6
    elif n_words >= 5:  length_score = 0.3
    else:               length_score = 0.0

    # 3. Absence of confusion markers (20%)
    confusion_hits = len(_CONFUSION_MARKERS.findall(student_response))
    confusion_score = max(0.0, 1.0 - confusion_hits * 0.5)

    # 4. Structural coherence (20%)
    coherence_hits = len(_STRUCTURAL_COHERENCE.findall(student_response))
    coherence_score = min(1.0, coherence_hits * 0.4)

    return round(keyword_score * 0.40 + length_score * 0.20 +
                 confusion_score * 0.20 + coherence_score * 0.20, 3)


def detect_give_up(student_response: str) -> bool:
    """Detects if student explicitly gives up or requests to skip."""
    pattern = re.compile(
        r"\b(skip|don'?t care|forget it|never mind|just (tell|give) me|"
        r"move on|i give up|next topic)\b",
        re.IGNORECASE
    )
    return bool(pattern.search(student_response))
```

---

### 2.3 — Rewrite Socratic Phase 1 (3 LLM -> 1 LLM)

**File**: [`tutor/socratic.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/tutor/socratic.py)

```python
def start_diagnostic_v2(self, question, topic, chapter, class_num, subject, context, metrics, db):
    """
    Step 1: DB lookup for prerequisites (FREE)
    Step 2: Algorithmic prerequisite selection (FREE)
    Step 3: Generate ONE diagnostic question (1 LLM call only)
    """
    topic_row = db.query(Topic).filter(func.lower(Topic.title) == topic.lower()).first()
    prereqs = []
    if topic_row:
        prereqs = db.query(TopicPrerequisite).filter(
            TopicPrerequisite.topic_id == topic_row.id
        ).order_by(TopicPrerequisite.difficulty_order).all()

    if not prereqs:
        # Infer once via LLM, save to DB so it is FREE next time
        prereqs = self._infer_and_save_prerequisites(topic, chapter, subject, class_num, topic_row, db)

    chosen = self._algorithmic_pick(prereqs, metrics)
    keywords = json.loads(chosen.expected_keywords or "[]")
    diag_question = self._generate_one_diagnostic(question, chosen.prereq_description, keywords)

    state = {
        "phase": "awaiting_response",
        "original_question": question,
        "topic": topic, "chapter": chapter,
        "class_num": class_num, "subject": subject,
        "context": context,
        "prereq_description": chosen.prereq_description,
        "prereq_class_num": chosen.prereq_class_num,
        "prereq_subject": chosen.prereq_subject,
        "prereq_chapter": chosen.prereq_chapter,
        "expected_keywords": keywords,
        "backtrack_depth": 0,
        "visited_topics": [topic],   # loop guard
    }
    return diag_question, state


def _algorithmic_pick(self, prereqs, metrics):
    """Picks prerequisite algorithmically using cognitive metrics. No LLM."""
    if not prereqs: return None
    concept_und = (metrics.get("concept_master_score", 50) + metrics.get("assessment_accuracy", 50)) / 2.0
    if concept_und < 40:   return prereqs[-1]
    elif concept_und > 70: return prereqs[0]
    else:                  return prereqs[len(prereqs) // 2]
```

---

### 2.4 — Cross-Class Backtracking in Phase 2

**File**: [`tutor/socratic.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/tutor/socratic.py)

```python
def evaluate_and_explain(self, student_response, state, metrics, history, engine):
    from tutor.patterns import detect_understanding, detect_give_up

    understanding_score = detect_understanding(student_response, state.get("expected_keywords", []))
    gave_up  = detect_give_up(student_response)
    depth    = state.get("backtrack_depth", 0)
    visited  = state.get("visited_topics", [])
    MAX_DEPTH = 3
    THRESHOLD = 0.50

    # Path A: Give up or max depth
    if gave_up or depth >= MAX_DEPTH:
        return self._generate_base_concept_explanation(state), None

    # Path B: Student understands — teach original topic
    if understanding_score >= THRESHOLD:
        return self._teach_original_topic(state, history, metrics), None

    # Path C: Confused — backtrack to lower class
    prereq_class = state.get("prereq_class_num", state["class_num"] - 1)
    prereq_subj  = state.get("prereq_subject", state["subject"])
    prereq_ch    = state.get("prereq_chapter")
    prereq_desc  = state.get("prereq_description", "")

    backtrack_chunks = None
    backtrack_class  = None
    for offset in range(0, MAX_DEPTH - depth + 1):
        target_class = prereq_class - offset
        if target_class < 1: break
        if prereq_desc in visited: continue   # loop guard

        chunks = engine.retrieve(
            query=prereq_desc,
            routing_metadata={"class": target_class, "subject": prereq_subj, "chapter": prereq_ch},
            top_k=4, min_results=2,
        )
        if chunks:
            backtrack_chunks = chunks
            backtrack_class  = target_class
            break

    if not backtrack_chunks:
        return self._generate_base_concept_explanation(state), None

    context = "\n\n".join(c["content"] for c in backtrack_chunks)
    answer   = self._generate_backtrack_lesson(prereq_desc, context, backtrack_class, state, history)

    new_state = {
        **state,
        "prereq_description": prereq_desc,
        "prereq_class_num": backtrack_class,
        "context": context,
        "backtrack_depth": depth + 1,
        "visited_topics": visited + [prereq_desc],
        "phase": "awaiting_response",
    }
    return answer, new_state
```

**Edge Cases**:
- **Infinite loop**: `visited_topics` list in state prevents re-teaching same content
- **Class 1 rock bottom**: `_generate_base_concept_explanation` uses real-world analogies only
- **No content in lower class**: Falls back to analogy-based explanation
- **Student gives up — Adaptive Skip (NOT forced loop)**: When `detect_give_up()` returns `True`, do NOT loop or re-ask. Instead, give a complete, direct explanation of the current topic with the full answer, but attach a soft note at the end:
  > *"I've explained it fully! When you're ready, try solving [micro-exercise] so it sticks in your memory 🧠"*
  This respects the student's frustration while still nudging toward consolidation — no forcing, but no blind giving up either.

### Phase 2 Verification

- [ ] Phase 1 makes exactly 1 LLM call (count from logs)
- [ ] `detect_understanding("I don't know", [])` returns < 0.3
- [ ] `detect_understanding("CO2 is converted because chlorophyll absorbs light", ["CO2", "chlorophyll"])` returns > 0.7
- [ ] Backtracking retrieves Class 8 content when Class 10 student fails Class 8 prereq
- [ ] `visited_topics` prevents same prereq being re-taught in one session
- [ ] `gave_up` breaks the loop on "just tell me the answer"

---

## PHASE 3 — Topic Mastery & Structured Memory

> **Goal**: Replace flat 8-bullet memory with per-topic mastery tracking. Inject ONLY
> relevant memories into the prompt.

### What breaks today

`student_subject_profiles.student_memory` is a flat JSON blob of 8 bullets for the
entire subject, injected into every prompt regardless of topic relevance.

---

### 3.1 — New DB Model: `StudentTopicMastery`

**File**: [`db/models.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/db/models.py)

```python
class StudentTopicMastery(Base):
    """Per-student, per-topic understanding tracker. Replaces flat student_memory."""
    __tablename__ = "student_topic_mastery"
    id = Column(Integer, primary_key=True, index=True)

    student_id = Column(String(100), ForeignKey("students.id"), nullable=False, index=True)
    topic_id   = Column(Integer, ForeignKey("topics.id"),   nullable=False, index=True)

    mastery_level       = Column(Float,   default=0.0,  nullable=False)   # 0-100
    times_visited       = Column(Integer, default=0,    nullable=False)
    last_visited        = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    first_visited       = Column(DateTime(timezone=True), server_default=func.now())

    understood_concepts = Column(Text, nullable=True)   # JSON list
    confused_concepts   = Column(Text, nullable=True)   # JSON list
    common_mistakes     = Column(Text, nullable=True)   # JSON list

    required_backtrack  = Column(Boolean, default=False)
    backtrack_depth     = Column(Integer, default=0)
    backtrack_class     = Column(Integer, nullable=True)

    student = relationship("Student")
    topic   = relationship("Topic")

    __table_args__ = (
        UniqueConstraint("student_id", "topic_id", name="uq_student_topic_mastery"),
    )
```

---

### 3.2 — Mastery Update Logic

**File**: [`db/profile.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/db/profile.py)

```python
def update_topic_mastery(
    db, student_id, topic_id, understanding_score,
    was_backtracked=False, backtrack_depth=0, backtrack_class=None,
    understood_concepts=None, confused_concepts=None,
):
    """Creates or updates StudentTopicMastery. Uses weighted moving average."""
    mastery = db.query(StudentTopicMastery).filter(
        StudentTopicMastery.student_id == student_id,
        StudentTopicMastery.topic_id == topic_id,
    ).first()

    if not mastery:
        mastery = StudentTopicMastery(student_id=student_id, topic_id=topic_id)
        db.add(mastery)

    # Weighted moving average: new score weighted 30%
    delta = (understanding_score * 100 - mastery.mastery_level) * 0.30
    mastery.mastery_level = max(0.0, min(100.0, mastery.mastery_level + delta))
    mastery.times_visited += 1

    if understood_concepts:
        existing = json.loads(mastery.understood_concepts or "[]")
        mastery.understood_concepts = json.dumps(list(set(existing + understood_concepts))[:20])

    if confused_concepts:
        existing = json.loads(mastery.confused_concepts or "[]")
        mastery.confused_concepts = json.dumps(list(set(existing + confused_concepts))[:20])

    if was_backtracked:
        mastery.required_backtrack = True
        mastery.backtrack_depth = max(mastery.backtrack_depth, backtrack_depth)
        if backtrack_class: mastery.backtrack_class = backtrack_class

    return mastery


def apply_mastery_decay(db, student_id: str, subject: str) -> None:
    """
    Reduces mastery_level for stale topics.
    Decay interval is controlled by MASTERY_DECAY_DAYS in .env (default: 30).
    Decay rate is controlled by MASTERY_DECAY_RATE in .env (default: 0.05 = 5% per interval).

    Add to .env:
        MASTERY_DECAY_DAYS=30
        MASTERY_DECAY_RATE=0.05
    """
    import os
    from datetime import datetime, timezone, timedelta

    DECAY_DAYS  = int(os.getenv("MASTERY_DECAY_DAYS", 30))
    DECAY_RATE  = float(os.getenv("MASTERY_DECAY_RATE", 0.05))
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=DECAY_DAYS)

    stale_topics = db.query(StudentTopicMastery).filter(
        StudentTopicMastery.student_id == student_id,
        StudentTopicMastery.last_visited < cutoff_date,
        StudentTopicMastery.mastery_level > 0.0,
    ).all()

    for m in stale_topics:
        m.mastery_level = max(0.0, m.mastery_level * (1.0 - DECAY_RATE))

    if stale_topics:
        db.commit()
        logger.info(f"Decay applied to {len(stale_topics)} stale topics for student {student_id}")
```

---

### 3.3 — Contextual Memory Injection

**File**: [`db/profile.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/db/profile.py)

```python
def get_relevant_topic_memories(db, student_id, topic_id, prereq_topic_ids=None) -> dict:
    """Returns ONLY memories for current topic and prerequisites. Max 3 topics."""
    from datetime import datetime, timezone
    target_ids = [topic_id] + (prereq_topic_ids or [])
    masteries = db.query(StudentTopicMastery).filter(
        StudentTopicMastery.student_id == student_id,
        StudentTopicMastery.topic_id.in_(target_ids[:3]),
    ).all()

    result = {}
    for m in masteries:
        days_stale = (datetime.now(timezone.utc) - m.last_visited).days if m.last_visited else 0
        result[m.topic_id] = {
            "mastery_level": round(m.mastery_level, 1),
            "times_visited": m.times_visited,
            "understood": json.loads(m.understood_concepts or "[]")[:5],
            "confused": json.loads(m.confused_concepts or "[]")[:5],
            "required_backtrack": m.required_backtrack,
            "knowledge_stale": days_stale > 30,
            "days_since_visit": days_stale,
        }
    return result
```

---

### 3.4 — Prompt Memory Block

**File**: [`tutor/llm.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/tutor/llm.py)

```python
def _build_topic_memory_block(self, topic_memories: dict) -> str:
    if not topic_memories:
        return "First time on this topic. Start from fundamentals."

    lines = ["TOPIC HISTORY:"]
    for _, m in topic_memories.items():
        stale = f" [STALE — {m['days_since_visit']}d ago, recap gently]" if m["knowledge_stale"] else ""
        bt    = " [needed backtracking before]" if m["required_backtrack"] else ""
        knows = ", ".join(m["understood"]) if m["understood"] else "nothing recorded"
        confused = ", ".join(m["confused"]) if m["confused"] else "none"
        lines.append(
            f"Mastery {m['mastery_level']:.0f}% | {m['times_visited']} visits{stale}{bt} | "
            f"Knows: [{knows}] | Confused by: [{confused}]"
        )
    return "\n".join(lines)
```

### Phase 3 Verification

- [ ] `StudentTopicMastery` record created on first topic visit
- [ ] Mastery increases after understanding_score > 0.5
- [ ] Mastery decreases when backtrack triggered
- [ ] LLM prompt contains ONLY memories for current topic, not all 8 global bullets
- [ ] Knowledge decay note appears for topics older than `MASTERY_DECAY_DAYS` env var (default 30)
- [ ] `apply_mastery_decay()` reduces mastery level by `MASTERY_DECAY_RATE` after the configured interval
- [ ] `update_topic_mastery()` called from `chat.py` after every Socratic Phase 2 eval
- [ ] Changing `MASTERY_DECAY_DAYS=60` in `.env` and restarting correctly changes the stale threshold

---

## PHASE 4 — Deterministic Cognitive Profiling

> **Goal**: Remove LLM guessing of 10 cognitive metrics. Derive them mathematically
> from `StudentTopicMastery` data.

### What breaks today

`batch_update_cognitive_profile()` sends raw signals to LLM every 4 turns.
LLM returns 10 absolute metric values — non-deterministic. `assessment_accuracy` never measured.

---

### 4.1 — New Turn-Level Signal Detectors

**File**: [`db/metrics.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/db/metrics.py)

```python
def detect_answer_correctness(student_response: str, expected_keywords: list[str]) -> float:
    """Directly measures assessment_accuracy when tutor asked a direct question."""
    from tutor.patterns import detect_understanding
    return detect_understanding(student_response, expected_keywords)


def detect_self_correction(student_response: str, prev_student_response: str | None) -> bool:
    """True if student corrects themselves — signal for struggle_recovery_rate."""
    if not prev_student_response: return False
    markers = re.compile(
        r"\b(actually|wait|i mean|let me correct|i think i was wrong|no wait)\b",
        re.IGNORECASE
    )
    return bool(markers.search(student_response))


def detect_misconception(student_response: str) -> list[str]:
    """Returns list of misconception patterns — populates confused_concepts."""
    MISCONCEPTIONS = {
        "heat_cold":         r"\b(cold is a thing|coldness enters|cold air flows)\b",
        "evolution_goal":    r"\b(animals evolve to|species want to evolve)\b",
        "current_direction": r"\b(current flows from negative|electrons are current)\b",
    }
    return [name for name, pat in MISCONCEPTIONS.items()
            if re.search(pat, student_response, re.IGNORECASE)]
```

---

### 4.2 — Compute Metrics FROM Mastery (Pure Math, No LLM)

**File**: [`db/profile.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/db/profile.py)

```python
def recompute_subject_metrics_from_mastery(db, student_id: str, subject: str) -> dict:
    """Derives all subject metrics from StudentTopicMastery. No LLM. Pure math."""
    masteries = (
        db.query(StudentTopicMastery)
        .join(Topic).join(Chapter).join(DBSubject)
        .filter(
            StudentTopicMastery.student_id == student_id,
            func.lower(DBSubject.name) == subject.lower(),
        ).all()
    )
    if not masteries: return {}

    n                = len(masteries)
    total_mastery    = sum(m.mastery_level for m in masteries)
    visited_more     = [m for m in masteries if m.times_visited > 1]
    backtracks       = [m for m in masteries if m.required_backtrack]
    revisit_improved = [m for m in visited_more if m.mastery_level > 50]
    fast_mastered    = [m for m in masteries if m.mastery_level > 60 and m.times_visited <= 2]
    repeat_struggles = [m for m in masteries if m.required_backtrack and m.times_visited > 2]

    profile = get_or_create_subject_profile(db, student_id, subject)

    profile.concept_master_score   = total_mastery / n
    profile.knowledge_retention    = len(revisit_improved) / max(1, len(visited_more)) * 100.0
    profile.struggle_recovery_rate = (1.0 - len(backtracks) / n) * 100.0
    profile.learning_velocity      = len(fast_mastered) / n * 100.0
    profile.error_repetition_rate  = len(repeat_struggles) / n   # 0.0 - 1.0

    db.commit()
    return get_subject_metrics(db, student_id, subject)
```

---

### 4.3 — Replace Batch-Per-4-Turns Metric LLM with Math

**File**: [`tutor/chat.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/tutor/chat.py)

```python
# BEFORE: LLM call for metrics every 4 turns
if turn_count % BATCH_TURN_INTERVAL == 0:
    batch_update_cognitive_profile(...)   # LLM guesses 10 metric values

# AFTER: Metrics computed from mastery after every Socratic evaluation (no LLM)
recompute_subject_metrics_from_mastery(db, request.student_id, request.subject)

# LLM still fires every 4 turns BUT only to update student_memory (identity facts, not numbers)
if turn_count % BATCH_TURN_INTERVAL == 0:
    update_student_memory_text_only(request.student_id, request.subject, recent_turns_text)
```

### Phase 4 Verification

- [ ] `concept_master_score` changes after topic visits (verify via DB query)
- [ ] `knowledge_retention` increases when student revisits topic with better score
- [ ] `error_repetition_rate` increases when same topic requires backtrack twice
- [ ] `learning_velocity` increases when student masters topic in <= 2 visits
- [ ] No LLM call fires for numeric metric update on standard turns

---

## PHASE 5 — Token Budget & Tiered Caching

> **Goal**: Cut per-turn token spend by ~40% via caching and conditional prompt injection.

### What wastes tokens today

| Source | Waste per turn |
|---|---|
| Full personalization block on EVERY turn | ~300 tokens |
| All 8 memory bullets regardless of topic | ~150 tokens |
| Unbounded session summary | ~200 tokens |
| Exact-match cache key (misses case/whitespace) | Full embed + DB query wasted |
| Full prompt saved to `prompt_logs` table | DB storage bloat |

---

### 5.1 — Token Budget System

**File**: [`tutor/llm.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/tutor/llm.py)

```python
class TokenBudget:
    MAX_SYSTEM   = 600    # Fixed system prompt
    MAX_CONTEXT  = 1200   # RAG curriculum content
    MAX_HISTORY  = 400    # Last 4 messages verbatim
    MAX_SUMMARY  = 200    # Compressed session summary
    MAX_MEMORY   = 100    # Topic-specific memories (Phase 3)
    MAX_PERSONA  = 150    # Personalization (conditional)
    TOTAL        = 2650   # Target input budget

    def should_include_personalization(self, metrics_changed: bool) -> bool:
        """Only inject personalization block when metrics actually changed."""
        return metrics_changed

    def truncate_summary(self, summary: str) -> str:
        return summary[-800:] if len(summary) > 800 else summary   # ~200 tokens

    def truncate_context(self, context: str) -> str:
        return context[:4800] if len(context) > 4800 else context  # ~1200 tokens
```

---

### 5.2 — 3-Layer Retrieval Cache

**File**: [`retrieval/cache.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/retrieval/cache.py)

```python
def _normalize(self, query: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", query.lower().strip()))

def _scoped_key(self, query, class_num, subject) -> str:
    norm = self._normalize(query)
    return f"retrieval:{class_num or 'any'}:{(subject or 'any').lower()}:{norm}"

# Layer 1: Embedding cache (24h TTL)
def get_embedding(self, query) -> list[float] | None: ...
def set_embedding(self, query, vector) -> None: ...

# Layer 2: Scoped retrieval cache
# TTL: 30 days (curriculum is static — confirmed will not change for at least 1 year)
def get_chunks(self, query, class_num, subject) -> list[dict] | None: ...
def set_chunks(self, query, class_num, subject, chunks, ttl=2592000) -> None: ...  # 30 days

# Layer 3: Prerequisite cache
# TTL: 30 days (prerequisite relationships are tied to curriculum — equally static)
def get_prerequisites(self, topic_id) -> list[dict] | None: ...
def set_prerequisites(self, topic_id, prereqs, ttl=2592000) -> None: ...  # 30 days

# Layer 1: Embedding cache
# TTL: 7 days (normalized queries won't change but we refresh weekly for safety)
def get_embedding(self, query) -> list[float] | None: ...
def set_embedding(self, query, vector, ttl=604800) -> None: ...  # 7 days

# Cache invalidation — only needed if curriculum is re-ingested (rare)
def invalidate_chapter(self, class_num, subject, chapter) -> int:
    pattern = f"retrieval:{class_num}:{subject.lower()}:*"
    keys = self.redis_client.keys(pattern)
    if keys: self.redis_client.delete(*keys)
    return len(keys)
```

**Edge Case — Redis Outage**: All methods wrap in `try/except`, return `None` on failure.
System degrades to direct DB queries without breaking chat flow.

> [!NOTE]
> With 30-day TTLs, all cache keys from a curriculum re-ingestion would be stale.
> Call `cache.invalidate_chapter(class_num, subject, chapter)` after any curriculum update
> to flush only the affected chapter scope, not the entire cache.

---

### 5.3 — Plug Caches into Retrieval Engine

**File**: [`retrieval/engine.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/retrieval/engine.py)

```python
def retrieve(self, query, routing_metadata, top_k=5, min_results=3):
    class_num = routing_metadata.get("class")
    subject   = routing_metadata.get("subject")

    cached = self.cache.get_chunks(query, class_num, subject)
    if cached:
        logger.info("Retrieval cache HIT — skipping embed + DB query")
        return cached

    query_vector = self.cache.get_embedding(query)
    if query_vector is None:
        query_vector = self.embedder.embed_query(query)
        self.cache.set_embedding(query, query_vector)

    results = self._cascade_retrieve(query_vector, routing_metadata, top_k, min_results)
    self.cache.set_chunks(query, class_num, subject, results)
    return results
```

---

### 5.4 — Lightweight Prompt Logs

**File**: [`tutor/llm.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/tutor/llm.py)

```python
# BEFORE — saves 3000+ char full prompt every turn
db.add(PromptLog(session_id=session_id, prompt_payload=json.dumps(messages)))

# AFTER — saves tiny metadata dict only
db.add(PromptLog(
    session_id=session_id, student_id=student_id,
    prompt_payload=json.dumps({
        "question_type": question_type, "class_num": class_num,
        "subject": subject, "context_chars": len(context),
        "history_turns": len(history), "topic": routed_topic,
        "cache_hit": was_cache_hit,
    })
))
```

### Phase 5 Verification

- [ ] Second identical question from same class/subject gets cache HIT in logs
- [ ] "what is ph" and "What is pH?" hit the same normalized cache key
- [ ] Personalization block absent when metrics haven't changed this turn
- [ ] Session summary truncated at 800 chars before injection
- [ ] Redis outage test: disconnect Redis -> chat still works via DB fallback
- [ ] `prompt_log` row is < 300 bytes after the change

---

### Phase 1 — Files Changed

| File | Change |
|---|---|
| [`db/models.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/db/models.py) | Add `index=True` to filter columns in both vector tables |
| [`schemas.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/schemas.py) | Add optional `class_num` to `ChatRequest` |
| [`routing/vector_store.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/routing/vector_store.py) | Scoped pre-filters + global fallback |
| [`routing/router.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/routing/router.py) | Accept + pass `class_num`, `subject` |
| [`retrieval/engine.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/retrieval/engine.py) | 3-level cascade retrieval |
| [`retrieval/query.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/retrieval/query.py) | Accept + pass `class_num`, `subject` |
| [`tutor/chat.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/tutor/chat.py) | Pre-filter routing + resolve `class_num` |
| [`api.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/api.py) | 3 curriculum browse endpoints |

---

## Full File Impact Summary

| File | Phase(s) | Change |
|---|---|---|
| [`db/models.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/db/models.py) | 1, 2, 3 | Indexes + 2 new tables |
| [`db/profile.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/db/profile.py) | 3, 4 | Mastery CRUD + metric recompute + decay |
| [`db/metrics.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/db/metrics.py) | 4 | 3 new signal detectors |
| [`schemas.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/schemas.py) | 1 | Add optional `class_num` to `ChatRequest` |
| [`routing/vector_store.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/routing/vector_store.py) | 1 | Scoped pre-filters |
| [`routing/router.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/routing/router.py) | 1 | Accept + pass class/subject |
| [`retrieval/engine.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/retrieval/engine.py) | 1, 5 | Cascade retrieval + cache |
| [`retrieval/query.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/retrieval/query.py) | 1 | Accept + pass class/subject to router |
| [`retrieval/cache.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/retrieval/cache.py) | 5 | 3-layer cache (30-day TTLs) |
| [`tutor/chat.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/tutor/chat.py) | 1, 2, 3, 4 | Orchestration wiring |
| [`tutor/llm.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/tutor/llm.py) | 3, 5 | Memory injection + token budget |
| [`tutor/socratic.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/tutor/socratic.py) | 2 | 1-call Phase 1 + backtracking + adaptive skip |
| [`tutor/patterns.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/tutor/patterns.py) | 2 | Understanding detection |
| [`api.py`](file:///c:/Users/manit/OneDrive/Desktop/code/Vishwalpha/AI%20Tutor/api.py) | 1 | Browse endpoints |

### New `.env` Variables Required

```env
# Phase 3 — Mastery decay configuration
MASTERY_DECAY_DAYS=30        # days without revisit before decay triggers
MASTERY_DECAY_RATE=0.05      # 5% reduction per decay interval
```

> [!IMPORTANT]
> **Start with Phase 1** — it fixes the most critical correctness bug and is a hard
> dependency for Phase 2 (backtracking needs correctly-scoped retrieval to find lower-class content).

> [!NOTE]
> **Alembic migrations needed**: Phases 1, 2, and 3 add columns/tables.
> After each phase: `alembic revision --autogenerate -m "phase_X" && alembic upgrade head`

> **Goal**: Overhaul the VishwAlpha AI Tutor backend to implement scoped routing, intelligent cross-class backtracking, structured topic-level memory, deterministic cognitive profiling, and tiered caching, while handling edge cases securely.

---

## 1. RAG Pipeline & Routing Redesign

### Current Issues Addressed
- Global unscoped routing leading to wrong-class content.
- Hard string matching (`AND` logic) causing zero results on slight mismatches.
- Overwriting class metadata *after* routing instead of *during* it.

### Implementation Steps

#### 1.1 Database Indexes
- **Add DB Indexes**: Add `index=True` to `class_num`, `subject`, `chapter` columns in both `curriculum_routing` and `curriculum_content` tables to prevent full-table scans.

#### 1.2 Scoped Semantic Routing
- **Modify `search_routes`**: Update `routing/vector_store.py` to accept `class_num` and `subject` filters. Apply these filters *before* the `ORDER BY cosine_distance`.
- **Pass Metadata**: Update `routing/router.py` to accept the student's class and subject and pass them to the vector store.
- **Edge Case - Missing Student Class**: If a student's class is missing or they are a guest, fallback to an unscoped global search, returning the class level that best matches semantically.

#### 1.3 Cascading Fallback Retrieval
- **Modify `retrieve`**: Update `retrieval/engine.py` to implement a 3-tier cascade:
  1. `class` + `subject` + `chapter` + `topic` (Target exactly ≥ 3 chunks)
  2. `class` + `subject` + `chapter` (Fallback if < 3 chunks)
  3. `class` + `subject` (Ultimate fallback if still < 3 chunks)
- **Edge Case - Cross-Class Queries**: If a student explicitly asks "How is this related to 12th class physics?" (explicit class mention), the router must detect the explicit class override and search the target class instead of the enrolled class.

#### 1.4 Smart Reranking
- Implement chunk deduplication and diversity in `retrieval/reranker.py` to ensure all 5 retrieved chunks don't come from the exact same sub-paragraph.

---

## 2. Intelligent Socratic Backtracking

### Current Issues Addressed
- 3 sequential LLM calls per diagnostic question (slow, expensive).
- No actual retrieval of lower-class prerequisite content.
- No algorithmic way to detect if a student understood the diagnostic answer.

### Implementation Steps

#### 2.1 Structured Prerequisites
- **New DB Model (`TopicPrerequisite`)**: Create a structured table linking a `topic_id` to a `prereq_topic_id`, tracking the `prereq_class_num` and `expected_keywords`.
- **Edge Case - Missing Prerequisite**: If the DB has no prerequisite for a topic, fallback to inferring it via a single LLM call, but *save the result to the DB* so it is only paid for once.

#### 2.2 Algorithmic Understanding Detection
- **Detect Understanding without LLM**: Implement `detect_understanding(student_response, expected_keywords)` in `tutor/patterns.py`. Use keyword overlap, absence of confusion markers ("not sure", "what"), and response length.
- **Edge Case - False Negatives/Positives**: If the system thinks the student understands but they explicitly say "I still don't get it" in the next turn, immediately decay the mastery score and force a backtrack.

#### 2.3 Cross-Class Backtracking Engine
- **Backtrack Logic**: If understanding score < 0.5, trigger backtracking. Search downward (Class-1, Class-2, max 3 levels deep) for the prerequisite topic content.
- **Edge Case - Rock Bottom**: If the student reaches Class 1 and still fails, or drops 3 levels down, trigger a "Base Concept Explanation" mode which explains the concept using real-world analogies (no prerequisites assumed).
- **Edge Case - Infinite Loops**: Track `visited_topics` in the current session state. If the system attempts to backtrack to a topic it already taught 5 minutes ago, break the loop and alert the student with a simplified summary.

---

## 3. Structured Memory & Personalisation

### Current Issues Addressed
- Memory is a flat 8-bullet list, wasting tokens on irrelevant facts.
- LLM merges overwrite memory non-deterministically.
- No continuity when a student returns to a topic later.

### Implementation Steps

#### 3.1 Topic Mastery Model
- **New DB Model (`StudentTopicMastery`)**: Track `mastery_level` (0-100), `times_visited`, `understood_concepts` (JSON), and `confused_concepts` (JSON) strictly per topic per student.

#### 3.2 Contextual Memory Injection
- **Targeted Injection**: Update `tutor/llm.py` to fetch memories *only* for the `current_topic_id` and its immediate prerequisites. Stop injecting global memory bullets.
- **Edge Case - First Time Topic**: If `StudentTopicMastery` doesn't exist for the topic, fallback to the student's global `learning_style` preferences.
- **Edge Case - Conflicting History**: If a student mastered a topic 6 months ago but fails it today, the system must detect the temporal gap (using `last_visited`) and treat it as "Knowledge Decay", gently reminding them of what they used to know.

#### 3.3 Structured Session Summaries
- Generate a structured end-of-session summary (Topics Discussed, Concepts Mastered, Concepts Confused) instead of a flat paragraph.

---

## 4. Deterministic Cognitive Profiling

### Current Issues Addressed
- Subject metrics (velocity, retention, etc.) are arbitrarily guessed by the LLM every 4 turns.

### Implementation Steps

#### 4.1 Algorithmic Metric Computation
- **Remove LLM Metric Guesses**: Replace the 4-turn LLM batch update in `db/metrics.py` with an algorithmic aggregator.
- Compute `concept_master_score` as the strict average of `mastery_level` across all `StudentTopicMastery` records for that subject.
- Compute `knowledge_retention` based on the delta of mastery scores when a student revisits a topic.
- Compute `struggle_recovery_rate` by tracking how often an understanding score goes from <0.5 to >0.8 within a single session.

#### 4.2 Turn-Level Signals
- Add deterministic signals: `detect_answer_correctness`, `detect_self_correction`, and `detect_misconception`.

---

## 5. Token Optimization & Caching Strategy

### Current Issues Addressed
- Identical queries burn tokens on embeddings and LLM generation.
- Full context pushed every turn.

### Implementation Steps

#### 5.1 Tiered Caching (`retrieval/cache.py`)
- **Layer 1: Embedding Cache**: Cache `normalized(query) -> vector`.
- **Layer 2: Retrieval Cache**: Cache `class_num:subject:normalized_query -> [chunks]`.
- **Layer 3: Prerequisite Cache**: Cache `topic_id -> prerequisites`.
- **Edge Case - Cache Poisoning**: Implement cache invalidation hooks. If the curriculum ingestion script runs and updates a topic, automatically flush all Redis keys matching `*:chapter_name:*`.
- **Edge Case - Redis Outage**: Wrap all cache calls in strict `try/except`. If Redis times out, gracefully degrade to direct DB queries without breaking the chat flow.

#### 5.2 Token Budgeting
- Implement `TokenBudget` in `tutor/llm.py`.
- Cap history to 400 tokens, memory to 100 tokens, and context to 1200 tokens.

---

## User Review Required / Open Questions

> [!IMPORTANT]
> Please review and approve these edge-case decisions:
> 
> 1. **Backtrack Limit**: Is a maximum depth of **3 classes back** acceptable to prevent the AI from overwhelming the student with primary school concepts?
> 2. **Mastery Decay**: Should topic mastery naturally decay over time? (e.g., dropping 5% every month the topic is not reviewed).
> 3. **Explicit Overrides**: If a student says "I don't care about the prerequisite, just tell me the answer", should we allow them to skip Socratic backtracking, or force them to complete it?
> 4. **Cache Invalidation**: How frequently is the curriculum database updated? If it's static, we can set Redis TTLs to 30 days. If it's dynamic, we need shorter TTLs.
