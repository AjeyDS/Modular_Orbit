# User-Model & Chat Refinements (Round 3) — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove the redundant `goals` Story Bucket, give the companion a recent-activity feed, and give Understanding Chat orchestrated per-module structured retrieval (tasks/plans/goals/routines).

**Architecture:** (A) Drop `goals` from the bucket key set + seed list and archive the empty row; everything reads active buckets so the rest ripples. (B) Add a recency section to `build_companion_context` from recent Life Items + goals. (C) Extend the existing chat router with a `modules` field (no extra LLM call) and add per-module structured retrievers that reuse existing service functions, injected into the Understanding answer context and SSE stream. Fast mode unchanged.

**Tech Stack:** Python 3 / FastAPI / psycopg / Gemini backend; pytest (LLM auto-disabled under pytest → fallbacks default; monkeypatch `generate_json` for LLM paths). React/TS frontend (verify status labels via app).

**Design doc:** `docs/plans/2026-06-11-usermodel-chat-refinements-design.md`

**Conventions:** see `docs/plans/2026-06-09-curious-companion.md` header. Backend tests: `cd backend && python -m pytest` against a test DB (DATABASE_URL containing "test"). Tests: bucket keys → `test_bucket_keys.py`; buckets/seed → `test_user_model.py`; companion → `test_companion.py`; chat → `test_chat_actions.py`.

---

## Phase A — Remove the `goals` Story Bucket

### Task A1: Drop `goals` from the key set

**Files:** Modify `backend/app/lifecycle/bucket_keys.py`. Test: `backend/tests/test_bucket_keys.py`.

**Step 1: Failing test**

```python
from app.lifecycle.bucket_keys import KNOWN_BUCKET_KEYS, normalize_bucket_key


def test_goals_is_not_a_bucket_key() -> None:
    assert "goals" not in KNOWN_BUCKET_KEYS
    assert len(KNOWN_BUCKET_KEYS) == 7
    assert normalize_bucket_key("goals") is None
    assert normalize_bucket_key("Career") == "career"
```

**Step 2: Run → fail.** `cd backend && python -m pytest tests/test_bucket_keys.py -k goals_is_not -v`

**Step 3: Implement** — remove `"goals",` from `KNOWN_BUCKET_KEYS` in `bucket_keys.py`. (`ALLOWED_KEYS_LINE` updates automatically.)

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "refactor(user-model): drop goals from bucket key set"`

---

### Task A2: Stop seeding + archive the legacy goals bucket

**Files:** Modify `backend/app/user_model/story_buckets.py` (`DEFAULT_STORY_BUCKETS`, `ensure_story_buckets`). Test: `backend/tests/test_user_model.py`.

**Step 1: Failing test**

```python
from app.db import connect
from app.user_model.story_buckets import ensure_story_buckets, DEFAULT_STORY_BUCKETS


def test_goals_bucket_not_seeded_and_archived(tmp_path) -> None:
    assert all(seed.stable_key != "goals" for seed in DEFAULT_STORY_BUCKETS)
    # Simulate a legacy goals bucket already present, then ensure.
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO story_buckets (stable_key, file_path, display_name, description, status) "
                "VALUES ('goals', %s, 'Goals', 'legacy', 'active') ON CONFLICT (stable_key) DO NOTHING",
                (str(tmp_path / "goals.md"),),
            )
        conn.commit()
    ensure_story_buckets(tmp_path)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM story_buckets WHERE stable_key = 'goals'")
            row = cur.fetchone()
            cur.execute("SELECT COUNT(*) c FROM story_buckets WHERE status = 'active'")
            active = cur.fetchone()["c"]
    assert row is None or row["status"] == "archived"
    assert active == 7
```

(Adjust the INSERT columns to match the real `story_buckets` schema; the point is a pre-existing active goals row gets archived and active count is 7.)

**Step 2: Run → fail.**

**Step 3: Implement**
- Remove the `StoryBucketSeed(stable_key="goals", …)` entry from `DEFAULT_STORY_BUCKETS`.
- In `ensure_story_buckets`, after the seed loop, archive any active legacy goals bucket:
  ```python
  cur.execute(
      "UPDATE story_buckets SET status = 'archived', updated_at = now() "
      "WHERE stable_key = 'goals' AND status = 'active'"
  )
  ```

**Step 4: Run → pass.** Then run the broad suites to confirm ripples are clean:
`cd backend && python -m pytest tests/test_user_model.py tests/test_companion.py tests/test_chat_actions.py tests/test_documents_module.py -q`.

**Step 5: Commit** `git commit -m "refactor(user-model): stop seeding goals bucket, archive legacy row"`

---

## Phase B — Companion recent-activity context

### Task B1: Recent Life Items + goals in `build_companion_context`

**Files:** Modify `backend/app/modules/companion.py`. Test: `backend/tests/test_companion.py`.

**Step 1: Failing test**

```python
from app.modules.companion import build_companion_context
from app.modules.logs import LogCreate, create_log


def test_context_includes_recent_activity(tmp_path) -> None:
    _ready_companion(tmp_path)
    create_log(LogCreate(text="Submitted my OPT application today"), review=False)
    ctx = build_companion_context()
    assert "Recent activity" in ctx
    assert "OPT" in ctx
```

**Step 2: Run → fail.**

**Step 3: Implement** — in `build_companion_context`, add a query:

```python
cur.execute(
    """
    SELECT m.id AS module_id, li.item_type, li.title, li.created_at
    FROM life_items li
    JOIN module_instances mi ON mi.id = li.module_instance_id
    JOIN modules m ON m.id = mi.module_id
    WHERE m.id IN ('logs','tasks','plans','documents','routine')
        AND li.item_type NOT IN ('curious_session','curious_question')
        AND li.lifecycle_status <> 'deleted'
    ORDER BY li.created_at DESC
    LIMIT 12
    """
)
recent_rows = cur.fetchall()
```

Then append a section:
```python
if recent_rows:
    sections.append(
        "Recent activity:\n" + "\n".join(f"- [{r['module_id']}] {r['title']}" for r in recent_rows)
    )
```
Place it before the final `context[:2000]` truncation (so buckets/goals stay; recency truncates last). Keep recent goals via the existing `list_goals()` section.

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(companion): recent cross-module activity in context"`

---

## Phase C — Structured query tool in Understanding Chat

### Task C1: Router returns `modules`

**Files:** Modify `backend/app/chat/actions.py` (`RouteDecision`, `_route_and_classify`, `_route_prompt`, add `_modules_fallback`). Test: `backend/tests/test_chat_actions.py`.

**Step 1: Failing test**

```python
from app.chat.actions import _route_and_classify, QUERYABLE_MODULES


def test_router_selects_modules_via_lexical_fallback() -> None:
    # LLM disabled under pytest -> lexical fallback.
    d1 = _route_and_classify("what tasks are overdue?")
    assert "tasks" in d1.modules
    d2 = _route_and_classify("did I do my routine today?")
    assert "routines" in d2.modules
    d3 = _route_and_classify("tell me a story about the ocean")
    assert d3.modules == []
```

**Step 2: Run → fail** (`RouteDecision` has no `modules`).

**Step 3: Implement**
- Add `QUERYABLE_MODULES = {"tasks", "plans", "goals", "routines"}`.
- `RouteDecision`: add `modules: list[str] = field(default_factory=list)`.
- `_route_and_classify`: parse `data.get("modules")`, clamp to `QUERYABLE_MODULES`; on the LLM-success path and the except/fallback path set `modules = _modules_fallback(message)`.
- `_modules_fallback(message)`: lowercase keyword detection →
  `due|overdue|task|todo`→tasks; `plan|progress|step|milestone`→plans;
  `goal|aspir|aiming`→goals; `routine|habit|streak|daily`→routines; else [].
- `_route_prompt`: add a line asking for `"modules"` from the queryable set, `[]` if none, and include `"modules":["..."]` in the JSON shape.

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(chat): router selects queryable modules"`

---

### Task C2: Per-module structured retrievers

**Files:** Modify `backend/app/chat/actions.py`. Test: `backend/tests/test_chat_actions.py`.

**Step 1: Failing test**

```python
from app.chat.actions import _structured_context
from app.modules.tasks import TaskCreate, create_task
from app.user_model.goals import create_goal


def test_structured_context_renders_selected_modules(tmp_path) -> None:
    create_task(TaskCreate(title="Renew passport"), review=False)
    create_goal(title="Start an LLC", status="active", horizon="short_term")
    block = _structured_context(["tasks", "goals"])
    assert "Renew passport" in block
    assert "Start an LLC" in block


def test_structured_context_empty_when_no_modules() -> None:
    assert _structured_context([]) == ""
```

**Step 2: Run → fail.**

**Step 3: Implement** — add the four retrievers (each `try/except (Exception)` → "") and a dispatcher:

```python
def _structured_tasks_context() -> str:
    from app.modules.tasks import list_tasks
    tasks = list_tasks(status="active", limit=10)
    if not tasks: return ""
    def key(t): return (t.due_date is None, t.due_date)
    lines = [f"- {t.title} — due {t.due_date or 'none'}, priority {t.priority or '-'}, {t.module_status or 'active'}"
             for t in sorted(tasks, key=key)]
    return "Tasks:\n" + "\n".join(lines)

def _structured_plans_context() -> str:
    from app.modules.plans import list_plans
    plans = list_plans(status="active")
    if not plans: return ""
    return "Plans:\n" + "\n".join(
        f"- {p.title} — {p.completed_steps}/{p.total_steps} steps ({p.progress_percent}%)" for p in plans)

def _structured_goals_context() -> str:
    from app.user_model.goals import list_goals
    goals = list_goals()
    if not goals: return ""
    return "Goals:\n" + "\n".join(
        f"- {g.status}/{g.horizon}: {g.title}" + (f" — target {g.target_note or g.target_date}" if (g.target_note or g.target_date) else "")
        for g in goals[:10])

def _structured_routines_context() -> str:
    from app.modules.routine import list_routine_state
    state = list_routine_state()
    if not state.items: return ""
    return "Routines:\n" + "\n".join(
        f"- {it.title} — streak {it.streak_count}, today: {'done' if it.completed_today else 'not done'}"
        for it in state.items[:10])

_STRUCTURED = {
    "tasks": _structured_tasks_context, "plans": _structured_plans_context,
    "goals": _structured_goals_context, "routines": _structured_routines_context,
}

def _structured_context(modules: list[str]) -> str:
    blocks = []
    for m in modules:
        fn = _STRUCTURED.get(m)
        if fn is None: continue
        try:
            b = fn()
        except Exception:
            b = ""
        if b: blocks.append(b)
    if not blocks: return ""
    return "Structured data:\n" + "\n\n".join(blocks)
```

(Confirm the `RoutineItem` field for today's completion — adapt `completed_today` to the actual attribute name on `RoutineItem`.)

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(chat): per-module structured retrievers"`

---

### Task C3: Inject structured data into Understanding context + stream

**Files:** Modify `backend/app/chat/actions.py` (`_build_answer_context`, `respond_to_chat_stream`). Test: `backend/tests/test_chat_actions.py` + `test_chat_streaming.py`.

**Step 1: Failing test**

```python
from app.chat.actions import _build_answer_context
from app.modules.tasks import TaskCreate, create_task


def test_understanding_context_includes_structured_block_for_task_query(tmp_path) -> None:
    create_task(TaskCreate(title="File taxes"), review=False)
    ctx = _build_answer_context("understanding", "what tasks are overdue?")
    assert "Structured data" in ctx and "File taxes" in ctx


def test_fast_mode_has_no_structured_block(tmp_path) -> None:
    create_task(TaskCreate(title="File taxes"), review=False)
    ctx = _build_answer_context("fast", "what tasks are overdue?")
    assert "Structured data" not in ctx
```

**Step 2: Run → fail.**

**Step 3: Implement**
- In `_build_answer_context`, understanding branch: after `decision = _route_and_classify(message)`, compute `structured = _structured_context(decision.modules)` and add it to the `sections` list (before joining).
- In `respond_to_chat_stream` (understanding path): after routing, if `decision.modules`, `yield {"stage": "checking_state"}`; include `_structured_context(decision.modules)` in the context passed to the answer prompt. Keep the existing stages/order otherwise.
- Fast path unchanged (no router, no structured).

**Step 4: Run → pass.** Run full `cd backend && python -m pytest`. **Step 5: Commit** `git commit -m "feat(chat): inject structured data into Understanding answers + stream"`

---

## Phase D — Frontend (verify via app)

### Task D1: `checking_state` status label
Modify `frontend/src/pages/ChatPage.tsx`: map the new `checking_state` stage to a friendly label ("Checking your tasks, plans & goals"). Verify by asking "what's overdue?" in Understanding mode and watching the status line. Commit.

> The goals-bucket removal needs no frontend change (User Model page renders active buckets). Confirm the User Model page no longer shows "Goals" after rebuild.

---

## Phase E — Final verification

### Task E1: Full suite + manual smoke
1. `cd backend && python -m pytest` → green. `cd frontend && npx tsc --noEmit` → clean.
2. Rebuild: `docker compose up --build`. Then:
   - User Model page shows 7 buckets, no Goals bucket; Goals page still works.
   - Companion references something recent ("I saw you added …").
   - Understanding chat: "what's overdue?" / "how far is my OPT plan?" / "my short-term goals?" / "did I do my routine today?" return exact-state answers, with the `checking_state` status flashing; a non-structured question shows no structured block.
   - Fast mode answers without structured data.
3. **REQUIRED SUB-SKILL:** superpowers:requesting-code-review, then superpowers:finishing-a-development-branch.

---

## Notes & deferred
- Documents/logs as structured-query modules; true function-calling; onboarding-defined bucket structure; reviewed bucket splitting.
