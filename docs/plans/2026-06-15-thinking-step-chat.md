# Thinking-Step Chat Pipeline (Round 7) — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a dedicated Thinking step to Understanding chat that reasons about how to approach each question and emits a freeform strategy + retrieval hints; route/retrieve/synthesize run per that plan, replacing hand-coded intent clauses (kept as fallback).

**Architecture:** New `_think()` LLM call → `_route_and_classify(message, plan)` seeded by the plan → existing retrieval → synthesis with the plan's `approach` as the strategy directive. SSE gains a `thinking` stage. Full deterministic fallback chain preserves today's behavior with the LLM stubbed.

**Tech Stack:** Python/FastAPI/pytest backend; React/TS frontend (one status-label addition).

**Design doc:** `docs/plans/2026-06-15-thinking-step-chat-design.md`
**Sequencing:** after round 6 (gap analysis) — the deterministic detectors it reuses as fallback are from rounds 5–6.

**Conventions:** backend tests `cd backend && python -m pytest` against a test DB; chat tests in `test_chat_actions.py` / `test_chat_streaming.py`.

---

## Phase A — The Think step

### Task A1: `ThinkingPlan` + `_think` with deterministic fallback

**Files:** Modify `backend/app/chat/actions.py`. Test: `backend/tests/test_chat_actions.py`.

**Step 1: Failing test**

```python
from app.chat.actions import _think, ThinkingPlan


def test_think_fallback_classifies_focus_and_advice() -> None:
    # LLM disabled under pytest -> deterministic fallback.
    p1 = _think("what should I focus on today?")
    assert isinstance(p1, ThinkingPlan)
    assert p1.question_type in {"prioritize", "open"}
    assert p1.approach  # non-empty
    p2 = _think("what can I learn next to fuel my career?")
    assert p2.question_type in {"gap_analysis", "open"}


def test_think_llm_path(monkeypatch) -> None:
    import app.chat.actions as actions
    monkeypatch.setattr(actions, "generate_json", lambda *a, **k: {
        "question_type": "lookup", "approach": "Give the exact value plainly.",
        "retrieval_hint": "tasks and documents",
    })
    p = _think("when is my dentist appointment?")
    assert p.question_type == "lookup"
    assert "exact value" in p.approach
    assert "tasks" in p.retrieval_hint
```

**Step 2: Run → fail.** `cd backend && python -m pytest tests/test_chat_actions.py -k think -v`

**Step 3: Implement**

```python
from dataclasses import dataclass

_QUESTION_TYPES = {"lookup", "gap_analysis", "prioritize", "how_to", "reflection", "open"}

@dataclass
class ThinkingPlan:
    question_type: str = "open"
    approach: str = ""
    retrieval_hint: str = ""

def _user_model_index() -> str:
    # bucket name+description (one line each), goal titles, queryable modules, recent-activity hint
    ...  # reuse _bucket_catalog(), list_goals(); compact string

def _think(message: str) -> ThinkingPlan:
    try:
        data = generate_json(
            f"Question:\n{message}\n\nUser model index:\n{_user_model_index()}\n\n"
            'Return JSON: {"question_type":"lookup|gap_analysis|prioritize|how_to|reflection|open",'
            '"approach":"how to tackle THIS question and what a great answer looks like",'
            '"retrieval_hint":"which life areas/modules/data to pull and why"}',
            system=("You plan how to answer a personal-assistant question. Think about the person's "
                    "context and what a great answer needs. Return only JSON."),
            temperature=0.2, max_output_tokens=350,
        )
        qt = data.get("question_type")
        if qt not in _QUESTION_TYPES:
            qt = "open"
        approach = str(data.get("approach") or "").strip()
        if not approach:
            raise ValueError("empty approach")
        return ThinkingPlan(qt, approach, str(data.get("retrieval_hint") or "").strip())
    except (LLMUnavailable, Exception):
        return _think_fallback(message)

def _think_fallback(message: str) -> ThinkingPlan:
    if _is_focus_query(message):
        return ThinkingPlan("prioritize", _FOCUS_APPROACH, "tasks, plans, routines, goals")
    if _is_advice_query(message):
        return ThinkingPlan("gap_analysis", _GAP_APPROACH, "tasks, plans, routines, goals, career")
    return ThinkingPlan("open", _DEFAULT_APPROACH, "")
```

Define `_FOCUS_APPROACH`, `_GAP_APPROACH`, `_DEFAULT_APPROACH` as the curated
guidance strings (move the existing focus-ranking / gap text from
`_chat_system_prompt` into these constants so they're reused).

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(chat): thinking step with deterministic fallback"`

---

## Phase B — Route seeded by the plan

### Task B1: `_route_and_classify(message, plan)`

**Files:** Modify `backend/app/chat/actions.py`. Test: `backend/tests/test_chat_actions.py`.

**Step 1: Failing test**

```python
def test_router_uses_retrieval_hint(monkeypatch) -> None:
    import app.chat.actions as actions
    from app.chat.actions import _route_and_classify, ThinkingPlan
    captured = {}
    def fake(prompt, *, system, **k):
        captured["prompt"] = prompt
        return {"breadth": "narrow", "buckets": ["career"], "modules": ["tasks"], "expansion_terms": []}
    monkeypatch.setattr(actions, "generate_json", fake)
    _route_and_classify("help me", ThinkingPlan("prioritize", "rank things", "focus on tasks and routines"))
    assert "focus on tasks and routines" in captured["prompt"] or "prioritize" in captured["prompt"]


def test_router_plan_optional_back_compat() -> None:
    from app.chat.actions import _route_and_classify
    d = _route_and_classify("what tasks are overdue?")  # no plan -> still works
    assert "tasks" in d.modules
```

**Step 2: Run → fail.**

**Step 3: Implement** — give `_route_and_classify(message, plan: ThinkingPlan | None = None)` a default; when `plan` is provided, include `plan.retrieval_hint` and `plan.question_type` in `_route_prompt`. In the module-union block, also fire when `plan` and `plan.question_type in {"prioritize","gap_analysis"}` (in addition to the existing `_is_focus_query`/`_is_advice_query`). Keep all fallbacks.

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(chat): router consumes the thinking plan"`

---

## Phase C — Synthesis directed by the plan

### Task C1: Inject `approach` as the strategy directive

**Files:** Modify `backend/app/chat/actions.py` (`_build_answer_context` or the answer-prompt builder, `_generate_chat_answer`, and simplify `_chat_system_prompt`). Test: `backend/tests/test_chat_actions.py`.

**Step 1: Failing test**

```python
def test_answer_prompt_includes_plan_approach() -> None:
    from app.chat.actions import _answer_prompt, ThinkingPlan  # or whichever builder exists
    prompt = _answer_prompt(message="x", context="ctx", suggestions=[],
                            plan=ThinkingPlan("gap_analysis", "Find gaps beyond their inputs.", ""))
    assert "Find gaps beyond their inputs." in prompt
```

(If there is no standalone `_answer_prompt`, add one extracted from `_generate_chat_answer`/the streaming builder so both paths share it — DRY.)

**Step 2: Run → fail.**

**Step 3: Implement**
- Thread `plan` into the answer-prompt builder; prepend `f"Approach for this answer: {plan.approach}\n\n"` when present.
- Simplify `_chat_system_prompt("understanding")`: keep base rules (grounded facts; may give general advice; formatting; plain values) and a one-line "follow the provided Approach"; remove the inline focus-ranking + gap clauses (now delivered via `plan.approach`, with the curated text living in the Phase-A fallback constants).
- Wire `_think` → `_route_and_classify(message, plan)` → retrieval → `_answer_prompt(..., plan=plan)` in both `respond_to_chat` (non-stream) and `respond_to_chat_stream`.

**Step 4: Run → pass.** Run full `cd backend && python -m pytest`. **Step 5: Commit** `git commit -m "feat(chat): synthesis directed by the thinking plan"`

---

## Phase D — Streaming `thinking` stage

### Task D1: Emit + label the thinking stage

**Files:** Modify `backend/app/chat/actions.py` (`respond_to_chat_stream`), `frontend/src/pages/ChatPage.tsx` (STAGE_LABELS). Test: `backend/tests/test_chat_streaming.py`.

**Step 1: Failing test**

```python
def test_stream_emits_thinking_first() -> None:
    from app.chat.actions import respond_to_chat_stream, ChatRequest
    events = list(respond_to_chat_stream(ChatRequest(session_id="s", mode="understanding", message="hi")))
    stages = [e.get("stage") for e in events]
    assert stages[0] == "thinking"
    assert "routing" in stages and stages[-1] == "done"
```

**Step 2: Run → fail.**

**Step 3: Implement** — in the understanding branch of `respond_to_chat_stream`, `yield {"stage": "thinking"}` then `plan = _think(message)` before routing; pass `plan` through route + synthesis. In `ChatPage.tsx`, add `thinking: "Thinking it through…"` to `STAGE_LABELS`.

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(chat): thinking stage in stream + UI label"`

---

## Phase E — Final verification

### Task E1: Suite + smoke
1. `cd backend && python -m pytest` → green (incl. existing focus/advice/sources tests).
2. Rebuild `docker compose up --build`. Confirm:
   - A "Thinking it through…" status flashes first in Understanding mode.
   - Focus ("what should I focus on?"), advice ("what can I learn next?"), and lookup ("when is my dentist appointment?") questions each get an appropriately *shaped* answer without any new hand-coded clause — driven by the plan's approach.
   - Personal-fact questions stay grounded; Fast mode behaves as before.
3. **REQUIRED SUB-SKILL:** superpowers:requesting-code-review, then superpowers:finishing-a-development-branch.

---

## Notes & deferred
- Agentic re-think loop; web grounding (round-6 deferred); thinking step for Fast/companion.
