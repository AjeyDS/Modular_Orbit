# Goals Capture, Document Enrichment & Log Deletion — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add first-class goal capture (Goals table CRUD + API + page + casual proposals), make documents selectively enrich Story Buckets, and make logs deletable/archivable.

**Architecture:** Goals get plain-SQL CRUD on the existing `goals` table (stable `goal_id` slug) plus REST endpoints, a Goals page, and a `"goals"` Capture Proposal target (Companion/Logs/Chat) that confirms into a tentative goal. Documents reuse the companion's bucket-key normalization (extracted to a shared module) via a new LLM routing step that writes pending `documents` bucket updates and weaves them — bypassing the dead lexical-connection path. Logs expose `DELETE`/archive endpoints wired to existing service functions.

**Tech Stack:** Python 3 / FastAPI / psycopg / Gemini backend; pytest (LLM auto-disabled under pytest → fallbacks default; monkeypatch `generate_json` for LLM paths). React + TS + Vite frontend (no unit-test harness — verify via the app).

**Design doc:** `docs/plans/2026-06-10-goals-docs-logs-design.md`

**Conventions:** see `docs/plans/2026-06-09-curious-companion.md` header. Backend tests: `cd backend && python -m pytest` against a test DB (DATABASE_URL containing "test"). Goal tests → `backend/tests/test_user_model.py`; chat → `test_chat_actions.py`; documents → `test_documents_module.py`; logs → `test_logs_module.py`.

---

## Phase A — Shared bucket-key helper (DRY refactor)

### Task A1: Extract `normalize_bucket_key` + allowed-keys line

**Files:**
- Create: `backend/app/lifecycle/bucket_keys.py`
- Modify: `backend/app/modules/companion.py` (import from the new module; delete local copies)
- Test: `backend/tests/test_bucket_keys.py` (new)

**Step 1: Write the failing test**

```python
# backend/tests/test_bucket_keys.py
from app.lifecycle.bucket_keys import normalize_bucket_key, KNOWN_BUCKET_KEYS, ALLOWED_KEYS_LINE


def test_normalize_maps_display_names_and_rejects_invented() -> None:
    assert normalize_bucket_key("Aspirations") == "aspirations"
    assert normalize_bucket_key("Who Am I") == "who_am_i"
    assert normalize_bucket_key("career") == "career"
    assert normalize_bucket_key("employment_authorization_document") is None
    assert normalize_bucket_key(None) is None


def test_allowed_keys_line_lists_all_keys() -> None:
    for key in KNOWN_BUCKET_KEYS:
        assert key in ALLOWED_KEYS_LINE
```

**Step 2: Run → fail.** `cd backend && python -m pytest tests/test_bucket_keys.py -v` → FAIL (module missing).

**Step 3: Implement**

```python
# backend/app/lifecycle/bucket_keys.py
from __future__ import annotations
from typing import Any
from app.chat.actions import KNOWN_BUCKET_KEYS  # the canonical 8 keys

ALLOWED_KEYS_LINE = (
    "Allowed bucket_key values — use EXACTLY one of these stable keys, lowercase, "
    "never a display name or invented key: " + ", ".join(sorted(KNOWN_BUCKET_KEYS)) + "."
)

def normalize_bucket_key(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    key = raw.strip().lower().replace(" ", "_").replace("-", "_")
    while "__" in key:
        key = key.replace("__", "_")
    return key if key in KNOWN_BUCKET_KEYS else None
```

(If importing `KNOWN_BUCKET_KEYS` from `app.chat.actions` risks a cycle, move the literal set here and have `chat.actions` import it instead.)

In `companion.py`: replace the local `_normalize_bucket_key` and `_ALLOWED_KEYS_LINE` with imports: `from app.lifecycle.bucket_keys import normalize_bucket_key, ALLOWED_KEYS_LINE`. Update call sites (`_normalize_bucket_key` → `normalize_bucket_key`, `_ALLOWED_KEYS_LINE` → `ALLOWED_KEYS_LINE`).

**Step 4: Run → pass.** `cd backend && python -m pytest tests/test_bucket_keys.py tests/test_companion.py -v` → PASS.

**Step 5: Commit** `git commit -m "refactor: extract shared bucket-key normalization"`

---

## Phase B — Goals service CRUD

### Task B1: `create_goal`

**Files:** Modify `backend/app/user_model/goals.py`; export from `app/user_model/__init__.py`. Test: `backend/tests/test_user_model.py`.

**Step 1: Failing test**

```python
from app.user_model.goals import create_goal, list_goals


def test_create_goal_inserts_tentative_with_stable_slug(tmp_path) -> None:
    # conftest truncates + seeds; goals table starts empty
    g = create_goal(title="Build a data engineering career", body="Because…")
    assert g.goal_id == "build-a-data-engineering-career"
    assert g.status == "tentative"
    assert any(x.goal_id == g.goal_id for x in list_goals())


def test_create_goal_slug_collision_gets_suffix() -> None:
    a = create_goal(title="Run a marathon", body="")
    b = create_goal(title="Run a marathon", body="")
    assert a.goal_id != b.goal_id
    assert b.goal_id.startswith("run-a-marathon")
```

**Step 2: Run → fail.** `pytest tests/test_user_model.py -k create_goal -v`

**Step 3: Implement** (in `goals.py`)

```python
def _slugify_goal(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug[:60].strip("-") or "goal"

def create_goal(title: str, body: str = "", status: GoalStatus = "tentative") -> GoalEntry:
    base = _slugify_goal(title)
    with transaction() as conn:
        with conn.cursor() as cur:
            goal_id = base
            n = 2
            while True:
                cur.execute("SELECT 1 FROM goals WHERE goal_id = %s", (goal_id,))
                if cur.fetchone() is None:
                    break
                goal_id = f"{base}-{n}"; n += 1
            cur.execute("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM goals WHERE status = %s", (status,))
            position = cur.fetchone()["p"]
            cur.execute(
                """
                INSERT INTO goals (goal_id, title, body, status, position)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING goal_id, title, body, status
                """,
                (goal_id, title, body, status, position),
            )
            row = cur.fetchone()
    return GoalEntry(goal_id=row["goal_id"], title=row["title"], body=row["body"] or "", status=row["status"])
```

Add `create_goal` to `app/user_model/__init__.py` exports.

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(goals): create_goal with stable slug"`

---

### Task B2: `update_goal` + `delete_goal`

**Files:** Modify `goals.py` + `__init__.py`. Test: `test_user_model.py`.

**Step 1: Failing test**

```python
from app.user_model.goals import create_goal, update_goal, delete_goal, list_goals
import pytest


def test_update_goal_preserves_id() -> None:
    g = create_goal(title="Learn Rust", body="x")
    u = update_goal(g.goal_id, title="Learn Rust deeply", body="y")
    assert u.goal_id == g.goal_id
    assert u.title == "Learn Rust deeply" and u.body == "y"


def test_delete_goal_removes_only_target() -> None:
    a = create_goal(title="Goal A"); b = create_goal(title="Goal B")
    delete_goal(a.goal_id)
    ids = {x.goal_id for x in list_goals()}
    assert a.goal_id not in ids and b.goal_id in ids


def test_update_missing_goal_raises() -> None:
    with pytest.raises(ValueError):
        update_goal("nope", title="x")
```

**Step 2: Run → fail.**

**Step 3: Implement**

```python
def update_goal(goal_id: str, *, title: str | None = None, body: str | None = None) -> GoalEntry:
    sets, params = [], []
    if title is not None: sets.append("title = %s"); params.append(title)
    if body is not None: sets.append("body = %s"); params.append(body)
    if not sets:
        # nothing to change; return current
        for g in list_goals():
            if g.goal_id == goal_id: return g
        raise ValueError(f"Unknown goal: {goal_id}")
    params.append(goal_id)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE goals SET {', '.join(sets)}, updated_at = now() WHERE goal_id = %s "
                        "RETURNING goal_id, title, body, status", params)
            row = cur.fetchone()
            if row is None: raise ValueError(f"Unknown goal: {goal_id}")
    return GoalEntry(goal_id=row["goal_id"], title=row["title"], body=row["body"] or "", status=row["status"])

def delete_goal(goal_id: str) -> None:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM goals WHERE goal_id = %s RETURNING goal_id", (goal_id,))
            if cur.fetchone() is None: raise ValueError(f"Unknown goal: {goal_id}")
```

Export both.

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(goals): update_goal and delete_goal"`

---

## Phase C — Goals API

### Task C1: Goal endpoints

**Files:** Modify `backend/app/api/user_model.py`. Test: `test_user_model.py` (via TestClient).

**Step 1: Failing test**

```python
from fastapi.testclient import TestClient
from app.main import app


def test_goal_crud_http() -> None:
    c = TestClient(app)
    r = c.post("/user-model/goals", json={"title": "Save 10k", "body": "buffer"})
    assert r.status_code == 201
    gid = r.json()["goal_id"]
    assert c.get("/user-model/goals").status_code == 200
    assert c.patch(f"/user-model/goals/{gid}", json={"body": "bigger buffer"}).json()["body"] == "bigger buffer"
    assert c.post(f"/user-model/goals/{gid}/promote").json()["status"] == "active"
    assert c.delete(f"/user-model/goals/{gid}").status_code == 204
    assert c.delete(f"/user-model/goals/{gid}").status_code == 404
```

**Step 2: Run → fail** (routes 404/405).

**Step 3: Implement** — add Pydantic models (`GoalCreate{title, body=""}`, `GoalUpdate{title?, body?}`, `GoalItem` mirroring `GoalEntry`) and routes:
- `GET /user-model/goals` → `list_goals()`
- `POST /user-model/goals` (201) → `create_goal(...)`
- `PATCH /user-model/goals/{goal_id}` → `update_goal(...)`, `ValueError`→404
- `POST /user-model/goals/{goal_id}/promote` → `promote_goal(...)`, `ValueError`→404
- `DELETE /user-model/goals/{goal_id}` (204) → `delete_goal(...)`, `ValueError`→404

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(goals): REST endpoints"`

---

## Phase D — Goal Capture Proposals (Companion + Logs + Chat)

### Task D1: Add `goals` proposal target + confirm contract

**Files:** Modify `backend/app/chat/actions.py`, `backend/app/db/schema.py` (add `created_goal_id` column), `backend/tests/conftest.py` (no new table; column add is fine). Test: `test_chat_actions.py`.

**Step 1: Failing test**

```python
from app.chat.actions import _detect_capture_proposals, _proposal_for_module


def test_explicit_add_goal_detected() -> None:
    p = _detect_capture_proposals("add this as a goal: become a staff engineer")
    assert p and p[0].module_id == "goals"
    assert p[0].item_type == "goal"
```

**Step 2: Run → fail.**

**Step 3: Implement**
- `DetectedProposal.module_id`: add `"goals"` to the Literal.
- `_detect_explicit`: add pattern `(r"(?:add|make|set)\s+(?:this\s+)?(?:as\s+)?(?:a\s+)?goals?\s*:?\s*(.+)", "goals")`.
- `_proposal_for_module`: add a `goals` branch → `DetectedProposal(module_id="goals", item_type="goal", title=_derive_title(text), description=text, payload={}, confidence_bucket=bucket, explicit_request=explicit)`.
- `_detect_suggested_with_llm`: add `goals` to the module list + prompt ("goals: a durable aspiration or direction the person wants, distinct from an actionable task"). Add `"goals"` to the allowed `module_id` set.
- Schema: add `ALTER TABLE capture_proposals ADD COLUMN IF NOT EXISTS created_goal_id TEXT;` in `schema.py` `ensure_schema()`.

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(goals): detect goal capture proposals"`

---

### Task D2: Confirm a goal proposal → tentative goal

**Files:** Modify `backend/app/chat/actions.py` (`_create_from_proposal`, `confirm_capture_proposal`, `ConfirmCaptureProposalResponse`). Test: `test_chat_actions.py`.

**Step 1: Failing test**

```python
from app.chat.actions import (
    _persist_preview, confirm_capture_proposal, ConfirmCaptureProposalRequest, _proposal_for_module,
)
from app.user_model.goals import list_goals


def test_confirming_goal_proposal_creates_tentative_goal() -> None:
    proposal = _proposal_for_module("goals", "become a staff engineer", explicit=True)
    preview = _persist_preview("sess-1", proposal)
    resp = confirm_capture_proposal(ConfirmCaptureProposalRequest(proposal_id=preview.id))
    assert resp.goal_id is not None
    assert any(g.goal_id == resp.goal_id and g.status == "tentative" for g in list_goals())
```

(Reuse the existing `_persist_preview` path; `_should_surface` not needed for an explicit proposal in a unit test.)

**Step 2: Run → fail.**

**Step 3: Implement**
- `ConfirmCaptureProposalResponse`: make `life_item_id: UUID | None = None`; add `goal_id: str | None = None`.
- `_create_from_proposal`: add `goals` branch → `g = create_goal(title=proposal["title"], body=proposal["description"], status="tentative"); return {"goal_id": g.goal_id}`.
- `confirm_capture_proposal`: when `module_id == "goals"`, persist `created_goal_id` (instead of `created_life_item_id`); idempotency check uses `created_goal_id`; build response with `goal_id`. For non-goals, unchanged (`life_item_id`).

**Step 4: Run → pass.** Run full `pytest tests/test_chat_actions.py -v`. **Step 5: Commit** `git commit -m "feat(goals): confirm goal proposals into tentative goals"`

---

## Phase E — Document → Story Bucket enrichment

### Task E1: Route a document's meaning to bucket keys + write/weave updates

**Files:** Modify `backend/app/modules/documents.py`. Test: `backend/tests/test_documents_module.py`.

**Step 1: Failing test**

```python
import app.modules.documents as docs
from app.modules.documents import DocumentCreate, create_document
from app.db import connect


def test_life_relevant_document_enriches_buckets(tmp_path, monkeypatch) -> None:
    # route returns one known key
    monkeypatch.setattr(docs, "_route_document_buckets", lambda content, summary: ["career"])
    create_document(DocumentCreate(original_name="plan.md", content="LLC self-employment action plan"), review=False, review_root=tmp_path)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) c FROM bucket_updates WHERE source_event->>'source'='documents'")
            assert cur.fetchone()["c"] == 1


def test_reference_document_enriches_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(docs, "_route_document_buckets", lambda content, summary: [])
    create_document(DocumentCreate(original_name="fee.pdf", content="SEVIS fee receipt number 123"), review=False, review_root=tmp_path)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) c FROM bucket_updates WHERE source_event->>'source'='documents'")
            assert cur.fetchone()["c"] == 0
```

(Using `review=False` isolates the new enrichment from the lexical connection review.)

**Step 2: Run → fail** (`_route_document_buckets` missing; no enrichment wired).

**Step 3: Implement**
- Add `_route_document_buckets(content: str, summary: str) -> list[str]`:
  ```python
  from app.lifecycle.bucket_keys import normalize_bucket_key, ALLOWED_KEYS_LINE
  def _route_document_buckets(content: str, summary: str) -> list[str]:
      try:
          data = generate_json(
              f"Document summary:\n{summary}\n\nExcerpt:\n{content[:2000]}\n\n"
              'Return JSON: {"bucket_keys": ["..."]}. Include a key ONLY if this '
              "document meaningfully informs the person's life narrative for that "
              "area; return [] for purely logistical/reference documents.",
              system="Route a personal document to life-story buckets. Return only JSON. " + ALLOWED_KEYS_LINE,
              temperature=0.1, max_output_tokens=120,
          )
          keys = [normalize_bucket_key(k) for k in (data.get("bucket_keys") or [])]
          out = []
          for k in keys:
              if k and k not in out: out.append(k)
          return out[:3]
      except (LLMUnavailable, Exception):
          return []
  ```
- Add `_write_document_bucket_updates(life_item_id, bucket_keys, text)`: for each key look up the active story bucket id and INSERT a pending `bucket_updates` row with `source_event = {"source": "documents", "bucket_key": key}` and `update_text = text`; set the document's `bucket_update_status = 'complete'` when any were written. Then weave each affected bucket (`weave_story_bucket`).
- In `create_document`, after `_annotate_document`/ingestion: `bucket_keys = _route_document_buckets(payload.content, summary)`; if `bucket_keys`, call `_write_document_bucket_updates(result.item["id"], bucket_keys, connection_summary)`. This runs regardless of the lexical connection review (replaces reliance on the dead `_set_document_bucket_update_text`/`_auto_weave_connected_buckets` bucket path; leave those for any future story_bucket connections).

**Step 4: Run → pass.** Run `pytest tests/test_documents_module.py -v`. **Step 5: Commit** `git commit -m "feat(documents): selective LLM-routed bucket enrichment"`

---

## Phase F — Log deletion

### Task F1: DELETE + archive endpoints

**Files:** Modify `backend/app/api/logs.py`. Test: `backend/tests/test_logs_module.py`.

**Step 1: Failing test**

```python
from fastapi.testclient import TestClient
from app.main import app


def test_log_delete_and_archive_http(tmp_path) -> None:
    c = TestClient(app)
    created = c.post("/logs", json={"text": "test log entry"}).json()
    lid = created["id"]
    assert c.post(f"/logs/{lid}/archive").json()["lifecycle_status"] == "archived"
    assert c.delete(f"/logs/{lid}").status_code == 204
    assert c.delete(f"/logs/{lid}").status_code == 404
```

**Step 2: Run → fail.**

**Step 3: Implement** — in `api/logs.py`, import `archive_log, remove_log` and `LifeItemError` (from `app.lifecycle`):
```python
@router.post("/{log_id}/archive", response_model=LogItem)
def archive_log_endpoint(log_id: UUID) -> LogItem:
    try:
        return archive_log(log_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.delete("/{log_id}", status_code=204)
def delete_log_endpoint(log_id: UUID) -> Response:
    try:
        remove_log(log_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)
```

**Step 4: Run → pass.** Run full `pytest`. **Step 5: Commit** `git commit -m "feat(logs): delete and archive endpoints"`

---

## Phase G — Frontend (verify via app; no unit-test harness)

> Verify each task with the `/run` skill + `mcp__Claude_Preview__preview_screenshot`.

### Task G1: API client fns
Modify `frontend/src/lib/api.ts`: `listGoals`, `createGoal`, `updateGoal`, `promoteGoal`, `deleteGoal`; `deleteLog`, `archiveLog`; and types. Handle `ConfirmCaptureProposalResponse.goal_id` (now optional `life_item_id`). Verify `npx tsc --noEmit`. Commit.

### Task G2: Goals page
Create `frontend/src/pages/GoalsPage.tsx` + route + sidebar entry: lists Active + Tentative; add (title + reason), edit, promote, delete; optimistic updates. Verify by creating/promoting/deleting a goal. Commit.

### Task G3: Log row actions
Modify `frontend/src/pages/LogsPage.tsx`: per-row delete (confirm) + archive actions calling the new client fns; remove the stuck `"It's going good"` entry to confirm. Commit.

### Task G4: Goal proposal cards
Confirm chat/companion render the `goals` Capture Proposal preview ("Add as goal?") and that confirming calls `confirm` and shows the goal on the Goals page. Adjust the proposal card to handle the goal target label. Commit.

---

## Phase H — Final verification

### Task H1: Full suite + manual smoke
1. `cd backend && python -m pytest` → green. `cd frontend && npx tsc --noEmit` → clean.
2. Manual via `/run` (rebuild containers: `docker compose up --build`):
   - Create a goal on the Goals page; say "I want to start an LLC" in chat/companion → goal proposal → confirm → appears as Tentative → promote.
   - Upload a life-relevant doc → a `documents` bucket update appears and a Story Bucket gains a woven line; upload a pure-reference doc → no bucket change.
   - Delete a log; archive a log.
3. **REQUIRED SUB-SKILL:** superpowers:requesting-code-review, then superpowers:finishing-a-development-branch.

---

## Notes & deferred (do NOT build now)

- Onboarding-defined bucket structure; reviewed size-triggered bucket splitting.
- Improving Connection Review lexical/semantic scoring.
- Per-upload document activity logs (decided against).
