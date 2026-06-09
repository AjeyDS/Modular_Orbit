# Advisor Gap Analysis (Round 6) — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let the advisor suggest what the user is missing / should learn next — base-model gap analysis with no internet — by separating private facts from general advice in the prompt and force-including the user's structured baseline for advice queries.

**Architecture:** Prompt + router tweaks in `app/chat/actions.py` only; reuses round-5's module-union mechanism. No new plumbing, no web access (gated web is a deferred design).

**Tech Stack:** Python/FastAPI/pytest backend. No frontend change.

**Design doc:** `docs/plans/2026-06-14-advisor-gap-analysis-design.md`
**Sequencing:** after round 5 (focus/cache) — both rely on `_route_and_classify` module union.

**Conventions:** backend tests `cd backend && python -m pytest` against a test DB; chat tests in `test_chat_actions.py`.

---

## Phase A — Advice intent + structured baseline

### Task A1: `_is_advice_query` force-includes actionable modules

**Files:** Modify `backend/app/chat/actions.py` (add `_is_advice_query`; extend the focus union in `_route_and_classify`). Test: `backend/tests/test_chat_actions.py`.

**Step 1: Failing test**

```python
from app.chat.actions import _is_advice_query, _route_and_classify


def test_is_advice_query() -> None:
    assert _is_advice_query("what can I learn next to fuel my career?") is True
    assert _is_advice_query("how can I improve from here?") is True
    assert _is_advice_query("when is my dentist appointment?") is False


def test_advice_query_forces_actionable_modules() -> None:
    d = _route_and_classify("what can I learn next to fuel my career?")
    assert {"tasks", "plans", "routines", "goals"} <= set(d.modules)
    assert d.breadth == "broad"
```

**Step 2: Run → fail.** `cd backend && python -m pytest tests/test_chat_actions.py -k advice -v`

**Step 3: Implement**

```python
_ADVICE_MARKERS = (
    "what can i learn", "what should i learn", "what to learn", "what am i missing",
    "how do i improve", "how can i improve", "level up", "fuel my career",
    "make the most", "what's next", "whats next", "what should i do next",
)

def _is_advice_query(message: str) -> bool:
    m = message.lower()
    return any(marker in m for marker in _ADVICE_MARKERS)
```

In `_route_and_classify`, change the existing focus union condition to also fire
for advice queries:

```python
if _is_focus_query(message) or _is_advice_query(message):
    modules = sorted(set(modules) | {"tasks", "plans", "routines", "goals"})
    breadth = "broad"
```

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(chat): advice queries pull structured baseline"`

---

## Phase B — Prompt: facts vs advice + gap instruction

### Task B1: Separate private facts from general advice

**Files:** Modify `backend/app/chat/actions.py` (`_chat_system_prompt` base). Test: `backend/tests/test_chat_actions.py`.

**Step 1: Failing test**

```python
def test_prompt_allows_advice_but_guards_personal_facts() -> None:
    from app.chat.actions import _chat_system_prompt
    p = _chat_system_prompt("understanding").lower()
    assert "never invent" in p or "do not invent" in p          # facts guarded
    assert "general" in p and ("suggest" in p or "gap" in p)    # advice allowed
```

**Step 2: Run → fail.**

**Step 3: Implement** — in `_chat_system_prompt` base, replace the single
"only as context; do not invent private facts." sentence with:

```
"The provided Story Buckets, Goals, module data, Connections, and Knowledge "
"Chunks are the source of truth for facts ABOUT THE PERSON — never invent or "
"guess personal facts. You MAY and SHOULD contribute general world knowledge, "
"opinions, and gap analysis (skills, learning paths, what's commonly needed for "
"the person's goals), framed clearly as suggestions, never as facts about the "
"person."
```

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(chat): allow general advice, keep personal facts grounded"`

---

### Task B2: Gap instruction for advice queries (understanding mode)

**Files:** Modify `backend/app/chat/actions.py` (`_chat_system_prompt` understanding branch). Test: `backend/tests/test_chat_actions.py`.

**Step 1: Failing test**

```python
def test_understanding_prompt_has_gap_instruction() -> None:
    from app.chat.actions import _chat_system_prompt
    p = _chat_system_prompt("understanding").lower()
    assert "have not" in p or "haven't" in p or "not already listed" in p
    assert "fabricate" in p or "do not invent specific" in p  # no fake courses/links
```

**Step 2: Run → fail.**

**Step 3: Implement** — append to the Understanding system prompt:

```
"When the person asks what to learn, improve, or do next, don't just recombine "
"what they already have. Compare their current skills, projects, and routines "
"against what their goals typically require, and surface 1–3 concrete things "
"they have NOT already listed (a real gap), each with a one-line why. Suggest "
"skill areas, topics, and types of resources — do not fabricate specific course "
"names, products, or links."
```

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(chat): gap-analysis guidance for advice answers"`

---

## Phase C — Final verification

### Task C1: Suite + smoke
1. `cd backend && python -m pytest` → green.
2. Rebuild `docker compose up --build`. Ask "What can I learn next to fuel my
   career or make the most of what I already have?" → answer now includes 1–3
   **beyond-inputs** suggestions (gaps relative to the user's stack/goals), each
   with a reason, framed as recommendations, with **no** fabricated course
   links — not just a recombination of existing plans/routines.
3. Confirm personal-fact questions ("what do you know about me?") still stay
   strictly grounded (no invented personal facts).
4. **REQUIRED SUB-SKILL:** superpowers:requesting-code-review, then
   superpowers:finishing-a-development-branch.

---

## Notes & deferred
- Gated web grounding (Gemini Google Search) for fresh/specific queries — see the
  design doc's deferred section; build as a separate later round.
- Standalone Decision Mode.
