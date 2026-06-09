# Goals Capture, Document Enrichment & Log Deletion — Design

Date: 2026-06-10
Status: Approved, ready for implementation planning

## Summary

Three related user-model improvements, surfaced after testing the companion:

1. **Goals capture** — today there is *no way to create a goal*. `goals.md` is
   empty (just `## Active` / `## Tentative` headers), there are no goal
   create/edit endpoints, and no Goals UI. Goals only exist as connection
   *targets*. Add first-class goal management **and** casual proposal capture.
2. **Documents → user model** — uploaded documents never enrich Story Buckets
   (0 document-sourced bucket updates; all document connections are
   `target_type = life_item`). Route a document's *life-relevant content* to
   Story Buckets selectively. Pure-reference documents leave no new trace.
3. **Log deletion** — logs are undeletable; `remove_log`/`archive_log` exist in
   the service but are not exposed via API or UI.

Plus a small **shared refactor**: extract the bucket-key normalization helper
(built for the companion) so document enrichment reuses it.

Deferred to a separate brainstorm: onboarding-defined bucket structure and
reviewed size-triggered bucket splitting.

## Evidence from live debugging (why these are needed)

- **Goals live in a Postgres `goals` table** (columns: `id`, `goal_id` unique
  slug, `title`, `body`, `status` CHECK active|tentative, `position`,
  timestamps). `goals.md` is only a one-time legacy seed source. The table is
  empty (only the seed ran, with nothing to seed). `app/user_model/goals.py`
  exposes `list_goals` / `promote_goal` / `ensure_goals_seed` — no
  create/update/delete. No goal routes in `app/api/user_model.py`. No goals UI.
- Live DB: 6 documents, all `bucket_update_status = not_needed`, **0**
  document-sourced `bucket_updates`; 16 document connections, all
  `target_type = life_item`.
- **Root cause (documents):** Connection Review scores candidates with crude
  lexical overlap `len(overlap) / |item_tokens|` (`_lexical_score`,
  `connection_review.py`). A document's text is large and domain-specific, so
  overlap with short bucket descriptions ("Career", "Health") falls below
  `CONNECTION_THRESHOLD = 0.18` → no `story_bucket` connection →
  `_should_create_bucket_update` is always false. The existing
  `_set_document_bucket_update_text` / `_auto_weave_connected_buckets` in
  `documents.py` are effectively dead because no bucket connection forms.
- `app/api/logs.py` exposes only `POST` (create) and `GET` (list).

## Decisions locked during brainstorming

- **Goals are first-class in BOTH ways:** a full Goals management page AND casual
  proposal capture from **Companion + Logs + Chat**.
- **Goal storage:** the Postgres `goals` table (runtime source of truth;
  `goals.md` is legacy seed only). CRUD is plain SQL; `goal_id` is a stable slug
  generated from the title, preserved across edits (connections point at it).
- **Casually-proposed goals default to `Tentative`** (manual promotion rule).
- **Document enrichment is selective and content-based, not lexical-connection-
  based.** Reuse the companion pattern: an LLM step routes a document's meaning
  to 1–3 stable bucket keys; write pending bucket updates; weave. Do NOT touch
  the lexical connection-review scoring.
- **Document *activity* gets no new trace.** Substantive *content* reaches
  buckets; everything else stays visible via the Documents page + RAG. No
  per-upload activity logs, no activity lines in buckets (avoids narrative
  pollution).
- **Logs become deletable + archivable** via new endpoints and row actions.
- **Shared refactor:** extract `normalize_bucket_key` + the allowed-keys prompt
  line into `app/lifecycle/bucket_keys.py`; companion and documents both import
  it.

## Architecture

### 1. Goals

**Storage / service** (`app/user_model/goals.py`, on the `goals` table):
- New functions: `create_goal(title, body, status="tentative") -> GoalEntry`
  (slugifies title → stable `goal_id`; numeric suffix on slug collision;
  `position` = max(position)+1 within the status), `update_goal(goal_id, *,
  title=None, body=None)`, `delete_goal(goal_id)`. Existing `promote_goal`
  (Tentative→Active) and `list_goals` stay. All plain SQL on the `goals` table;
  `goal_id` is immutable across edits so connections never break.

**API** (`app/api/user_model.py`):
- `GET /user-model/goals` (list), `POST /user-model/goals` (create),
  `PATCH /user-model/goals/{goal_id}` (edit),
  `POST /user-model/goals/{goal_id}/promote`,
  `DELETE /user-model/goals/{goal_id}`.

**Goals page (frontend):** lists Active + Tentative; add (title + reason), edit,
promote, delete. Stable-ID-safe; optimistic updates.

**Casual capture (Companion + Logs + Chat):**
- Extend the Capture Proposal system in `app/chat/actions.py`: add `"goals"` to
  `DetectedProposal.module_id` and the detection prompt. Goal-shaped intent = a
  durable aspiration/direction ("I want to…", "my goal is…", "I'm trying to
  build…"), distinct from a task (actionable) or plan (multi-step).
- A confirmed goal proposal → `create_goal(..., status="tentative")`.
- Companion proposes a goal inline when conversation surfaces goal-shaped intent
  (reuse the same preview/confirm contract).

**Connection (free win):** once goals exist in `goals.md`, Connection Review
already lists them as candidates, so items begin linking to goals automatically.

### 2. Document enrichment

- Extract `normalize_bucket_key` + `ALLOWED_KEYS_LINE` into
  `app/lifecycle/bucket_keys.py` (from `companion.py`). Companion imports from
  there.
- Extend `_annotate_document` (already an LLM call in `documents.py`) — or add a
  dedicated routing call — to also return **`bucket_keys: [..]` (0–3 stable
  keys)** for the document's life-relevant meaning, using `ALLOWED_KEYS_LINE` and
  `normalize_bucket_key`. Returning `[]` means "reference only — no enrichment."
- After ingestion (when `bucket_keys` is non-empty): for each key, write a
  **pending `bucket_updates` row** (`source_event.source = "documents"`,
  `life_item_id` = the document) using `connection_summary` as the fact text;
  set the document's `bucket_update_status = complete`; then weave the affected
  buckets (reuse `_auto_weave_connected_buckets` or call `weave_story_bucket`).
- Keep the lexical item↔item connection review unchanged.
- Replace the dead reliance on a story_bucket *connection* for bucket updates.

### 3. Log deletion

- `app/api/logs.py`: add `DELETE /logs/{log_id}` (→ `remove_log`) returning 204,
  and `POST /logs/{log_id}/archive` (→ `archive_log`) returning the updated item.
- `LogsPage.tsx`: row delete (confirm) + archive actions; client fns in
  `api.ts`. This also clears the stuck `pending` companion log.

### Error handling

- All new LLM calls wrapped in `try/except (LLMUnavailable, Exception)` with
  deterministic fallbacks. Document routing failure → treat as `[]` (no
  enrichment; document still ingested + chunked).
- Goal CRUD: slug collisions get a numeric suffix; `goal_id` immutable across
  edits; delete/update of a missing ID raises → 404 at the API.
- Goal proposal detection guarded like other Capture Proposals (explicit always
  works; suggested suppressed on questions/lookups per the existing guard).

### Testing

- **Goals service:** create → row with a stable `goal_id` and correct status;
  update preserves `goal_id`; promote moves Tentative→Active; delete removes only
  the target; slug collision suffixing.
- **Goals API:** full CRUD + promote happy paths and 404s.
- **Goal proposal detection:** explicit "add as goal" + suggested goal intent →
  `module_id="goals"`, defaults to tentative; LLM-down fallback; questions
  suppressed.
- **Document enrichment:** a life-relevant document (stubbed routing → e.g.
  `["career"]`) writes a pending `documents` bucket update and weaves; a
  reference document (routing → `[]`) writes none; invented/cased keys
  normalized or dropped; LLM-down → no enrichment, document still created.
- **Log deletion:** DELETE removes the log (404 when missing); archive flips
  lifecycle_status.
- **Shared helper:** `normalize_bucket_key` unit tests (display name, casing,
  invented key) live with the extracted module; companion tests still pass.

## Out of scope (deferred)

- Onboarding-defined bucket structure (which `.md` files exist).
- Reviewed, size-triggered bucket splitting/weaving into logical separations.
- Improving Connection Review's lexical scoring / semantic candidate matching.
- Per-upload document activity logs (decided against — Documents page + RAG
  already cover visibility).
