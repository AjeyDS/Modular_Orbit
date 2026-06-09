# Two-Mode Chat Retrieval Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the four chat modes with **Fast** (pure chunk RAG) and **Understanding** (router selects 1–3 Story Buckets → focused retrieval → conditional one follow-up → synthesis), without diluting the retrieval query with user-model content.

**Architecture:** All new logic lives in `backend/app/chat/actions.py`, built from small, individually-testable helpers (a router with a lexical fallback, a pure retrieval-query builder, a sufficiency check, and a bucket-content fetch). Story Buckets are **not** vectorized; the router reads their one-line descriptions. Every LLM call has a deterministic fallback so the stubbed-LLM test suite stays green. The frontend swaps its four-mode picker for two.

**Tech Stack:** FastAPI + psycopg, Pydantic v2, pytest + FastAPI TestClient; React + TypeScript + Vite.

**Design reference:** `docs/plans/2026-06-09-two-mode-chat-retrieval-design.md`

**Conventions:**
- Run backend tests from `backend/`: `python -m pytest tests/test_x.py::test_name -v`.
- Chat tests use the `_ready(tmp_path)` fixture pattern in `tests/test_chat_actions.py`.
- LLM helpers wrap `generate_json`/`generate_text` in `try/except (LLMUnavailable, Exception)` and fall back deterministically (see `_detect_suggested_with_llm` at `actions.py:190`).
- Commit after each task.

**Anti-dilution principle (the thing this plan exists to protect):** in Understanding mode, buckets shape *retrieval* only when the query is broad. For narrow queries the retrieval query is the user's words verbatim. Buckets always feed *synthesis*, never the narrow-query search string.

---

## Task 1: Switch ChatMode to `fast | understanding`

**Files:**
- Modify: `backend/app/chat/actions.py` (`ChatMode`, `ChatRequest.mode` default, `_chat_system_prompt`, `_mode_answer`)
- Modify: `backend/tests/test_chat_actions.py` (existing tests referencing old modes)
- Test: `backend/tests/test_chat_actions.py`

**Step 1: Write the failing test**

```python
def test_chat_mode_accepts_two_modes(tmp_path) -> None:
    _ready(tmp_path)
    fast = respond_to_chat(ChatRequest(session_id=_session_id("fast"), mode="fast", message="hi there orbit"))
    understanding = respond_to_chat(ChatRequest(session_id=_session_id("u"), mode="understanding", message="hi there orbit"))
    assert fast.mode == "fast"
    assert understanding.mode == "understanding"
```

**Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_chat_actions.py::test_chat_mode_accepts_two_modes -v`
Expected: FAIL (pydantic validation rejects `"fast"`/`"understanding"`).

**Step 3: Implement**

- `actions.py`: `ChatMode = Literal["fast", "understanding"]`; set `ChatRequest.mode` default to `"understanding"`.
- Collapse `_chat_system_prompt(mode)` to two branches:
  - `fast`: base + "This is Fast Chat: answer directly from retrieved knowledge; minimal assumptions."
  - `understanding` (default): base + "This is Understanding Chat: use the selected Story Buckets to frame and personalize, but answer the user's actual question; do not wander."
- Collapse `_mode_answer(mode, has_suggestion)` to two branches with equivalent fallback copy.
- Update existing tests that pass `mode="context"`/`"free"`/`"deep"`/`"decision"` (grep `tests/test_chat_actions.py`) to `"understanding"`/`"fast"`, and any `assert response.mode == "context"` accordingly.

**Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_chat_actions.py -v`
Expected: PASS (all chat tests green).

**Step 5: Commit**

```bash
git add backend/app/chat/actions.py backend/tests/test_chat_actions.py
git commit -m "refactor(chat): replace four chat modes with fast and understanding"
```

---

## Task 2: Bucket router with lexical fallback

**Files:**
- Modify: `backend/app/chat/actions.py` (new `RouteDecision`, `_route_and_classify`, `_breadth_fallback`, `_select_buckets_fallback`, `_route_prompt`)
- Test: `backend/tests/test_chat_actions.py`

**Step 1: Write the failing test** (stub-LLM exercises the fallback)

```python
def test_router_fallback_selects_buckets_and_breadth(tmp_path) -> None:
    _ready(tmp_path)
    from app.chat.actions import _route_and_classify
    narrow = _route_and_classify("when is my dentist appointment on friday")
    broad = _route_and_classify("what are the main things I should focus on in my life right now")
    assert narrow.breadth == "narrow"
    assert broad.breadth == "broad"
    assert all(key in {
        "who_am_i","goals","interests_and_works","career","health","relationships","habits","aspirations"
    } for key in broad.buckets)
    assert 1 <= len(broad.buckets) <= 3
    # narrow query gets no expansion terms
    assert narrow.expansion_terms == []
```

**Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_chat_actions.py::test_router_fallback_selects_buckets_and_breadth -v`
Expected: FAIL (`_route_and_classify` missing).

**Step 3: Implement**

```python
from dataclasses import dataclass, field

KNOWN_BUCKET_KEYS = {
    "who_am_i","goals","interests_and_works","career",
    "health","relationships","habits","aspirations",
}
_BROAD_MARKERS = (
    "what should i", "what are the things", "what do i", "focus on",
    "my life", "everything", "overall", "in general", "priorities",
    "where should i", "how am i doing",
)

@dataclass
class RouteDecision:
    breadth: str  # "narrow" | "broad"
    buckets: list[str] = field(default_factory=list)
    expansion_terms: list[str] = field(default_factory=list)
    rationale: str = ""

def _bucket_catalog() -> list[dict[str, str]]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT stable_key, display_name, description FROM story_buckets WHERE status='active'"
            )
            return [dict(row) for row in cur.fetchall()]

def _route_and_classify(message: str) -> RouteDecision:
    catalog = _bucket_catalog()
    try:
        data = generate_json(
            _route_prompt(message, catalog),
            system=(
                "You route a personal-assistant query to the user's story buckets. "
                "Return only JSON. breadth is 'narrow' for specific questions and "
                "'broad' for wide/vague life questions. Pick 1-3 bucket keys. "
                "expansion_terms is non-empty ONLY when breadth is broad."
            ),
            temperature=0.1,
            max_output_tokens=400,
        )
        breadth = data.get("breadth")
        if breadth not in {"narrow", "broad"}:
            raise ValueError("bad breadth")
        buckets = [k for k in (data.get("buckets") or []) if k in KNOWN_BUCKET_KEYS][:3]
        terms = [str(t).strip() for t in (data.get("expansion_terms") or []) if str(t).strip()]
        if breadth == "narrow":
            terms = []
        if not buckets:
            buckets = _select_buckets_fallback(message, catalog)
        return RouteDecision(breadth=breadth, buckets=buckets, expansion_terms=terms,
                             rationale=str(data.get("rationale") or ""))
    except (LLMUnavailable, Exception):
        breadth = _breadth_fallback(message)
        return RouteDecision(
            breadth=breadth,
            buckets=_select_buckets_fallback(message, catalog),
            expansion_terms=[],
            rationale="lexical fallback",
        )

def _breadth_fallback(message: str) -> str:
    lowered = message.lower()
    if any(marker in lowered for marker in _BROAD_MARKERS):
        return "broad"
    # short, open questions lean broad; otherwise narrow
    return "broad" if len(_tokens(message)) <= 3 else "narrow"

def _select_buckets_fallback(message: str, catalog: list[dict[str, str]] | None = None) -> list[str]:
    catalog = catalog if catalog is not None else _bucket_catalog()
    tokens = set(_tokens(message))
    scored = sorted(
        catalog,
        key=lambda b: _overlap(tokens, f"{b['display_name']} {b['description']}"),
        reverse=True,
    )
    picked = [b["stable_key"] for b in scored if _overlap(tokens, f"{b['display_name']} {b['description']}") > 0][:3]
    return picked or [scored[0]["stable_key"]] if scored else []

def _route_prompt(message: str, catalog: list[dict[str, str]]) -> str:
    lines = "\n".join(f"- {b['stable_key']}: {b['display_name']} — {b['description']}" for b in catalog)
    return (
        "Buckets:\n" + lines + "\n\n"
        'Return JSON: {"breadth":"narrow|broad","buckets":["key"],'
        '"expansion_terms":["..."],"rationale":"one line"}\n\n'
        f"Query:\n{message}"
    )
```

(`_tokens` and `_overlap` already exist in `actions.py`.)

**Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_chat_actions.py::test_router_fallback_selects_buckets_and_breadth -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/chat/actions.py backend/tests/test_chat_actions.py
git commit -m "feat(chat): add bucket router with breadth classification and lexical fallback"
```

---

## Task 3: Pure retrieval-query builder (anti-dilution guard)

**Files:**
- Modify: `backend/app/chat/actions.py` (`_retrieval_query`)
- Test: `backend/tests/test_chat_actions.py`

**Step 1: Write the failing test**

```python
def test_retrieval_query_does_not_dilute_narrow(tmp_path) -> None:
    _ready(tmp_path)
    from app.chat.actions import _retrieval_query, RouteDecision
    narrow = RouteDecision(breadth="narrow", buckets=["career"], expansion_terms=["promotion","mentoring"])
    broad = RouteDecision(breadth="broad", buckets=["career","aspirations"], expansion_terms=["promotion","mentoring"])
    msg = "when is my dentist appointment"
    assert _retrieval_query(msg, narrow) == msg            # verbatim, no expansion
    assert "promotion" in _retrieval_query(msg, broad)     # broad applies expansion
    assert _retrieval_query(msg, broad).startswith(msg)
```

**Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_chat_actions.py::test_retrieval_query_does_not_dilute_narrow -v`
Expected: FAIL (`_retrieval_query` missing).

**Step 3: Implement**

```python
def _retrieval_query(message: str, decision: RouteDecision) -> str:
    if decision.breadth == "broad" and decision.expansion_terms:
        return f"{message} " + " ".join(decision.expansion_terms)
    return message
```

**Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_chat_actions.py::test_retrieval_query_does_not_dilute_narrow -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/chat/actions.py backend/tests/test_chat_actions.py
git commit -m "feat(chat): add anti-dilution retrieval-query builder"
```

---

## Task 4: Sufficiency check + conditional single follow-up retrieval

**Files:**
- Modify: `backend/app/chat/actions.py` (`_sufficiency_check`, `_understanding_retrieval`)
- Test: `backend/tests/test_chat_actions.py`

**Step 1: Write the failing test** (count retrieval calls via monkeypatch)

```python
def test_understanding_retrieval_caps_followups(tmp_path, monkeypatch) -> None:
    _ready(tmp_path)
    import app.chat.actions as actions
    from app.chat.actions import _understanding_retrieval, RouteDecision

    calls = {"n": 0}
    def fake_retrieve(query, *, limit=4):
        calls["n"] += 1
        return []
    monkeypatch.setattr(actions, "retrieve_chunks", fake_retrieve)
    # force "insufficient" so a follow-up would be attempted if uncapped
    monkeypatch.setattr(actions, "_sufficiency_check", lambda message, chunks: (False, "dentist friday"))

    _understanding_retrieval("when is my dentist appointment", RouteDecision(breadth="narrow", buckets=["health"]))
    assert calls["n"] <= 2  # first pass + at most ONE follow-up
```

**Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_chat_actions.py::test_understanding_retrieval_caps_followups -v`
Expected: FAIL (functions missing).

**Step 3: Implement**

```python
def _sufficiency_check(message: str, chunks: list) -> tuple[bool, str]:
    """Return (sufficient, follow_up_query). Fallback: sufficient."""
    if not chunks:
        # nothing retrieved — one focused retry on the raw message can help,
        # but only if we have not already used the message verbatim.
        return True, ""
    summary = "\n".join(f"- {getattr(c, 'title', '')}: {getattr(c, 'content', '')[:200]}" for c in chunks[:6])
    try:
        data = generate_json(
            f'Query:\n{message}\n\nRetrieved:\n{summary}\n\n'
            'Return JSON: {"sufficient": bool, "follow_up_query": "" }. '
            'Only set sufficient=false if the retrieved context clearly misses '
            'something the query explicitly asked for.',
            system="You judge whether retrieved context answers the query. Return only JSON.",
            temperature=0.1,
            max_output_tokens=200,
        )
        sufficient = bool(data.get("sufficient", True))
        follow_up = str(data.get("follow_up_query") or "").strip()
        return (sufficient, "" if sufficient else follow_up)
    except (LLMUnavailable, Exception):
        return True, ""

def _understanding_retrieval(message: str, decision: RouteDecision, *, limit: int = 4) -> list:
    query = _retrieval_query(message, decision)
    chunks = retrieve_chunks(query, limit=limit)
    sufficient, follow_up = _sufficiency_check(message, chunks)
    if not sufficient and follow_up:
        extra = retrieve_chunks(follow_up, limit=limit)
        seen = {getattr(c, "id", id(c)) for c in chunks}
        chunks = chunks + [c for c in extra if getattr(c, "id", id(c)) not in seen]
    return chunks
```

**Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_chat_actions.py::test_understanding_retrieval_caps_followups -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/chat/actions.py backend/tests/test_chat_actions.py
git commit -m "feat(chat): conditional single follow-up retrieval with sufficiency check"
```

---

## Task 5: Selected-bucket context + mode-aware context assembly

**Files:**
- Modify: `backend/app/chat/actions.py` (`_selected_bucket_context`, `_build_answer_context`, `_generate_chat_answer`)
- Test: `backend/tests/test_chat_actions.py`

**Step 1: Write the failing test**

```python
def test_fast_mode_attaches_no_buckets(tmp_path) -> None:
    _ready(tmp_path)
    from app.chat.actions import _build_answer_context
    fast_ctx = _build_answer_context("fast", "what are my career goals")
    understanding_ctx = _build_answer_context("understanding", "what should I focus on in my career")
    assert "Story Buckets:" not in fast_ctx
    assert "Story Buckets:" in understanding_ctx
```

**Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_chat_actions.py::test_fast_mode_attaches_no_buckets -v`
Expected: FAIL (fast still attaches buckets / context assembled the old way).

**Step 3: Implement**

- Add a fetch for selected buckets' **full content**:

```python
def _selected_bucket_context(keys: list[str]) -> str:
    if not keys:
        return ""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT display_name, description, content
                FROM story_buckets
                WHERE status='active' AND stable_key = ANY(%s)
                """,
                (keys,),
            )
            rows = cur.fetchall()
    if not rows:
        return ""
    lines = [f"- {r['display_name']}: {r['description']}\n{(r.get('content') or '')[:1400].strip()}" for r in rows]
    return "Story Buckets:\n" + "\n".join(lines)
```

- Rewrite `_build_answer_context(mode, message)`:

```python
def _build_answer_context(mode: ChatMode, message: str) -> str:
    if mode == "fast":
        sections = [_chunk_context(message, limit=4), _connection_context(message), _goal_context()]
        return "\n\n".join(s for s in sections if s.strip()) or "No Orbit context found yet."

    # understanding
    decision = _route_and_classify(message)
    chunks = _understanding_retrieval(message, decision, limit=8 if decision.breadth == "broad" else 4)
    chunk_block = _chunks_to_context(chunks)  # extract the formatting from _chunk_context into a shared helper
    sections = [
        chunk_block,
        _connection_context(message),
        _selected_bucket_context(decision.buckets),
        _goal_context(),
    ]
    return "\n\n".join(s for s in sections if s.strip()) or "No Orbit context found yet."
```

- Refactor: split `_chunk_context` so the row→text formatting is reusable as `_chunks_to_context(chunks)` (DRY — used by both the old call and the new pipeline). Keep `_chunk_context(message, limit)` calling `retrieve_chunks` then `_chunks_to_context`.
- Remove `_module_tool_context` from the assembled context (its blanket-scan behavior is superseded by routed retrieval). Delete the function if now unreferenced, or leave it unused — prefer deleting to keep the file honest.
- `_generate_chat_answer` already calls `_build_answer_context(request.mode, request.message)`; no signature change needed. Confirm its `max_output_tokens` branch no longer references removed modes (set: `2200` for `understanding`, `1300` for `fast`).

**Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_chat_actions.py -v`
Expected: PASS (new test + all existing chat tests green).

**Step 5: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS (catches any other place that referenced old modes — e.g. `sessions.py` stores `mode` as free text, so it should be fine).

**Step 6: Commit**

```bash
git add backend/app/chat/actions.py backend/tests/test_chat_actions.py
git commit -m "feat(chat): mode-aware context assembly with routed bucket selection"
```

---

## Task 6: Frontend — two-mode picker

**Files:**
- Modify: `frontend/src/lib/api.ts:193` (`ChatMode`)
- Modify: `frontend/src/pages/ChatPage.tsx` (`modes`, default mode, any `mode === 'decision'` styling branches)

**Step 1: Update the type and mode list**

- `api.ts`: `export type ChatMode = 'fast' | 'understanding'`.
- `ChatPage.tsx`: replace the `modes` array (lines ~19-24) with:

```ts
const modes: Array<{ id: ChatMode; label: string; description: string }> = [
  { id: 'understanding', label: 'Understanding', description: 'Reads your user model, then retrieves and synthesizes.' },
  { id: 'fast', label: 'Fast', description: 'Direct answer from retrieved knowledge.' },
]
```

**Step 2: Fix defaults and removed-mode references**

- `useState<ChatMode>('context')` → `useState<ChatMode>('understanding')` (line ~46) and the reset at line ~62.
- Replace `const decideMode = mode === 'decision'` and every `mode === 'decision'` styling branch (lines ~55, ~462, ~495) with neutral styling (drop the violet "decision" accent, or key it off `mode === 'understanding'` if you want an accent).

**Step 3: Verify**

Run: `cd frontend && npm run build`
Expected: build succeeds, no TypeScript errors referencing old modes.

**Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/pages/ChatPage.tsx
git commit -m "feat(chat): two-mode (Understanding/Fast) picker"
```

---

## Final verification

```bash
cd backend && python -m pytest -q
cd ../frontend && npm run build
```

Expected: backend suite green; frontend build clean.

Then use superpowers:requesting-code-review before merging.

## Notes for the implementer

- **Do not vectorize Story Buckets.** The router reads descriptions; that is intentional.
- **The narrow-query anti-dilution guard (Task 3 test) is the heart of this change** — never let bucket content into a narrow retrieval query.
- The follow-up retrieval is capped at exactly one. Do not turn it into a loop.
- Capture-proposal detection (`_detect_capture_proposals` and the preview flow) is untouched and still runs in both modes.
