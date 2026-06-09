# User-Model-Aware Modules Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Orbit's modules user-model-aware (tasks reorganized through the user model, documents tagged + connection-explained) and make the user model itself a visible top-level module, plus a Curious completion preview.

**Architecture:** Each feature enriches existing lifecycle machinery rather than bypassing it. New LLM calls follow the existing typed `generate_json` + deterministic-fallback pattern (see `app/modules/tasks.py:306` priority advisor). New persistence uses idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in `app/db/schema.py:ensure_schema()`, which runs per-test. Frontend relocates/extends existing pages.

**Tech Stack:** FastAPI + psycopg (Postgres/pgvector), Pydantic v2, pytest + FastAPI TestClient; React + TypeScript + Vite + Tailwind + framer-motion.

**Design reference:** `docs/plans/2026-06-08-user-model-aware-modules-design.md`

**Conventions to match:**
- Backend tests live in `backend/tests/test_<module>_module.py`, use the `ensure_schema()` + `sync_module_registry()` + `ensure_story_buckets(tmp_path, conn)` fixture pattern (see `tests/test_tasks_module.py:28`).
- Run backend tests from `backend/`: `python -m pytest tests/test_x.py::test_name -v`.
- LLM-dependent code MUST keep working when `LLM_MODE` is stub: wrap `generate_json` in `try/except (LLMUnavailable, Exception)` and fall back deterministically (mirror `tasks.py:318-336`).
- Commit after each task with a `feat:`/`refactor:`/`test:` message.

---

## Phase 1 — User Model as a top-level module

Pure frontend relocation; no backend change. The `/user-model/buckets` API already exists.

### Task 1.1: Extract the bucket editor into its own page

**Files:**
- Read first: `frontend/src/pages/SettingsPage.tsx` (the `UserModelTab` component, ~line 177 onward, and its imports from `../lib/api`).
- Create: `frontend/src/pages/UserModelPage.tsx`
- Modify: `frontend/src/App.tsx`

**Step 1: Create `UserModelPage.tsx`**

Move the `UserModelTab` component body into a new default-export page component named `UserModelPage`. Wrap it in the standard page shell used by other pages (copy the outer `<div className="min-h-[calc(100vh-3rem)] ...">` + `pageContentClass` wrapper from `DocumentsPage.tsx:55-57`), and add a page `<header>` with an `<h1>` "User Model" and a one-line subtitle ("What Orbit understands about you. Edits lock a bucket from automatic rewriting."). Keep all existing fetch/save logic (`fetchStoryBuckets`, `updateStoryBucket`).

**Step 2: Mount the route in `App.tsx`**

Add import `import UserModelPage from './pages/UserModelPage'` and a route alongside the others (see `App.tsx:99`):

```tsx
<Route path="/user-model" element={<UserModelPage />} />
```

**Step 3: Verify it renders**

Run: `cd frontend && npm run build`
Expected: build succeeds with no TypeScript errors.

**Step 4: Commit**

```bash
git add frontend/src/pages/UserModelPage.tsx frontend/src/App.tsx
git commit -m "feat(user-model): add standalone User Model page"
```

### Task 1.2: Add User Model to navigation

**Files:**
- Modify: `frontend/src/layout/moduleOrder.ts:2`
- Modify: `frontend/src/layout/Sidebar.tsx`

**Step 1: Add to default order**

In `moduleOrder.ts`, insert `'user_model'` into `DEFAULT_ORDER` (place it after `'documents'`):

```ts
const DEFAULT_ORDER = ['chat', 'curious', 'tasks', 'plans', 'logs', 'documents', 'user_model', 'recommendations', 'strategies', 'goals']
```

**Step 2: Add the sidebar entry**

Read `Sidebar.tsx` to find how nav items map id → route → icon. Add a `user_model` entry pointing at `/user-model` with an appropriate `lucide-react` icon (e.g. `ShieldCheck`, already used for the user model in Settings). Match the existing item shape exactly.

**Step 3: Verify**

Run: `cd frontend && npm run build`
Expected: build succeeds; the sidebar shows "User Model".

**Step 4: Commit**

```bash
git add frontend/src/layout/moduleOrder.ts frontend/src/layout/Sidebar.tsx
git commit -m "feat(user-model): add User Model to navigation"
```

### Task 1.3: Remove the User Model tab from Settings

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

**Step 1: Remove the tab and its panel**

- Remove `'user-model'` from the `SettingsTab` union (`SettingsPage.tsx:8`), the `tabs` array (line ~13), and `readHashTab` (line ~19).
- Remove the `{tab === 'user-model' && <UserModelTab />}` render (line ~77).
- Delete the now-unused `UserModelTab` component and any imports it solely used (`fetchStoryBuckets`, `updateStoryBucket`, `StoryBucketItem`) — **only if** no longer referenced in this file.
- Where the tab used to be, this is optional: a small muted note is not required since the nav now carries it. Keep Settings clean.

**Step 2: Verify**

Run: `cd frontend && npm run build`
Expected: build succeeds, no unused-import errors.

**Step 3: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "refactor(settings): remove User Model tab; it now lives in its own module"
```

---

## Phase 2 — Documents: category tag + connection sentence

### Task 2.1: Add annotation columns to `document_items`

**Files:**
- Modify: `backend/app/db/schema.py` (after the `document_items` CREATE TABLE, ~line 154)
- Test: `backend/tests/test_schema.py`

**Step 1: Write the failing test**

Add to `test_schema.py` a test asserting the columns exist:

```python
def test_document_items_has_annotation_columns():
    from app.db import connect, ensure_schema
    ensure_schema()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'document_items'
                  AND column_name IN ('category_tag', 'connection_summary', 'tag_status')
                """
            )
            cols = {row["column_name"] for row in cur.fetchall()}
    assert cols == {"category_tag", "connection_summary", "tag_status"}
```

**Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_schema.py::test_document_items_has_annotation_columns -v`
Expected: FAIL (columns missing).

**Step 3: Add the columns**

After the `document_items` CREATE TABLE block in `schema.py`, add:

```python
            cur.execute(
                """
                ALTER TABLE document_items
                ADD COLUMN IF NOT EXISTS category_tag TEXT NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS connection_summary TEXT NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS tag_status TEXT NOT NULL DEFAULT 'pending'
                """
            )
```

**Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_schema.py::test_document_items_has_annotation_columns -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/db/schema.py backend/tests/test_schema.py
git commit -m "feat(documents): add annotation columns to document_items"
```

### Task 2.2: Generate tag + connection summary on ingest

**Files:**
- Modify: `backend/app/modules/documents.py`
- Test: `backend/tests/test_documents_module.py`

**Step 1: Write the failing test**

In stub LLM mode (default in tests), the deterministic fallback must run. Add:

```python
def test_create_document_populates_annotation_fallback(tmp_path):
    from app.modules.documents import create_document, DocumentCreate
    doc = create_document(
        DocumentCreate(original_name="career_notes.md",
                       content="Planning a transition into staff engineering and mentoring."),
        review_root=tmp_path,
    )
    assert doc.tag_status in {"complete", "failed"}
    assert doc.category_tag != ""
    assert doc.connection_summary != ""
```

Also extend the `DocumentItem` model (`documents.py:50`) with the three fields and map them in `_row_to_document` (and add to the SELECT lists in `list_documents`/`get_document`). The test imports will fail until then.

**Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_documents_module.py::test_create_document_populates_annotation_fallback -v`
Expected: FAIL (fields missing / empty).

**Step 3: Implement annotation generation**

Add a helper that mirrors the priority advisor pattern:

```python
def _annotate_document(content: str) -> tuple[str, str, str]:
    """Return (category_tag, connection_summary, tag_status)."""
    from app.user_model import list_goals, list_story_bucket_items
    context = {
        "story_buckets": [
            {"name": b.display_name, "description": b.description}
            for b in list_story_bucket_items()
        ],
        "active_goals": [
            {"title": g.title} for g in list_goals() if g.status == "active"
        ],
    }
    try:
        response = generate_json(
            _annotation_prompt(content[:4000], context),
            system=(
                "You categorize a personal document and explain in one sentence how it "
                "connects to the person, using their story buckets and goals. "
                "Return only JSON: {\"category_tag\": str, \"connection_summary\": str}."
            ),
            temperature=0.2,
            max_output_tokens=300,
        )
        tag = _slug_tag(str(response.get("category_tag") or ""))
        summary = " ".join(str(response.get("connection_summary") or "").split())[:280]
        if tag and summary:
            return tag, summary, "complete"
    except (LLMUnavailable, Exception):
        pass
    return _fallback_tag(content), _fallback_summary(content), "failed"
```

Add `_annotation_prompt`, `_slug_tag` (lowercase, hyphenated, <=40 chars), `_fallback_tag` (e.g. `"uncategorized"`), and `_fallback_summary` (reuse `_summary(content)`). Import `generate_json`, `LLMUnavailable` from `app.llm`.

In `create_document`, after computing `summary` and before/around `create_life_item`, call `tag, conn_summary, tag_status = _annotate_document(payload.content)` and pass them into `side_table_data` and `payload`. After insert, persist them on the `document_items` row (extend the side-table write, or `UPDATE document_items SET category_tag=…, connection_summary=…, tag_status=…`). Update `DocumentItem`, the SELECTs, and `_row_to_document`.

**Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_documents_module.py -v`
Expected: PASS (new test + existing tests still green).

**Step 5: Commit**

```bash
git add backend/app/modules/documents.py backend/tests/test_documents_module.py
git commit -m "feat(documents): generate category tag and connection summary on ingest"
```

### Task 2.3: Annotation edit endpoint

**Files:**
- Modify: `backend/app/modules/documents.py` (service fn + model)
- Modify: `backend/app/api/documents.py` (route)
- Test: `backend/tests/test_documents_module.py`

**Step 1: Write the failing test**

```python
def test_update_document_annotation(tmp_path):
    from app.modules.documents import create_document, DocumentCreate, update_document_annotation, DocumentAnnotation
    doc = create_document(DocumentCreate(original_name="n.md", content="hello world content"), review_root=tmp_path)
    updated = update_document_annotation(doc.id, DocumentAnnotation(category_tag="job-search", connection_summary="Relates to your career goal."))
    assert updated.category_tag == "job-search"
    assert updated.connection_summary == "Relates to your career goal."
```

**Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_documents_module.py::test_update_document_annotation -v`
Expected: FAIL (function missing).

**Step 3: Implement**

Add to `documents.py`:

```python
class DocumentAnnotation(BaseModel):
    category_tag: str | None = Field(default=None, max_length=40)
    connection_summary: str | None = Field(default=None, max_length=400)


def update_document_annotation(document_id: UUID | str, payload: DocumentAnnotation) -> DocumentItem:
    document = get_document(document_id)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE document_items
                SET category_tag = COALESCE(%s, category_tag),
                    connection_summary = COALESCE(%s, connection_summary),
                    tag_status = 'complete',
                    updated_at = now()
                WHERE life_item_id = %s
                """,
                (payload.category_tag, payload.connection_summary, document.id),
            )
    return get_document(document.id)
```

Add the route in `api/documents.py`:

```python
@router.patch("/{document_id}/annotation", response_model=DocumentItem)
def update_document_annotation_endpoint(document_id: UUID, payload: DocumentAnnotation) -> DocumentItem:
    try:
        return update_document_annotation(document_id, payload)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
```

Import `DocumentAnnotation`, `update_document_annotation` in `api/documents.py`.

**Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_documents_module.py::test_update_document_annotation -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/modules/documents.py backend/app/api/documents.py backend/tests/test_documents_module.py
git commit -m "feat(documents): add annotation edit endpoint"
```

### Task 2.4: Auto-weave the connection summary into the right bucket

**Files:**
- Modify: `backend/app/modules/documents.py` (`create_document`, after `process_lifecycle_for_item`)
- Test: `backend/tests/test_documents_module.py`

**Step 1: Write the failing test**

Connection Review must have linked the doc to at least one Story Bucket; after auto-weave that bucket's content should grow. Write a test that creates a document whose content strongly overlaps a seeded bucket (e.g. "career", "work", "role") and asserts the connected bucket's content changed, OR (LLM-stub-safe) that `weave_story_bucket` was invoked for each connected bucket. Simplest deterministic assertion: after `create_document`, there are no leftover `pending` bucket_updates for that life item.

```python
def test_create_document_auto_weaves_connected_buckets(tmp_path):
    from app.modules.documents import create_document, DocumentCreate
    from app.db import connect
    doc = create_document(
        DocumentCreate(original_name="career.md",
                       content="career role work job promotion mentoring leadership team"),
        review_root=tmp_path,
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM bucket_updates WHERE life_item_id = %s AND status = 'pending'",
                (doc.id,),
            )
            pending = cur.fetchone()["n"]
    assert pending == 0
```

**Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_documents_module.py::test_create_document_auto_weaves_connected_buckets -v`
Expected: FAIL (pending updates remain unwoven).

**Step 3: Implement auto-weave**

In `create_document`, after the `process_lifecycle_for_item(...)` call, add a helper that finds the Story Buckets this life item connects to and weaves each:

```python
def _auto_weave_connected_buckets(life_item_id: UUID) -> None:
    from app.lifecycle.story_weave import StoryWeaveError, weave_story_bucket
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT target_id::uuid AS bucket_id
                FROM item_connections
                WHERE source_life_item_id = %s AND target_type = 'story_bucket'
                """,
                (life_item_id,),
            )
            bucket_ids = [row["bucket_id"] for row in cur.fetchall()]
    for bucket_id in bucket_ids:
        try:
            weave_story_bucket(bucket_id)
        except StoryWeaveError:
            continue
```

Call it inside the `if result.created and review:` block, after `process_lifecycle_for_item`. (Verify `weave_story_bucket`'s signature in `app/lifecycle/story_weave.py` and pass the bucket id form it expects.)

**Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_documents_module.py -v`
Expected: PASS (all document tests green).

**Step 5: Commit**

```bash
git add backend/app/modules/documents.py backend/tests/test_documents_module.py
git commit -m "feat(documents): auto-weave connection summary into connected buckets on ingest"
```

### Task 2.5: Surface tag + summary in the documents list (frontend)

**Files:**
- Modify: `frontend/src/lib/api.ts` (`DocumentItem` type + `updateDocumentAnnotation`)
- Modify: `frontend/src/pages/DocumentsPage.tsx` (`DocumentRow`)

**Step 1: Extend the API client**

In `api.ts`, add `category_tag: string`, `connection_summary: string`, `tag_status: string` to the `DocumentItem` type, and add:

```ts
export async function updateDocumentAnnotation(id: string, body: { category_tag?: string; connection_summary?: string }) {
  // follow the existing renameDocument PATCH pattern in this file
}
```

(Model it on the existing `renameDocument` call.)

**Step 2: Render under each row**

In `DocumentsPage.tsx`'s `DocumentRow` (around line 158), below the existing metadata line, render the `category_tag` as a chip and `connection_summary` as muted text. Make both inline-editable (reuse the existing rename inline-edit pattern at lines 181-205: click-to-edit, Enter saves via `updateDocumentAnnotation`, Escape cancels). Call `onChanged()` after a successful save.

**Step 3: Verify**

Run: `cd frontend && npm run build`
Expected: build succeeds.

**Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/pages/DocumentsPage.tsx
git commit -m "feat(documents): show and edit category tag and connection summary"
```

### Task 2.6: Multi-file sequential upload (frontend)

**Files:**
- Modify: `frontend/src/components/documents/AddDocumentDialog.tsx`

**Step 1: Accept multiple files**

- Add `multiple` to the `<input type="file">` (line ~231) and `accept` unchanged.
- Replace `pendingFile: File | null` with `pendingFiles: File[]`; the drop and change handlers append to the array. Render one chip per file (reuse the chip at lines 245-266) with an individual remove.

**Step 2: Upload sequentially with per-file status**

Replace `handleUpload` so it iterates `pendingFiles` and `await uploadDocument(file)` one at a time. Track a per-file status map (`queued | uploading | done | error`) and render it on each chip. On completion call `onSaved(\`${n} files uploaded…\`)`. Keep the dialog open until all finish (or surface per-file errors and let the user retry the failed ones).

**Step 3: Verify**

Run: `cd frontend && npm run build`
Expected: build succeeds.

**Step 4: Commit**

```bash
git add frontend/src/components/documents/AddDocumentDialog.tsx
git commit -m "feat(documents): support multi-file sequential upload"
```

---

## Phase 3 — Tasks: fuzzy due date + auto-rewrite + expandable row

### Task 3.1: Add `due_window` column

**Files:**
- Modify: `backend/app/db/schema.py` (after `task_items` CREATE TABLE, ~line 118)
- Test: `backend/tests/test_schema.py`

**Step 1: Write the failing test**

```python
def test_task_items_has_due_window():
    from app.db import connect, ensure_schema
    ensure_schema()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name='task_items' AND column_name='due_window'"
            )
            assert cur.fetchone() is not None
```

**Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_schema.py::test_task_items_has_due_window -v`
Expected: FAIL.

**Step 3: Add the column**

After the `task_items` CREATE TABLE block:

```python
            cur.execute(
                """
                ALTER TABLE task_items
                ADD COLUMN IF NOT EXISTS due_window TEXT NOT NULL DEFAULT 'this_week'
                    CHECK (due_window IN ('this_week', 'this_month', 'someday', 'exact'))
                """
            )
```

**Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_schema.py::test_task_items_has_due_window -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/db/schema.py backend/tests/test_schema.py
git commit -m "feat(tasks): add due_window column to task_items"
```

### Task 3.2: Wire `due_window` through the Tasks service

**Files:**
- Modify: `backend/app/modules/tasks.py` (`TaskCreate`, `TaskUpdate`, `TaskItem`, `create_task`, `update_task`, `_task_payload`, `_row_to_task`, the SELECTs in `list_tasks`/`get_task`, and side-table writes)
- Test: `backend/tests/test_tasks_module.py`

**Step 1: Write the failing test**

```python
def test_create_task_defaults_due_window_this_week(tmp_path):
    from app.modules.tasks import create_task, TaskCreate
    task = create_task(TaskCreate(title="ship it"), review_root=tmp_path)
    assert task.due_window == "this_week"

def test_create_task_exact_window_with_date(tmp_path):
    from datetime import date
    from app.modules.tasks import create_task, TaskCreate
    task = create_task(TaskCreate(title="dentist", due_window="exact", due_date=date(2026, 7, 1)), review_root=tmp_path)
    assert task.due_window == "exact"
    assert task.due_date == date(2026, 7, 1)
```

**Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_tasks_module.py -k due_window -v`
Expected: FAIL.

**Step 3: Implement**

- Add `due_window: Literal["this_week","this_month","someday","exact"] = "this_week"` to `TaskCreate`; `due_window: Literal[...] | None = None` to `TaskUpdate`; `due_window: str` to `TaskItem`.
- Thread it through `_task_payload`, the `side_table_data`, the `task_items` INSERT/UPDATE, the two SELECTs (add `ti.due_window`), and `_row_to_task`.
- In `_fallback_task_sort_key` (line ~633) compute an **effective date** from `due_window`: `someday` → treat as no date; `this_week` → end of current week (Mon-anchored: `today + (6 - today.weekday())`); `this_month` → last day of month; `exact`/legacy → `due_date`. Use the effective date in the existing bucketing.

**Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_tasks_module.py -v`
Expected: PASS (new + existing tests green).

**Step 5: Commit**

```bash
git add backend/app/modules/tasks.py backend/tests/test_tasks_module.py
git commit -m "feat(tasks): thread due_window through the Tasks service"
```

### Task 3.3: Auto-rewrite task through the user model

**Files:**
- Modify: `backend/app/modules/tasks.py` (new `_rewrite_task`, `create_task`, `TaskItem`)
- Test: `backend/tests/test_tasks_module.py`

**Step 1: Write the failing test**

Stub-LLM-safe: fallback keeps the typed text and preserves the original.

```python
def test_create_task_preserves_original_on_rewrite(tmp_path):
    from app.modules.tasks import create_task, get_task, TaskCreate
    task = create_task(TaskCreate(title="email bob re: the q3 thing maybe", description="follow up"), review_root=tmp_path)
    assert task.original_title == "email bob re: the q3 thing maybe"
    assert task.rewrite_status in {"complete", "skipped"}
    assert task.title  # non-empty
```

**Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_tasks_module.py::test_create_task_preserves_original_on_rewrite -v`
Expected: FAIL (`original_title`/`rewrite_status` missing).

**Step 3: Implement**

- Store the original + status in the life item `payload` (no new column needed): add `original_title`, `original_description`, `rewrite_status` keys. Expose them on `TaskItem` by reading `li.payload` in the SELECTs (the SELECT already returns `li.*`, so `payload` is available in the row) and mapping in `_row_to_task`.
- Add a rewrite helper reusing the priority context:

```python
def _rewrite_task(title: str, description: str) -> tuple[str, str, str]:
    """Return (title, description, status). Falls back to the typed text."""
    context = _task_priority_context_summary()
    try:
        response = generate_json(
            _rewrite_prompt(title, description, context),
            system=(
                "You reorganize a freshly captured task using the person's goals and story "
                "buckets. Produce a short, clean imperative title and an organized body. "
                "Return only JSON: {\"title\": str, \"description\": str}."
            ),
            temperature=0.2,
            max_output_tokens=400,
        )
        new_title = " ".join(str(response.get("title") or "").split())[:120]
        new_desc = str(response.get("description") or "").strip()
        if new_title:
            return new_title, new_desc or description, "complete"
    except (LLMUnavailable, Exception):
        pass
    return title, description, "skipped"
```

Add `_rewrite_prompt`. In `create_task`, before `create_life_item`, compute `new_title, new_desc, rewrite_status = _rewrite_task(payload.title, payload.description)`; use them as the life item `title`/`description`; put `original_title=payload.title`, `original_description=payload.description`, `rewrite_status` into the item `payload`.

**Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_tasks_module.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/modules/tasks.py backend/tests/test_tasks_module.py
git commit -m "feat(tasks): auto-rewrite captured tasks through the user model, preserving the original"
```

### Task 3.4: Revert endpoint

**Files:**
- Modify: `backend/app/modules/tasks.py` (`revert_task_rewrite`)
- Modify: `backend/app/api/tasks.py` (route)
- Test: `backend/tests/test_tasks_module.py`

**Step 1: Write the failing test**

```python
def test_revert_task_rewrite_restores_original(tmp_path):
    from app.modules.tasks import create_task, update_task, revert_task_rewrite, TaskCreate, TaskUpdate
    task = create_task(TaskCreate(title="orig title", description="orig body"), review_root=tmp_path)
    update_task(task.id, TaskUpdate(title="rewritten title"))
    reverted = revert_task_rewrite(task.id)
    assert reverted.title == "orig title"
```

(Note: `create_task` stores `original_title="orig title"`. Even if rewrite is skipped in stub mode, the original equals the typed title, so revert is a no-op-but-correct restore.)

**Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_tasks_module.py::test_revert_task_rewrite_restores_original -v`
Expected: FAIL.

**Step 3: Implement**

```python
def revert_task_rewrite(task_id: UUID | str) -> TaskItem:
    task = get_task(task_id)
    payload = _get_life_item_payload(task_id)  # small helper: SELECT payload FROM life_items
    original_title = payload.get("original_title") or task.title
    original_description = payload.get("original_description") or task.description
    return update_task(task_id, TaskUpdate(title=original_title, description=original_description))
```

Add the route in `api/tasks.py`:

```python
@router.post("/{task_id}/revert-rewrite", response_model=TaskItem)
def revert_task_rewrite_endpoint(task_id: UUID) -> TaskItem:
    try:
        return revert_task_rewrite(task_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
```

**Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_tasks_module.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/modules/tasks.py backend/app/api/tasks.py backend/tests/test_tasks_module.py
git commit -m "feat(tasks): add revert-rewrite endpoint"
```

### Task 3.5: Fuzzy due-date control + expandable row (frontend)

**Files:**
- Modify: `frontend/src/lib/api.ts` (`TaskItem`, `TaskCreate`/payload types, `revertTaskRewrite`)
- Modify: `frontend/src/pages/TasksPage.tsx`

**Step 1: Extend the API client**

Add `due_window`, `original_title`, `original_description`, `rewrite_status` to the `TaskItem` type. Add `due_window` to the create payload. Add `revertTaskRewrite(id)` POSTing `/modules/tasks/{id}/revert-rewrite` (model on existing task calls).

**Step 2: Due-window control in the capture box**

In the `NewTaskComposer` area (around `TasksPage.tsx:248`, where `dueDate` is wired), replace the bare date button with a small segmented/popover control: **This week** (default) / **This month** / **Someday** / **Pick a date…**. Selecting "Pick a date…" reveals the existing `<input type="date">` and sets `due_window='exact'`. Pass `due_window` (and `due_date` only when exact) into `createTask`. Default state = `this_week`.

**Step 3: Render due label from window**

Update the row's `dueLabel` (around line 502) to render from `due_window`: `this_week` → "This week", `this_month` → "This month", `someday` → no label, `exact` → the date (keep the "today" special case).

**Step 4: Expandable row**

Make each task row an accordion: the collapsed state shows the (possibly rewritten) `title` on one truncated line. A chevron/click expands to show the full `description` body. When `rewrite_status === 'complete'` and `original_title !== title`, show a subtle "rewritten" marker with a "revert" action calling `revertTaskRewrite(task.id)` then refreshing the list. Reuse existing motion/accordion patterns from the plans components if helpful.

**Step 5: Verify**

Run: `cd frontend && npm run build`
Expected: build succeeds.

**Step 6: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/pages/TasksPage.tsx
git commit -m "feat(tasks): fuzzy due-window control, expandable rows, and rewrite revert"
```

---

## Phase 4 — Curious: "what we'll write about you" preview

### Task 4.1: Build the grouped preview server-side

**Files:**
- Modify: `backend/app/modules/curious.py` (`CuriousCompletion` + `complete_onboarding_session`, and `CuriousWeaveResult` if surfacing on weave)
- Test: `backend/tests/test_curious_module.py`

**Step 1: Write the failing test**

```python
def test_completion_returns_user_model_preview(tmp_path):
    # Follow the existing onboarding-flow test setup in this file:
    # answer the onboarding questions, then complete the session.
    # Assert the completion exposes a non-empty preview grouped by bucket.
    ...
    assert completion.preview  # list of {bucket_name, lines: [...]}
    assert all(group["lines"] for group in completion.preview)
```

(Read `tests/test_curious_module.py` for the existing onboarding answer/complete helper and reuse it verbatim.)

**Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_curious_module.py::test_completion_returns_user_model_preview -v`
Expected: FAIL (`preview` missing).

**Step 3: Implement**

- Add `preview: list[CuriousPreviewGroup]` to `CuriousCompletion`, where:

```python
class CuriousPreviewGroup(BaseModel):
    target_bucket_key: str
    target_bucket_name: str
    lines: list[str]
```

- Add a builder that groups the session's `CuriousAnswerSummary` items (already available via `_state_for_session(session_id).answers` / `_answers_for_session`) by `target_bucket_key`, collecting each answer's `bucket_update_text` into `lines`:

```python
def _build_user_model_preview(answers: list[CuriousAnswerSummary]) -> list[CuriousPreviewGroup]:
    groups: dict[str, CuriousPreviewGroup] = {}
    for a in answers:
        g = groups.setdefault(
            a.target_bucket_key,
            CuriousPreviewGroup(target_bucket_key=a.target_bucket_key,
                                target_bucket_name=a.target_bucket_name, lines=[]),
        )
        if a.bucket_update_text not in g.lines:
            g.lines.append(a.bucket_update_text)
    return list(groups.values())
```

- In `complete_onboarding_session`, populate `preview=_build_user_model_preview(...)` on the returned `CuriousCompletion`. (LLM smoothing is optional and out of scope for this task — raw grouped lines satisfy the requirement.)

**Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_curious_module.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/modules/curious.py backend/tests/test_curious_module.py
git commit -m "feat(curious): include a user-model preview on completion"
```

### Task 4.2: Show the preview on completion (frontend)

**Files:**
- Modify: `frontend/src/lib/api.ts` (`CuriousCompletion` type)
- Modify: `frontend/src/pages/CuriousPage.tsx`

**Step 1: Extend the API type**

Add `preview: Array<{ target_bucket_key: string; target_bucket_name: string; lines: string[] }>` to the completion type.

**Step 2: Render it on the completion screen**

In `CuriousPage.tsx`, on the completion/summary view, render a "What I'll add to your user model" section: one block per preview group (bucket name heading + bulleted `lines`). Place it near the existing completion summary.

**Step 3: Verify**

Run: `cd frontend && npm run build`
Expected: build succeeds.

**Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/pages/CuriousPage.tsx
git commit -m "feat(curious): show user-model preview on completion"
```

---

## Final verification

After all phases:

```bash
cd backend && python -m pytest -q
cd ../frontend && npm run build
```

Expected: backend suite green; frontend build clean.

Then use superpowers:requesting-code-review before merging.
