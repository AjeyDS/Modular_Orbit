# Single Woven User Model — Design

Date: 2026-06-15
Status: Approved, ready for implementation planning

## Summary

Today the User Model is **7 Story Buckets** (`who_am_i`, `interests_and_works`,
`career`, `health`, `relationships`, `habits`, `aspirations`) stored in Postgres
(`story_buckets.content`). At runtime, `build_companion_context()` reads all
buckets, **truncates each to 400 chars**, concatenates them, and caps the result
at a 2000-char budget. The feed is therefore a lossy, mechanical stitch — not a
coherent picture of the person.

Replace this with a **raw-capture → woven-narrative** model:

- A single append-only **fact stream** (`user_facts`) captures observations from
  companion answers, life-item events, and manual notes.
- A **weave** step synthesizes the stream into **one** living narrative document
  (`user_model_weave.content`) using a fixed section template.
- The model is fed, **every time**, the woven doc **plus a short unwoven tail**
  of the newest facts. Feeding is every-turn; weaving is triggered.

The `.md` is assembled on demand from Postgres and is **never written to git**.
(The legacy `user_model/*.md` files have been removed from git history and
gitignored as part of this work.)

## Decisions locked

- **Source of truth:** raw `user_facts` stream → woven narrative. The woven doc
  is generated, not hand-edited.
- **Capture sources:** `companion`, `life_item`, `manual` — all through one
  `capture_fact()` helper. **Capture-all**: every life-item event becomes a
  fact; the weave does the summarizing (keeps the hook dumb).
- **Weave trigger:** unwoven-tail **size threshold** (~8 facts or ~1500 chars).
- **Weave execution:** **background task** (capture never blocks the user
  action that tipped the threshold), modeled on `lifecycle/connection_review`.
- **Doc structure:** **fixed section template** (below).
- **Manual edits:** a direct edit becomes a **high-salience `manual` fact**, not
  an in-place doc edit. The next weave folds it in. No "user edit lock" on the
  doc itself.
- **Storage:** Postgres for both stream and woven doc. `.md` exported on demand.

## Section template (fixed)

The weave always emits these sections; durable identity at the bottom stays
stable, the freshest layer (`Top of Mind`) at the top of the "current" block:

```
# Identity            — stable: who you are, origin, values, hard constraints
# Work & Career       — work context
# Personal Life       — family, relationships, community, health
# Top of Mind         — active threads right now (freshest layer)
# Brief History
  ## Recent           — recent months
  ## Earlier
  ## Long-term background
```

`Identity` is preserved verbatim across weaves unless a fact directly revises it,
so durable self-knowledge never gets churned out.

## Data model (Postgres)

### `user_facts` — raw capture stream (append-only)

| column | purpose |
|---|---|
| `id`, `created_at` | identity / ordering |
| `source` | `companion` \| `life_item` \| `manual` \| `import` |
| `text` | the raw observation, as captured |
| `ref` | optional: `life_item_id` + kind, for trace + retract on delete |
| `salience` | `normal` \| `high` (manual edits land `high`) |
| `woven` (bool), `woven_at` | folded into the narrative yet? |

### `user_model_weave` — the woven doc (current + history)

| column | purpose |
|---|---|
| `content` | full woven markdown (the "one `.md`") |
| `version`, `woven_at` | each weave writes a new version (rollback + audit) |
| `fact_count_at_weave` | how much raw material this version reflects |

## Capture

Single helper `capture_fact(source, text, *, ref=None, salience='normal')`
appends to `user_facts`. Three feeders:

- **companion** — companion answer handling appends the answer as a fact
  (replaces the current bucket-update path).
- **life_item** — **one hook** in `lifecycle/life_items.py` on
  `create_life_item` / `update_life_item` / `delete_life_item`. Every task,
  plan, document, definition, connection emits a fact (`ref` = item id + kind).
  Deletes append a retraction fact.
- **manual** — a "add a note" / direct-edit action appends a `high`-salience
  fact.

## Feed (every time)

New `build_user_model_context()` replaces the per-bucket truncation in
`companion.py` and the other `chat/` context builders:

```
<woven user_model.md — full, or trimmed to a token budget>

## Recently (not yet woven)
- [task] Added: finish Home Credit writeup        (2h ago)
- [companion] Prefers DE roles in fintech         (5h ago)
```

Woven doc = stable narrative. Tail = newest unwoven facts, capped. Cheap to
assemble, always current.

## Weave (triggered, background)

After `capture_fact()`, check the unwoven-tail budget. On crossing the threshold,
enqueue a **background** weave:

- **Input:** current woven doc + all unwoven facts.
- **Prompt:** "Fold these new observations into the life narrative. Keep the
  fixed sections. Preserve Identity verbatim unless a fact directly revises it.
  Demote aging Top-of-Mind items into Recent → Earlier as they cool. Honor
  high-salience facts. Stay under {budget}. Output the full updated document."
- **Output:** new `user_model_weave` version; mark folded facts `woven=true`.

A manual **"re-weave now"** action triggers the same path on demand.

## Migration

1. **Seed the woven doc:** one-time weave of the current 7 buckets' content into
   the initial narrative (maps `who_am_i`→Identity, `career`→Work, etc.).
2. **Seed the stream (optional):** import existing logs and bucket bodies as
   historical `import` facts, marked `woven=true`.
3. **Keep `story_buckets` table** read-only during transition for rollback, then
   deprecate once the woven model is trusted.

## Code touchpoints

- `lifecycle/life_items.py` — add capture hook to create/update/delete.
- `modules/companion.py` — answers append facts; `build_companion_context()` →
  `build_user_model_context()`; question generation reads woven doc for coverage
  gaps instead of per-bucket coverage.
- `chat/` context builders — feed woven doc + tail.
- New `user_model/facts.py` + `user_model/weave.py` (capture, threshold check,
  weave prompt, version write).
- New API + settings UI: view woven doc, view recent facts, add note, re-weave.
- DB migration: `user_facts`, `user_model_weave` tables.

## Testing

- Capture: each source appends a well-formed fact; life-item delete retracts.
- Threshold: weave fires at budget, not before; runs in background; marks facts
  woven; writes a new version.
- Feed: returns woven doc + capped tail; first-run (empty) degrades gracefully.
- Weave prompt: Identity preserved across a weave that doesn't revise it;
  high-salience facts always reflected.
- Migration: 7 buckets produce a sensible initial woven doc.

## Reconciliation with existing machinery

This is an **evolution** of machinery that already exists, not greenfield:

- `bucket_updates` (`lifecycle/derived.py::write_bucket_updates`) already turns
  life-item events into per-bucket pending "facts" via Connection Review. Our
  `user_facts` stream generalizes this into one unified, source-tagged stream.
- `lifecycle/story_weave.py::weave_story_bucket()` already weaves pending
  `bucket_updates` into a bucket's `content` — but it is a **deterministic v0**
  that *appends bullet markdown* per bucket (no LLM synthesis), gated by a 7-day
  User Edit Lock, triggered inline or via `POST /api/story-weave/...`. Our
  `weave_user_model()` replaces this with **one LLM-synthesized document**.
- Execution today is **inline/synchronous** (`process_lifecycle_for_item`); there
  is no background worker. "Background weave" is therefore a *new* capability —
  see the execution note below.
- `capture_proposals` (chat → previewed life items) is a separate concern and is
  **unaffected**.

**Build-vs-reuse decision:** add new `user_facts` + `user_model_weave` tables and
a new LLM `weave_user_model()`. Leave the legacy per-bucket `bucket_updates` /
`story_weave` path in place but **unwired** from the feed (a later task removes
it once the woven model is trusted). This avoids entangling the new single-doc
weave with the old bullet-append logic.

**Background execution note:** since there is no worker, v1 runs the threshold
weave via FastAPI `BackgroundTasks` (fire-and-forget after the request that
tipped the threshold). The weave function is idempotent and safe to also call
from a manual "re-weave now" endpoint and from a future scheduler.

**LLM-in-tests note:** `llm_enabled()` is `False` under pytest, so
`weave_user_model()` must fall back to a deterministic synthesis (append facts
under their sections) when `LLMUnavailable` is raised. Tests assert on threshold
firing, fact `woven` marking, version creation, and feed assembly — never on LLM
prose.

## Out of scope (deferred)

- Splitting the single file back into multiple files (explicitly future).
- Per-fact embeddings / semantic retrieval over the stream.
- Conflict resolution UI when a new fact contradicts the narrative.
