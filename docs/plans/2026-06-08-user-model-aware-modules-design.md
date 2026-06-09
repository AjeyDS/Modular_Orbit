# User-Model-Aware Modules — Design

Date: 2026-06-08
Status: Approved, ready for implementation planning

## Summary

Six related features that make Orbit's modules *user-model-aware* and make the
user model itself *visible*. Most of the plumbing already exists (Connection
Review, Story Buckets, bucket updates, the priority advisor's LLM pattern); this
work mostly **surfaces**, **enriches**, and **refactors** it.

Delivered as one design, built in four independently-shippable phases.

### Decisions locked during brainstorming

- **Document tags:** free-form, LLM-generated. No folder taxonomy yet (deferred).
- **Task rewrite:** auto-rewrite on create, keep the original, one-click revert.
- **User Model module:** relocate the existing bucket editor into its own
  top-level module. Live activity feed / pending-review queue deferred.
- **Delivery:** one combined design, phased plan.

### Confirmed defaults

1. Task due-window default is **`this_week`**; the "no date" option is `someday`.
2. Task auto-rewrite runs **synchronously inline** on create (like the existing
   Connection Review), accepting a brief settle delay. Background deferral is a
   later optimization.
3. Phase 1 **removes** the User Model tab from Settings (no duplicate editor);
   a one-line pointer replaces it.

## Existing building blocks (context)

- `backend/app/modules/tasks.py` — Task = Life Item + `task_items` side table;
  `due_date` is a plain `date`. Already has an LLM priority advisor with a
  deterministic fallback and a user-model context summary
  (`_task_priority_context_summary`).
- `backend/app/modules/documents.py` — single-file upload, auto `unique_name`,
  chunking, inline Connection Review. No tag or human-readable connection note.
- `backend/app/lifecycle/connection_review.py` — deterministic lexical matching
  that already writes `connection_note` and pending `bucket_updates`.
- `backend/app/lifecycle/story_weave.py` (`weave_story_bucket`) — folds pending
  bucket updates into a Story Bucket's markdown.
- `backend/app/user_model/story_buckets.py` — the eight Story Buckets are the
  user model; editable markdown persisted in Postgres.
- `backend/app/modules/curious.py` — answers → `bucket_update_text` →
  woven into Story Buckets; completion currently returns raw answers only.
- Frontend: `pages/SettingsPage.tsx` hosts the bucket editor as a tab;
  `pages/TasksPage.tsx` uses a bare `<input type="date">`;
  `pages/DocumentsPage.tsx` lists files with no annotation;
  `layout/moduleOrder.ts` defines nav order.

---

## Phase 1 — User Model as a top-level module

**Goal:** the user model is visible and reachable, not buried two steps into
Settings.

- Extract the bucket-editor UI (currently `UserModelTab` in
  `pages/SettingsPage.tsx`) into `pages/UserModelPage.tsx`, mounted at
  `/user-model` in `App.tsx`.
- Add `user_model` to `DEFAULT_ORDER` in `layout/moduleOrder.ts` and a sidebar
  entry in `layout/Sidebar.tsx`.
- Remove the `user-model` tab from `SettingsPage`; replace with a one-line
  pointer ("The User Model now lives in its own module").
- No backend change — `/user-model/buckets` endpoints already exist.

**Data flow:** unchanged. Pure relocation + navigation.

**Testing:** the page renders the same buckets; edits still hit
`updateStoryBucket`; Settings no longer renders the editor; nav shows the new
module.

---

## Phase 2 — Documents: category tag + connection sentence

**Goal:** every ingested document gets a free-form category tag and a sentence
explaining how it connects to the user; both editable; multi-file sequential
upload; the connection context reaches the right user-model bucket immediately.

### Data
Add to the `document_items` side table and `DocumentItem`:
- `category_tag text` — free-form LLM tag.
- `connection_summary text` — one sentence on how the doc connects to the user.
- `tag_status text` — `pending` | `complete` | `failed`.

### Ingestion
After text extraction + chunking, one small `generate_json` call (mirroring the
priority advisor: typed, low temperature, deterministic fallback when
`LLM_MODE` is stub/unavailable) takes the document text + user-model context
(Story Buckets + goals) and returns `{category_tag, connection_summary}`.
Fallback when the LLM is unavailable: tag = `uncategorized`, summary derived
from the existing document summary.

### Display & editing
- Under each row in `DocumentsPage`, render the tag as a chip and the
  connection sentence as muted text.
- Both inline-editable. New endpoint `PATCH /modules/documents/{id}/annotation`
  with `{category_tag?, connection_summary?}` persisting to `document_items`
  and `life_items.payload`.

### Multi-file upload
- The Add Document dialog accepts multiple files and uploads them
  **sequentially** (one existing `/upload` request each), with per-file
  progress rows (queued / uploading / done / error). Backend `/upload` stays
  single-file.

### Immediate user-model update
- After each document's inline Connection Review writes its pending
  `bucket_updates`, auto-run `weave_story_bucket` for the affected bucket(s),
  using `connection_summary` as the update text — so the context lands in the
  correct bucket immediately rather than waiting for a manual weave.

**Testing:** upload produces tag + summary; annotation edit persists; multiple
files process one at a time; affected bucket content reflects the new summary
after upload; LLM-down path uses the fallback without erroring.

---

## Phase 3 — Tasks: fuzzy due date + auto-rewrite + expandable row

**Goal:** vague-by-default dates with an exact-date escape hatch; tasks
reorganized through the user model with a clean AI title; long tasks expand
instead of bloating the list.

### Fuzzy due date
- Add `due_window text` to `task_items`: `this_week` | `this_month` |
  `someday` | `exact`, **default `this_week`**. Keep `due_date` for `exact`.
- `TaskCreate`/`TaskUpdate`/`TaskItem` carry `due_window`.
- Effective-date derivation for sorting/overdue: `this_week` → end of current
  week, `this_month` → end of month, `someday` → none, `exact` → `due_date`.
  Reuse in `_fallback_task_sort_key`.
- UI: capture box shows a "This week ▾" control (This week / This month /
  Someday / Pick a date…). Choosing a date sets `due_window='exact'` and
  `due_date`.

### Auto-rewrite, keep original
- On `create_task`, after the Life Item is created, an LLM pass using
  user-model context (Story Buckets + goals, same summary as the priority
  advisor) returns a clean `title` and an organized body.
- Store the rewritten `title`/`description`; preserve the typed original in
  `payload` (`original_title`, `original_description`). Add `rewrite_status`.
- Deterministic fallback = no rewrite (keep typed text).
- Inline/synchronous, like Connection Review. The task appears instantly with
  the typed title (optimistic), then settles to the rewritten title with a
  subtle "rewritten" marker and a one-click revert.

### Expandable row
- The list shows the AI title on one clean, truncated line.
- Clicking expands an accordion with the full organized body + the revert
  affordance. Long tasks no longer blow out the list.

**Testing:** new task defaults to `this_week`; picking a date flips to `exact`;
sort/overdue uses effective date; create yields a rewritten title with original
preserved; revert restores the original; LLM-down path keeps typed text; long
task expands/collapses.

---

## Phase 4 — Curious: "what we'll write about you" preview

**Goal:** when an answer set completes, show the user what is about to be
written to their user model.

- At onboarding completion and in the pending-weave flow, build a preview
  grouped by Story Bucket: each bucket name with the bullet list of
  `bucket_update_text` it is about to receive (these already exist per answer in
  `CuriousAnswerSummary`).
- Optional single LLM call to smooth the grouped bullets into a short paragraph;
  fall back to the raw grouped list.
- Surface via a new `preview` field on `CuriousCompletion` (and/or the weave
  result), rendered on the completion screen in `CuriousPage`.

**Testing:** completing a set returns a non-empty, bucket-grouped preview that
matches the answers given; LLM-down path shows the raw grouped list.

---

## Cross-cutting notes

- **LLM pattern:** every new model call follows the existing typed
  `generate_json` + deterministic-fallback pattern. No single large prompt.
- **Schema changes:** new columns on `task_items` and `document_items`. Follow
  the project's existing schema/bootstrap approach; do not implicitly reset the
  database.
- **Lifecycle integrity:** all writes continue to go through the shared Life
  Item service and Connection Review; new features enrich, they do not bypass.

## Deferred (explicitly out of scope now)

- Document folder structure / stable tag taxonomy.
- User Model live activity feed and pending-review queue.
- Background (async) execution of task rewrite and doc annotation.
- **Chat module structured querying / LLM tool-use.** Today chat
  (`backend/app/chat/actions.py`) has no tool-calling: `_build_answer_context`
  pre-assembles context (vector chunks, connections, story buckets, goals, and a
  lexical scan of recent `life_items` in `_module_tool_context`) into one
  `generate_text` call. It reads only base `life_items` (title/description/
  payload), not side tables, so task `due_window`, plan step progress, and the
  new document `category_tag`/`connection_summary` won't surface in chat unless
  mirrored into `payload`. A future design should either add real
  function-calling so the model can query modules on demand (e.g. "overdue
  tasks") or wire dedicated structured-retrieval helpers into
  `_build_answer_context`. To be designed separately, after the four phases land.
