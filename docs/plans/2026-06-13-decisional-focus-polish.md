# Decisional Focus, Field Cleanup & Cache Headers (Round 5) — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make focus/priority chat queries rank-and-recommend across tasks/plans/routines/goals; stop the model echoing raw field labels; and add nginx cache headers so frontend rebuilds reach the browser (fixing the "missing" Sources footer).

**Architecture:** Pure prompt + router tweaks reusing round-3 structured retrieval (no new plumbing) for #1/#2, plus an nginx config change for #3.

**Tech Stack:** Python/FastAPI/pytest backend; nginx (frontend container). No frontend code change.

**Design doc:** `docs/plans/2026-06-13-decisional-focus-polish-design.md`
**Sequencing:** after rounds 3 + 4 (both already merged).

**Conventions:** backend tests `cd backend && python -m pytest` against a test DB; chat tests in `test_chat_actions.py`.

---

## Phase A — Decisional focus (#1)

### Task A1: `_is_focus_query` + force-include actionable modules

**Files:** Modify `backend/app/chat/actions.py` (`_route_and_classify`, add `_is_focus_query`). Test: `backend/tests/test_chat_actions.py`.

**Step 1: Failing test**

```python
from app.chat.actions import _is_focus_query, _route_and_classify


def test_is_focus_query() -> None:
    assert _is_focus_query("what should I focus on today?") is True
    assert _is_focus_query("how should I prioritize my week?") is True
    assert _is_focus_query("when is my dentist appointment?") is False


def test_focus_query_forces_actionable_modules() -> None:
    # LLM disabled under pytest -> lexical/fallback path.
    d = _route_and_classify("what should I focus on today?")
    assert {"tasks", "plans", "routines", "goals"} <= set(d.modules)
    assert d.breadth == "broad"
```

**Step 2: Run → fail.** `cd backend && python -m pytest tests/test_chat_actions.py -k focus -v`

**Step 3: Implement**

```python
_FOCUS_MARKERS = (
    "focus on", "what should i do", "what should i focus", "prioritize",
    "priorities", "plan my day", "what now", "where should i start",
    "how should i spend", "what's important", "whats important",
)

def _is_focus_query(message: str) -> bool:
    m = message.lower()
    return any(marker in m for marker in _FOCUS_MARKERS)
```

In `_route_and_classify`, just before returning `RouteDecision(...)` on BOTH the
LLM-success and the fallback paths (or once at a shared exit), add:

```python
if _is_focus_query(message):
    modules = sorted(set(modules) | {"tasks", "plans", "routines", "goals"})
    breadth = "broad"
```

(Ensure `modules` and `breadth` locals are set on both paths before this.)

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(chat): focus queries pull all actionable modules"`

---

### Task A2: Focus-ranking guidance in the answer prompt

**Files:** Modify `backend/app/chat/actions.py` (`_chat_system_prompt`). Test: `backend/tests/test_chat_actions.py`.

**Step 1: Failing test**

```python
def test_understanding_prompt_has_focus_ranking_guidance() -> None:
    from app.chat.actions import _chat_system_prompt
    p = _chat_system_prompt("understanding").lower()
    assert "prioritize" in p or "rank" in p
    assert "due" in p  # urgency by due date
```

**Step 2: Run → fail.**

**Step 3: Implement** — append to the Understanding system prompt:

```
"If the user asks what to focus on or how to prioritize, use the Structured data "
"to RANK concrete items (tasks, plans, routines) by urgency (soonest or overdue "
"due dates first), then priority, then alignment to active goals. Recommend an "
"ordered short list (top 3), each with a one-line reason, leading with the single "
"most important. Decide; don't just describe."
```

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(chat): focus-ranking answer guidance"`

---

## Phase B — Field-leak cleanup (#2)

### Task B1: Plain-language guidance

**Files:** Modify `backend/app/chat/actions.py` (base part of `_chat_system_prompt`). Test: `backend/tests/test_chat_actions.py`.

**Step 1: Failing test**

```python
def test_prompt_discourages_raw_field_labels() -> None:
    from app.chat.actions import _chat_system_prompt
    p = _chat_system_prompt("understanding").lower()
    assert "plain" in p or "raw field" in p or "verbatim" in p
```

**Step 2: Run → fail. Step 3:** append to the base prompt: "Render values in plain, natural language. Do not echo raw field names or status codes verbatim (e.g. 'Admit Until Date: D/S'); translate them ('admitted for duration of status') or omit if unclear." **Step 4: pass. Step 5:** `git commit -m "feat(chat): plain-language value rendering guidance"`

---

## Phase C — nginx cache headers (#3)

### Task C1: Cache-Control for index.html + assets

**Files:** Modify `frontend/nginx.conf`.

**Step 1: Implement** — inside the `server` block, replace the single `location /`
with:

```nginx
location = /index.html {
  add_header Cache-Control "no-cache";
}

location /assets/ {
  add_header Cache-Control "public, max-age=31536000, immutable";
}

location / {
  try_files $uri $uri/ /index.html;
}
```

Keep the existing `/api/` and `/health` blocks unchanged.

**Step 2: Verify**

```bash
cd /Users/ajeyds/Projects/modular-orbit && docker compose up --build -d frontend
curl -sI http://localhost:5173/index.html | grep -i cache-control      # expect: no-cache
curl -s http://localhost:5173/ | grep -o '/assets/[^"]*\.js' | head -1  # grab a hashed asset
# curl -sI http://localhost:5173/assets/<that-file> | grep -i cache-control  # expect: immutable
```

Expected: `index.html` → `Cache-Control: no-cache`; `/assets/*.js` → `immutable`.

**Step 3: Commit** `git commit -m "fix(frontend): cache-control headers so rebuilds reach the browser"`

---

## Phase D — Final verification

### Task D1: Suite + smoke
1. `cd backend && python -m pytest` → green.
2. `docker compose up --build`. Then hard-refresh once and confirm:
   - "What should I focus on today?" returns a **ranked** short list (top ~3) with reasons and a clear top pick — not a single-task description.
   - No raw field labels ("Admit Until Date: D/S") in "what do you know about me?".
   - The **Sources** strip now appears under answers (and stays correct on the next rebuild without a manual hard refresh).
3. **REQUIRED SUB-SKILL:** superpowers:requesting-code-review, then superpowers:finishing-a-development-branch.

---

## Notes & deferred
- Dedicated Decision Mode (option/tradeoff generation); service-worker caching.
