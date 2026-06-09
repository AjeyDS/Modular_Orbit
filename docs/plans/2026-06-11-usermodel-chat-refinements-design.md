# User-Model & Chat Refinements (Round 3) — Design

Date: 2026-06-11
Status: Approved, ready for implementation planning

## Summary

Three related refinements found while testing the companion + goals work:

- **A. Scrap the `goals` Story Bucket.** Goals are now first-class in the Goals
  module/table; a parallel `goals` Story Bucket is redundant and complicates
  bucket selection. Remove it; goal-*aligned* facts route to thematic buckets.
- **B. Companion recent-activity context.** The companion can't reference recent
  things done across the app (documents added, resume updated, goals, logs). Add
  a recency feed of recent Life Items + goals to its context.
- **C. Structured query tool in Understanding Chat.** Understanding Chat answers
  everything through fuzzy chunk RAG; it can't answer exact-state questions
  ("what's overdue?", "plan progress?", "my short-term goals?", "did I do my
  routine today?"). Add orchestrated per-module structured retrieval.

(Issue already fixed inline before this round: companion quick-reply chips now
render in the person's voice, not as follow-up questions — commit `ab3067a`.)

## Decisions locked during brainstorming

- **Goals bucket is removed**, not hidden: dropped from `KNOWN_BUCKET_KEYS` and
  `DEFAULT_STORY_BUCKETS`; the existing (empty) row is **archived**
  (non-destructive). Everything reads *active* buckets, so the rest ripples
  automatically. Goal-aligned facts go to thematic buckets (career, aspirations…).
- **Companion recency** = recent Life Items across modules (logs, tasks, plans,
  documents, routine), excluding internal curious scaffolding
  (`curious_session`/`curious_question`), plus recent goals.
- **Structured query = orchestrated**, no LLM function-calling. The existing
  router (`_route_and_classify`) gains a `modules` field — **no extra LLM call**.
  Queryable modules: **tasks, plans, goals, routines**. Documents stay RAG-only;
  logs deferred.
- **Fast chat mode is unchanged** (pure chunk RAG).

## Current state (context)

- `KNOWN_BUCKET_KEYS` lives in `app/lifecycle/bucket_keys.py` (8 keys incl.
  `goals`). `ALLOWED_KEYS_LINE` derives from it.
- `DEFAULT_STORY_BUCKETS` in `app/user_model/story_buckets.py` seeds a `goals`
  bucket (`stable_key="goals"`). Live DB: that bucket is empty (34 chars), 0
  bucket updates. No Curious question targets `goals`.
- `build_companion_context` (`app/modules/companion.py`) reads story buckets,
  goals, active tasks/plans, asked-coverage — no recency, no documents/logs.
- `_route_and_classify` / `RouteDecision` (`app/chat/actions.py`) returns
  breadth + buckets + expansion_terms. `_build_answer_context` (understanding)
  assembles chunks + connections + selected buckets + goals; `respond_to_chat_stream`
  mirrors it with stage events.
- Reusable services: `list_tasks(status=, limit=)` (TaskItem: due_date,
  priority, module_status), `list_plans(status=)` (PlanItem: progress_percent,
  completed_steps, total_steps), `list_goals()` (status, horizon, target_date,
  target_note), `list_routine_state()` (RoutineState: items with streak_count +
  today's completion).

## Architecture

### A. Remove the `goals` Story Bucket

- `bucket_keys.py`: remove `"goals"` from `KNOWN_BUCKET_KEYS` (→ 7).
  `ALLOWED_KEYS_LINE` updates automatically.
- `story_buckets.py`: remove the `goals` `StoryBucketSeed`; in
  `ensure_story_buckets`, after seeding, archive any active legacy goals bucket:
  `UPDATE story_buckets SET status='archived', updated_at=now() WHERE stable_key='goals' AND status='active'`.
- Automatic ripples (no edits): connection-review bucket candidates, the chat
  router's `_bucket_catalog`, companion/document/synthesis routing, and the User
  Model page (renders active buckets) all stop seeing `goals`.
- `normalize_bucket_key("goals")` now returns `None` (correctly drops stray
  goal-bucket routing).

### B. Companion recent-activity context

- Extend `build_companion_context`: add a **"Recent activity"** section — the
  most recent ~12 rows from `life_items` joined to `module_instances`/`modules`
  where `module_id IN ('logs','tasks','plans','documents','routine')` and
  `item_type NOT IN ('curious_session','curious_question')` and
  `lifecycle_status <> 'deleted'`, ordered by `created_at DESC`. Each line:
  `- [module] title` (documents append their `category_tag`/summary if cheap).
- Recent goals already come from `list_goals()`; keep them. Respect the existing
  2000-char cap (recency section truncated last).

### C. Structured query tool in Understanding Chat

- **Router:** add `modules: list[str]` to `RouteDecision` and the
  `_route_and_classify` JSON output. Prompt: "Also list which modules this query
  needs exact state from: tasks, plans, goals, routines — or [] if none."
  Clamp to the known set. **Lexical fallback** (LLM down): keyword detection —
  `due|overdue|task|todo` → tasks; `plan|progress|step|milestone` → plans;
  `goal|aspire|aiming` → goals; `routine|habit|streak|daily` → routines.
- **Retrievers** (`app/chat/actions.py`, reuse services):
  - `_structured_tasks_context()`: `list_tasks(status="active", limit=10)` →
    lines `- {title} — due {due_date}, priority {priority}, {module_status}`
    (sort soonest/overdue first; None due last).
  - `_structured_plans_context()`: `list_plans(status="active")` →
    `- {title} — {completed_steps}/{total_steps} steps ({progress_percent}%)`.
  - `_structured_goals_context()`: `list_goals()` →
    `- {status}/{horizon}: {title}{ — target …}`.
  - `_structured_routines_context()`: `list_routine_state()` →
    `- {title} — streak {streak_count}, today: {done|not done}`.
  - Each returns "" when empty; wrap in try/except → "".
- **Integration:** in `_build_answer_context` (understanding path) and
  `respond_to_chat_stream`, after routing, build a **"Structured data"** section
  from the selected modules' retrievers and inject alongside chunks/connections/
  selected buckets/goals. Streaming emits a `{"stage":"checking_state"}` event
  (label "Checking your tasks, plans & goals") before `writing` when any module
  was selected.
- **Fast mode:** unchanged.

### Error handling

- Router fallback is lexical and deterministic; structured retrievers are plain
  service calls wrapped to degrade to "" on error. The pipeline still answers
  with the LLM stubbed.
- Archiving the goals bucket is idempotent (`WHERE stable_key='goals' AND
  status='active'`).

### Testing

- **A:** `KNOWN_BUCKET_KEYS` has 7 keys, no `goals`; `normalize_bucket_key("goals")
  is None`; `ensure_story_buckets` archives the existing goals bucket and leaves
  7 active; existing companion/chat/curious tests still pass.
- **B:** with a recent document + log present, `build_companion_context` includes
  their titles under "Recent activity"; `curious_session`/`curious_question`
  excluded.
- **C:** router returns `modules` (LLM-stubbed → lexical picks tasks for "what's
  overdue", routines for "did I do my routine"); each retriever returns expected
  lines from seeded data; understanding context includes the structured block
  when modules are selected and omits it when none; **Fast mode never calls the
  structured retrievers** (assert call counts).

## Out of scope (deferred)

- Documents and logs as structured-query modules (documents stay RAG-only).
- True LLM function-calling / agentic multi-hop tool use.
- Onboarding-defined bucket structure; reviewed size-triggered bucket splitting.
