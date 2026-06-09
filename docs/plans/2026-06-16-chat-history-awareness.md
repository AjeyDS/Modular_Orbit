# History-Aware Chat (Round 8) — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make chat follow-ups coherent — load recent conversation, have the Think step rewrite the message into a self-contained question that drives routing/retrieval, and give synthesis recent turns for continuity.

**Architecture:** New `_recent_history(session_id)`; `ThinkingPlan.resolved_question`; `_think(message, history)`; route/retrieve run on the resolved question; synthesis prompt gains a recent-conversation block. Fast mode gets history in synthesis only. Full deterministic fallback preserves single-turn behavior.

**Tech Stack:** Python/FastAPI/pytest backend. No frontend change (history already rendered).

**Design doc:** `docs/plans/2026-06-16-chat-history-awareness-design.md`
**Branch:** `feat/chat-history-awareness` (already created off `main`).

**Conventions:** backend tests `cd backend && python -m pytest` against a test DB; chat tests in `test_chat_actions.py` / `test_chat_streaming.py`; session helpers in `app/chat/sessions.py`.

---

## Phase A — Load recent history

### Task A1: `_recent_history`

**Files:** Modify `backend/app/chat/actions.py`. Test: `backend/tests/test_chat_actions.py`.

**Step 1: Failing test**

```python
from app.chat.actions import _recent_history
from app.chat.sessions import insert_chat_message
from app.db import transaction


def test_recent_history_returns_last_turns_in_order() -> None:
    sid = "hist-1"
    with transaction() as conn:
        from app.chat.sessions import upsert_session_for_message
        upsert_session_for_message(conn, sid, initial_title="t")
        insert_chat_message(conn, session_id=sid, role="user", content="first")
        insert_chat_message(conn, session_id=sid, role="assistant", content="answer one")
        insert_chat_message(conn, session_id=sid, role="user", content="second")
    hist = _recent_history(sid, limit=6)
    assert [r for r, _ in hist] == ["user", "assistant", "user"]
    assert hist[0][1] == "first" and hist[-1][1] == "second"


def test_recent_history_empty_for_new_session() -> None:
    assert _recent_history("does-not-exist") == []
```

**Step 2: Run → fail.** `cd backend && python -m pytest tests/test_chat_actions.py -k recent_history -v`

**Step 3: Implement**

```python
def _recent_history(session_id: str, *, limit: int = 6, char_cap: int = 500) -> list[tuple[str, str]]:
    try:
        from app.chat.sessions import list_chat_messages
        msgs = list_chat_messages(session_id)
    except Exception:
        return []
    out: list[tuple[str, str]] = []
    for m in msgs[-limit:]:
        if m.role in ("user", "assistant"):
            out.append((m.role, (m.content or "")[:char_cap]))
    return out
```

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(chat): load recent conversation history"`

---

## Phase B — Think resolves the follow-up

### Task B1: `resolved_question` on the plan + history-aware `_think`

**Files:** Modify `backend/app/chat/actions.py` (`ThinkingPlan`, `_think`, `_think_fallback`). Test: `backend/tests/test_chat_actions.py`.

**Step 1: Failing test**

```python
from app.chat.actions import _think, ThinkingPlan


def test_think_fallback_resolved_question_is_message() -> None:
    p = _think("prioritize this")   # LLM disabled -> fallback
    assert p.resolved_question == "prioritize this"


def test_think_resolves_with_history(monkeypatch) -> None:
    import app.chat.actions as actions
    captured = {}
    def fake(prompt, *, system, **k):
        captured["prompt"] = prompt
        return {"question_type": "prioritize", "approach": "rank them",
                "retrieval_hint": "", "resolved_question": "prioritize the learning areas: MLOps, Kubernetes"}
    monkeypatch.setattr(actions, "generate_json", fake)
    hist = [("user", "what can I learn?"), ("assistant", "MLOps, Kubernetes, IaC")]
    p = _think("prioritize this", hist)
    assert "MLOps" in p.resolved_question
    assert "what can I learn" in captured["prompt"] or "MLOps" in captured["prompt"]  # history fed in
```

**Step 2: Run → fail.**

**Step 3: Implement**
- `ThinkingPlan`: add `resolved_question: str = ""`.
- `_think(message, history=None)`: when `history`, render a "Recent conversation:\n" block into the prompt; instruct the model to return `resolved_question` (self-contained restatement resolving references). Parse it; if empty → `message`. On exception → `_think_fallback(message)`.
- `_think_fallback(message)`: set `resolved_question=message` on the returned plan.

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(chat): think step resolves referential follow-ups"`

---

## Phase C — Route/retrieve on the resolved question + synthesis continuity

### Task C1: Thread resolved question + history through both pipelines

**Files:** Modify `backend/app/chat/actions.py` (`respond_to_chat`, `respond_to_chat_stream`, `_route_and_classify` callers, retrieval call, answer-prompt builder). Test: `backend/tests/test_chat_actions.py`, `test_chat_streaming.py`.

**Step 1: Failing test**

```python
def test_resolved_question_drives_retrieval(monkeypatch) -> None:
    import app.chat.actions as actions
    seen = {}
    monkeypatch.setattr(actions, "_think", lambda m, h=None: actions.ThinkingPlan(
        "prioritize", "rank", "", resolved_question="prioritize MLOps and Kubernetes"))
    monkeypatch.setattr(actions, "retrieve_chunks", lambda q, **k: seen.setdefault("q", q) or [])
    actions._build_answer_context("understanding", "prioritize this")
    assert seen["q"] == "prioritize MLOps and Kubernetes" or "MLOps" in seen.get("q", "")


def test_answer_prompt_includes_recent_history() -> None:
    from app.chat.actions import _answer_prompt
    prompt = _answer_prompt(message="x", context="ctx", suggestions=[], plan=None,
                            history=[("user", "what can I learn?"), ("assistant", "MLOps")])
    assert "Recent conversation" in prompt and "MLOps" in prompt
```

(Adapt to the actual builder signatures; the assertions are the contract.)

**Step 2: Run → fail.**

**Step 3: Implement**
- In `_build_answer_context(mode, message, *, plan=None, history=None)` (understanding): `query = (plan.resolved_question if plan and plan.resolved_question else message)`; pass `query` to `_route_and_classify` and retrieval. Keep capture detection on the raw message upstream.
- Answer-prompt builder gains `history`; prepend a "Recent conversation:\n…" block when present.
- `respond_to_chat` / `respond_to_chat_stream`: capture `history` before inserting the user message; pass `plan` (already there) and `history` into context + answer prompt. Fast mode: pass `history` into its synthesis prompt only.

**Step 4: Run → pass.** Run full `cd backend && python -m pytest`. **Step 5: Commit** `git commit -m "feat(chat): retrieval + synthesis use resolved question and history"`

---

## Phase D — Verification

### Task D1: Suite + smoke
1. `cd backend && python -m pytest` → green.
2. Rebuild `docker compose up --build`. In one session:
   - Ask "what can I learn next…" → learning answer.
   - Follow with "give me that in priority order as an actionable list" → it now
     prioritizes the **learning items** (MLOps/Kubernetes/…), not your goals.
   - Try "expand on the second one" → stays on the right subject.
   - A fresh session's first message behaves exactly as before.
3. **REQUIRED SUB-SKILL:** superpowers:requesting-code-review, then superpowers:finishing-a-development-branch.

---

## Notes & deferred
- Long-thread summarization; cross-session memory; companion follow-up resolution.
