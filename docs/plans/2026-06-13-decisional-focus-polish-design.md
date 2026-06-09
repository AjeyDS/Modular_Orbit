# Decisional Focus, Field Cleanup & Cache Headers (Round 5) — Design

Date: 2026-06-13
Status: Approved, ready for implementation planning

## Summary

Three fixes found after rounds 3–4 shipped:

1. **#1 Decisional focus.** "What should I focus on today?" *describes* one task
   instead of *prioritizing* across everything. Make focus/priority queries rank
   active tasks/plans/routines by urgency (due date), priority, and goal-fit, and
   recommend an ordered short list.
2. **#2 Field-leak cleanup.** Answers echo raw field labels verbatim ("admission
   expiring on 'Admit Until Date: D/S'"). Nudge the prompt to render values in
   plain language or omit unclear codes.
3. **#3 Cache headers (real cause of the "missing" Sources footer).** The Sources
   feature works end-to-end; `nginx.conf` sets no cache headers, so the browser
   serves a stale cached `index.html` pointing at the old JS bundle. Add proper
   cache-control so rebuilds always reach the browser.

## Evidence

- **#1:** the lexical module fallback in `_route_and_classify` keys off words like
  `task/plan/goal/routine`. "what should I focus on today" contains none →
  `modules = []` → no "Structured data" block → the model can only describe. Even
  when a task surfaces via buckets, there's no ranking instruction.
- **#3:** live `done` events carry `sources` (understanding returned documents +
  buckets + "Tasks"); the freshly built frontend bundle contains `SourcesStrip`
  and the streaming handler attaches `sources`. `nginx.conf` has **no
  Cache-Control**, so `index.html` is heuristically cached by the browser and
  keeps referencing the previous content-hashed bundle.

## Decisions locked

- **#1:** focus/priority intent → force-include the actionable modules
  (tasks, plans, routines, goals) in retrieval, and add focus-ranking guidance to
  the answer prompt. No new plumbing — reuses round-3 structured retrieval.
- **#2:** prompt-only nudge (no data change).
- **#3:** `index.html` → `Cache-Control: no-cache`; `/assets/*` (content-hashed)
  → `immutable, max-age=31536000`.

## Architecture

### #1 Decisional focus

- `_is_focus_query(message)` — true for markers like `focus on`, `what should i
  do`, `what should i focus`, `prioritize`, `priorities`, `plan my day`,
  `what now`, `where should i start`, `how should i spend`.
- In `_route_and_classify` (`app/chat/actions.py`): after computing `modules`
  (LLM or lexical fallback), if `_is_focus_query(message)`, union `modules` with
  `{"tasks", "plans", "routines", "goals"}` and set `breadth = "broad"`. This
  guarantees the "Structured data" block is present for focus queries.
- **Answer prompt** (`_chat_system_prompt` for understanding, or the answer
  prompt builder): append focus guidance — "If the user asks what to focus on or
  how to prioritize, use the Structured data to RANK concrete items
  (tasks/plans/routines) by urgency (soonest or overdue due dates first), then
  priority, then alignment to active goals. Recommend an ordered short list (top
  ~3), each with a one-line reason, and lead with the single most important.
  Don't just describe — decide."

### #2 Field-leak cleanup

- Append to the base chat system prompt: "Render values in plain, natural
  language. Do not echo raw field names or status codes verbatim (e.g. 'Admit
  Until Date: D/S'); translate them ('admitted for duration of status') or omit
  if unclear."

### #3 Cache headers

- `frontend/nginx.conf`, inside the `server` block:
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
  (Keep the existing `/api/` and `/health` proxies.)

### Error handling / testing

- **#1:** `_is_focus_query` deterministic. Tests: `_is_focus_query` truthy for
  focus phrasings, falsy for "what's my dentist appointment"; `_route_and_classify`
  for a focus query yields `modules ⊇ {tasks, plans, routines, goals}` (LLM-stubbed
  → fallback path); the understanding context for a focus query contains the
  "Structured data" block.
- **#2:** the understanding system prompt mentions plain-language/no-raw-labels.
- **#3:** no unit test (nginx); verify via `curl -I` after rebuild that
  `index.html` returns `Cache-Control: no-cache` and an `/assets/*.js` returns
  `immutable`. Manual: hard-reload once, then confirm future rebuilds show new UI
  without a manual hard refresh.

## Out of scope (deferred)

- A dedicated "Decision Mode" with option/tradeoff generation (this is just
  focus-ranking inside Understanding).
- Service worker / offline caching.
