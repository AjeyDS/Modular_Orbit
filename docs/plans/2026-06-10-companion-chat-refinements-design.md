# Companion + Chat Refinements — Design

Date: 2026-06-10
Status: Approved, ready for implementation planning

## Summary

Post-build feedback on the Curious Companion and the main Chat. Six refinements:

1. **Conversation lifecycle** — sessions can be closed and a fresh one opened
   (companion session is currently a permanent singleton).
2. **On-demand "Ask me something"** — a button to pull a question whenever the
   person is free; questions are light/conversational, mostly fixed options with
   free text always available.
3. **Volunteered info → Logs** — meaningful volunteered replies become Log items
   (visible in Logs, no Curious clutter) and **still** enrich the user model.
4. **End-conversation controls** — `Skip` / `Talk later` / `Done`, plus typed
   end-intent ("bye", "talk to you later").
5. **Chat capture cards** — suppress suggested Capture Proposals on questions/
   lookups; keep explicit creation and real life-item intent.
6. **Chat live status** — real SSE streaming of pipeline stages + streamed answer.

Builds on `docs/plans/2026-06-09-curious-companion-design.md` and its
implementation. Affects `backend/app/modules/companion.py`,
`backend/app/api/curious.py`, `backend/app/chat/actions.py`,
`backend/app/api/chat.py`, `backend/app/llm/client.py`,
`frontend/src/pages/CuriousPage.tsx`, `frontend/src/pages/ChatPage.tsx`,
`frontend/src/lib/api.ts`.

## Decisions locked during brainstorming

- **Question style (all companion questions):** light, concrete, conversational;
  answerable in any length; **never** essay-prompting. Default to **2–4 fixed
  quick-reply options with free text always available as the implicit last
  option.**
- **Logs vs user model:** volunteered info is **logged AND enriches the user
  model**. Logs created with **`review=False`** so per-item Connection Review
  does not double up bucket updates; enrichment happens via the existing
  session-end synthesis pass.
- **Capture cards (chat):** **suppress suggested proposals on questions/lookups**;
  explicit "add this to tasks/logs/plans" always works.
- **Chat status:** **real SSE streaming** (genuine stage events + streamed
  answer tokens); keep the non-streaming endpoint as fallback.
- **Lifecycle default:** ending clears the visible thread to a fresh empty
  session; old messages are preserved in the DB but hidden. Past-conversation
  browser deferred.
- **Curious visibility:** volunteered info appears only in **Logs**, nowhere
  inside Curious. The captured-moments timeline + "N captured moments" counter
  are removed.

## Current state (context)

`backend/app/modules/companion.py`:
- `get_or_create_companion_session()` returns the single permanent companion
  session forever. `end_companion_session()` synthesizes + weaves but never
  closes or rotates the session.
- `record_user_turn()` stores meaningful replies as `curious_capture` Life Items
  + Knowledge Chunks; `get_companion_state()` exposes a `timeline` of them.
- `_companion_ask()` exists but is only reachable from `respond_to_user_turn`
  when there is no outstanding question. No on-demand endpoint.
- `generate_companion_question()` prompt does not constrain question size/style.

`backend/app/chat/actions.py`:
- `_detect_capture_proposals()` → `_detect_explicit()` then
  `_detect_suggested_with_llm()` / `_detect_suggested()`. The LLM shape detector
  fires on the user message with no question/lookup guard (the bogus
  "EAD Start Date" document card).

`backend/app/api/chat.py`: single `POST /chat/respond` (non-streaming).
`backend/app/llm/client.py`: `generate_text` / `generate_json`, **no streaming**.
`backend/app/modules/logs.py`: `create_log(LogCreate, *, review=True)`; when
`review` it runs `process_lifecycle_for_item` (Connection Review → may create
chunks + bucket updates).

## Architecture

### A. Conversation lifecycle (items 1 & 4)

- Add a session **state** in the companion session payload:
  `session_state ∈ {"open","closed"}` (default `open`).
- `get_or_create_companion_session()` returns the latest **open** session, or
  creates a new open one.
- `end_companion_session()` → synthesize → weave → set `session_state="closed"`.
  The next message or explicit "New conversation" opens a fresh empty session.
- **Skip** = ask a different question without ending (re-run `_companion_ask`,
  preferring a different `target_bucket_key` than the skipped one).
- **End triggers:** the `Done` / `Talk later` controls and `Skip` chips in the
  UI, plus lightweight typed end-intent detection (`bye`, `talk to you later`,
  `that's all`, `gotta go`) inside `respond_to_user_turn` → ends gracefully with
  a short sign-off.

### B. On-demand "Ask me something" + question style (items 2 & refinement)

- `POST /modules/curious/companion/ask` → forces `_companion_ask` on the open
  session, returns the question.
- Generation system prompt gains explicit constraints: *ask one small, concrete,
  conversational question; answerable in a few words or more; never demand a
  long/essay answer; provide 2–4 short quick-reply options when natural.*
- The UI always renders the free-text input alongside any chips (free text is
  the implicit "last option").

### C. Volunteered info → Logs, still enriches user model (item 3)

- In `record_user_turn`, a meaningful reply now calls
  `create_log(LogCreate(text=..., source={"kind":"companion_capture",
  "session_id": ...}), review=False)` instead of creating a `curious_capture`.
  `review=False` avoids duplicate bucket updates; the log still appears in the
  Logs page.
- **Session-end synthesis is unchanged** — reads the transcript and queues
  `curious_companion` bucket updates → Story Weave. User model keeps deepening.
- Remove `CompanionTimelineEntry`, `CompanionState.timeline`, the
  `curious_capture` queries, and the Curious timeline UI + counter.

### D. Chat capture cards: suppress on questions (item 5)

- Guard at the top of `_detect_capture_proposals`: if the message is a
  question/lookup (trimmed ends with "?", or starts with an interrogative
  marker: `what|when|where|who|why|how|which|is|are|do|does|did|can|could|
  should|will`) and is not an explicit add-request, return `[]`.
- Explicit `_detect_explicit` still runs first (so "add this to tasks" inside a
  question still works). Tighten the LLM detector prompt to refuse questions.

### E. Chat live status via SSE (item 6)

- Add `generate_text_stream(prompt, *, system, ...)` to `llm/client.py` using
  `client.models.generate_content_stream(...)`, yielding text deltas; raises
  `LLMUnavailable` when disabled.
- Add a streaming responder (e.g. `respond_to_chat_stream(request)`) that
  `yield`s typed events as the pipeline runs:
  - Understanding: `{"stage":"routing"}` → `{"stage":"retrieving"}` →
    `{"stage":"reading_story"}` → `{"stage":"writing"}` →
    `{"stage":"answer","delta":"..."}` (repeated) → `{"stage":"done",
    "suggestions":[...]}`.
  - Fast: `retrieving` → `writing` → `answer` deltas → `done`.
- Add `POST /chat/respond/stream` returning `text/event-stream`
  (`fastapi.responses.StreamingResponse`), each event a `data: <json>\n\n` line.
- Persist the user + assistant messages exactly as the non-streaming path does
  (reuse the session/insert helpers); capture-proposal detection runs once,
  guarded per §D, and rides on the final `done` event.
- Keep `POST /chat/respond` as the non-streaming fallback.
- Frontend `ChatPage.tsx`: send via `fetch` to the stream endpoint, read
  `response.body` with a `ReadableStream` reader, parse `data:` lines, show a
  live status line per stage, then render streamed answer tokens; fall back to
  `respondToChat` on error.

### Error handling

- All new LLM calls wrapped in `try/except (LLMUnavailable, Exception)` with
  deterministic fallbacks (matches existing code).
- Streaming: if `generate_text_stream` is unavailable, emit `writing` then a
  single `answer` event built from the existing non-streaming fallback text,
  then `done`. The stream must always terminate with `done`.
- End-intent and question/lookup detection are deterministic (no LLM dependency).
- Companion logs use `review=False` to avoid duplicate/parallel bucket updates.

### Testing focus

- Lifecycle: `end_companion_session` closes the session + synthesizes; the next
  `get_or_create_companion_session` returns a new empty open session; typed
  end-intent ends gracefully.
- On-demand ask returns + persists a question on the open session.
- Volunteered meaningful reply creates a **Log** Life Item (module `logs`),
  **not** a `curious_capture`, and session-end synthesis still queues bucket
  updates.
- Capture suggestion suppressed for interrogative messages; explicit add still
  fires.
- SSE responder yields ordered stage events then `answer`/`done`; with the LLM
  stubbed it still terminates with `done` and a fallback answer.

## Out of scope (deferred)

- Past-conversation browser / history UI.
- Multi-question batching; notifications; background scheduler.
- Retiring Logs or Curious onboarding questions.
- Token-level streaming refinements beyond basic delta passthrough.
