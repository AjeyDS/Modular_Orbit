# History-Aware Chat (Round 8) — Design

Date: 2026-06-16
Status: Approved, ready for implementation planning

## Summary

The chat is single-turn: every message is answered in isolation. Prior messages
are stored (`chat_messages`) but never fed into any LLM call. So referential
follow-ups drift — "give me priority order of **this**" lost its referent (a
learning list) and the pipeline re-prioritized the user's *goals* instead.

Fix: make the pipeline **history-aware** by resolving the follow-up in the
**Think step** into a self-contained question that then drives routing,
retrieval, and synthesis. Recent turns also flow into synthesis for continuity.

## Decisions locked

- **Resolve follow-ups in the Think step** (not synthesis-only): the rewritten,
  self-contained question drives retrieval, so referential follow-ups fetch the
  right data — not just read better.
- **History window:** last ~6 messages (≈3 exchanges), per-message truncation.
  Summarizing long threads is **deferred**.
- **Understanding** gets full treatment; **Fast** gets recent history in its
  synthesis prompt only (no Think step), retrieval stays on the raw message.
- First turn (no history) must behave exactly as today.

## Context (current state)

- `app/chat/actions.py`: `respond_to_chat` / `respond_to_chat_stream` insert the
  user message then run `_think(message)` → `_route_and_classify(message, plan)` →
  retrieval → synthesis, all on the single `message`. No history is read back.
- `ThinkingPlan` = `{question_type, approach, retrieval_hint}` (round 7).
- `app/chat/sessions.py`: `list_chat_messages(session_id)` returns the full thread
  ordered `created_at ASC` with `role/content`. `insert_chat_message(...)` appends.
- `ChatRequest` carries `session_id`.

## Architecture

### 1. Load recent history (before inserting the current turn)

- `_recent_history(session_id, *, limit=6, char_cap=500) -> list[tuple[str,str]]`:
  returns the last `limit` `(role, content)` pairs (each truncated to `char_cap`),
  oldest→newest. Wrapped in try/except → `[]` on error.
- In `respond_to_chat` and `respond_to_chat_stream`, capture
  `history = _recent_history(request.session_id)` **before**
  `insert_chat_message(user, ...)` so the current message isn't included.

### 2. Think step resolves the follow-up

- `ThinkingPlan` gains `resolved_question: str = ""`.
- `_think(message, history=None)`:
  - Prompt includes a compact "Recent conversation" block (from `history`) and
    instructs: "Restate the user's new message as a SELF-CONTAINED question,
    resolving any references like 'this/that/those/it' using the recent
    conversation. Also classify question_type, approach, retrieval_hint." Output
    adds `"resolved_question"`.
  - Fallback / empty: `resolved_question = message`.
- `_think_fallback(message)` sets `resolved_question = message` (no history use).

### 3. Route + retrieve on the resolved question

- Define `query = plan.resolved_question or message`.
- `_route_and_classify(query, plan)` and `_understanding_retrieval(query, ...)`
  use `query` (so retrieval anchors to the real subject).
- `_detect_capture_proposals` still uses the **raw** `message` (intent to create
  is about what the user literally said).

### 4. Synthesis continuity

- The answer-prompt builder gains an optional `history` arg; when present it
  prepends a short "Recent conversation:\n<role: content>…" block. The answer
  still targets the user's actual (resolved) intent + `plan.approach`.

### 5. Fast mode

- No Think/resolution. Pass `history` into the Fast synthesis prompt for basic
  continuity; retrieval stays on the raw `message`.

### Error handling

- `_recent_history` → `[]` on any error (chat still works).
- All LLM calls keep deterministic fallbacks; with the LLM stubbed,
  `resolved_question = message` and the pipeline degrades to today's single-turn
  behavior.

### Testing

- `_recent_history` returns the last N `(role, content)` in order and **excludes
  the current turn** (called before insert); truncates long messages; `[]` for a
  new session.
- `_think(message, history)` returns a `resolved_question` (monkeypatched
  `generate_json`); fallback sets `resolved_question = message`.
- Route + retrieval receive the **resolved** question (monkeypatch router/retrieval
  to capture their input; assert it's the resolved string, not the raw follow-up).
- Synthesis prompt includes the recent-conversation block when history is present.
- First-turn (empty history) Understanding + Fast behave exactly as today.
- Pipeline still answers with the LLM fully stubbed.

## Out of scope (deferred)

- Summarizing/compacting long threads beyond the fixed window.
- Cross-session memory (only same-session history).
- Applying resolution to the companion (separate surface).
