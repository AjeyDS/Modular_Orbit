# Curious → Companion — Design

Date: 2026-06-09
Status: Approved, ready for implementation planning

## Summary

Evolve the **Curious** module from a multiple-choice question-card UI into a
persona-driven **conversational companion**. The companion checks in
proactively, asks targeted questions by reasoning over the user model + goals +
active tasks/plans, **receives volunteered life updates**, encourages briefly,
and harvests everything it learns into the user model. It subsumes the **Logs**
module's role: every log-worthy moment becomes a captured conversation turn that
also feeds the Story Buckets.

This reuses machinery that already exists rather than building from scratch:
Curious is already a "question → harvest" engine (answer → Life Item +
Knowledge Chunk + Bucket Update → Story Weave), it has a dormant `dynamic`
question tier, and Story Weave already merges pending Bucket Updates into bucket
prose.

**Value Moment:** primarily **Capture** (pulls life data in through
conversation), plus a relationship/understanding angle that enriches the user
model feeding everything downstream.

## Decisions locked during brainstorming

- **Home:** evolve the existing **Curious** module (not a new chat mode, not a
  new sibling module). Keep the harvest pipeline, bucket targeting, and settings
  surface; change the *interaction shape* to conversation.
- **Onboarding/cold-start:** keep the existing foundational (onboarding + bay)
  questions for cold-start, surfaced conversationally with quick-reply chips,
  then shift to free generation once foundations are covered. *Conversation with
  inline choices*, not pure free-text and not pure cards.
- **Persona config:** named **presets** (Warm / Coach / Gentle / Direct) **plus
  an optional freeform override**, stored in the Curious module-instance
  settings.
- **Proactive delivery:** in-app, prepared on a schedule. Because the app has
  **no scheduler infrastructure** (no celery/apscheduler/cron; today's Curious
  weave is client-driven via idle timers + `pagehide` beacons), v0 implements a
  **lazy due-check on app open**, not a true background cron.
- **Harvest timing:** **raw per-turn, synthesize at session end.** Meaningful
  turns are stored raw immediately; one synthesis pass at session end extracts
  and routes facts to buckets, then Story Weave merges.
- **Bidirectional behavior:** the companion either **asks** a targeted question
  or **receives-and-acknowledges** a volunteered update ("Got it — that's
  great"), short and warm, no interrogation.
- **Logs replacement:** companion-captured moments render as a **dated,
  browsable timeline** inside Curious — a stand-in for the Logs feed. Captured
  moments are the companion's *own* Life Items (not real `logs` items). The Logs
  module keeps running in parallel during v0 as a safety net and is retired only
  once the companion proves out.
- **In-conversation create-actions** (Tasks/Plans/Logs/Routines) are **out of
  scope for v0**.

## Current state (context)

`backend/app/modules/curious.py`:
- Pre-authored `ONBOARDING_QUESTIONS` and `BAY_QUESTIONS`, each with a known
  `target_bucket_key`. A `dynamic` `QuestionTier` is **defined but unused**.
- Answering a question (`answer_pending_question` / `answer_onboarding_question`)
  creates a `curious_answer` Life Item and calls
  `_persist_direct_connection_and_updates`, which writes: a direct
  `item_connections` row, a pending `bucket_updates` row, and a
  `knowledge_chunks` row, then marks the Life Item's lifecycle side-statuses
  complete.
- `weave_pending_curious_updates()` merges pending `curious_bay`/`curious_dynamic`
  Bucket Updates via `weave_story_bucket(bucket_id)`.

`frontend/src/pages/CuriousPage.tsx`:
- Focus-card UI (`FocusQuestion`) with single-choice options, a "Learned"
  accordion, a user-model preview, and a settings popover
  (`notify_questions_enabled`, `max_new_questions_per_week`, `curious_paused`).
- Weave is triggered client-side: on "Done for now", on idle
  (`CURIOUS_IDLE_WEAVE_MS = 2 min`), and on `pagehide` via a beacon.

`backend/app/chat/actions.py`:
- Capture Proposal flow (preview + confirm) exists for tasks/logs/plans/
  documents — available for later in-conversation create-actions, not used in v0.

No scheduler/background-job infrastructure exists anywhere in the backend.

## Architecture

### 1. Interaction model

- A single **conversation thread** replaces the focus-card UI. Turns are short;
  the companion asks, reacts, and encourages — it does **not** produce lists or
  essays. Enforced via system prompt + a low `max_output_tokens`.
- **Bidirectional per turn:**
  - *Companion-initiated:* it asks a targeted question (see §3).
  - *User-initiated:* the user volunteers a fact/update; the companion
    **acknowledges briefly** and the turn is harvested. Generation is skipped.
- **Quick-reply chips:** when a question is naturally multiple-choice, the turn
  may carry chips (reusing the existing `CuriousOption` shape). The user taps a
  chip or types freely.
- **Cold-start:** while the user model is thin, the companion leans on the
  foundational questions (surfaced conversationally with chips). Once foundations
  are covered, it shifts to free generation.

### 2. Persona configuration

- A small set of **presets** (Warm / Coach / Gentle / Direct), each a curated
  system-prompt fragment, **plus an optional freeform override** the user writes.
- Stored in the Curious module-instance `settings` (same place as today's
  Curious settings). Assembled into the companion's system prompt at
  conversation time. Defaults exist and are restorable (architecture invariant).

### 3. Question generation (the heart)

A single typed `generate_json` call composes the next companion move from:
- the persona,
- the user model (selected Story Buckets / self-profile),
- goals (`goals.md` via `list_goals`),
- active tasks & plans (lightweight structured lookup),
- recent conversation + already-asked coverage (so it does not repeat).

Output shape:

```json
{
  "opening_message": "string",
  "target_bucket_key": "career",
  "quick_replies": [{ "id": "...", "label": "...", "bucket_update_text": "..." }],
  "rationale": "one short line"
}
```

- `target_bucket_key` clamps to known bucket keys.
- `quick_replies` is optional (empty when the question is naturally open).
- **Fallback (LLM down):** fall back to the next unanswered foundational/bay
  question (the existing structured queue).

For **volunteered updates**, generation is skipped entirely: the companion emits
a short acknowledgment and the turn goes straight to harvest (§5).

### 4. Proactive check-ins

- Curious settings gain a **check-in frequency** (e.g. times/day, or off).
- **v0 = lazy due-check on app open:** when the user opens the app/Curious, the
  backend checks `now − last_check_in ≥ interval`. If due, it prepares the next
  check-in (generates the opener via §3) and it is waiting as a greeting/badge.
- This is consistent with today's client-driven Curious pattern.
- **Deferred:** a real backend scheduler that prepares check-ins while the app
  is closed (and optionally browser/OS notifications).

### 5. Harvesting (raw per-turn, synthesize at session end)

- **Per meaningful turn:** a cheap meaningfulness **gate** decides whether the
  user's reply carries real signal (skips "thanks" / "ok" / filler). If yes,
  store raw immediately: a companion-turn Life Item + a `knowledge_chunk`
  (free-text variant of today's `curious_answer` flow).
- **At session end** (idle timeout or explicit "done" — the same triggers
  Curious already uses): one **synthesis pass** reads the whole conversation,
  extracts facts, routes each to a bucket, and queues `bucket_update`s →
  **Story Weave** (`weave_story_bucket`) merges them into bucket prose. Reuses
  the `weave_pending_curious_updates` machinery and source tagging.
- Net effect: raw is captured live (no data loss on abandonment); synthesized
  facts get full-conversation context (better quality, fewer LLM calls).

### 6. Logs replacement

- Companion-captured moments render as a **dated, browsable timeline** inside
  Curious — a stand-in for the Logs feed.
- Captured moments are the companion's **own Life Items** (a companion-turn /
  captured-moment item type), **not** real `logs` module items, so Logs can be
  retired later by pointing the timeline at companion items.
- The **Logs module stays running in parallel** during v0 as a safety net. It is
  retired only once the companion's capture quality is proven.

### Code changes (high level)

- `backend/app/modules/curious.py`: add conversational turn handling, the
  question-generation call (activating the `dynamic` tier), the meaningfulness
  gate, per-turn raw capture for free-text, the session-end synthesis pass, the
  due-check, and the captured-moment timeline query. Keep the foundational
  question queue as cold-start + fallback.
- New helpers follow the existing typed `generate_json` + deterministic-fallback
  pattern used by the chat router and Curious.
- Curious module-instance settings: add persona preset + override and check-in
  frequency, with defaults and restore-default support.
- `frontend/src/pages/CuriousPage.tsx`: replace the focus-card UI with a
  conversation thread (with quick-reply chips), surface the prepared check-in /
  greeting, the dated captured-moments timeline, and the persona + frequency
  settings. Keep the client-driven weave triggers (idle / done / pagehide).
- API layer (`backend/app/api/curious.py`): endpoints for sending a turn,
  fetching conversation + timeline state, checking/preparing a due check-in, and
  the session-end synthesis/weave (extend existing weave endpoint).

### Error handling

- Every LLM call wrapped in `try/except (LLMUnavailable, Exception)` with a
  deterministic fallback (matches existing code). The companion must still
  function with the LLM fully stubbed:
  - question generation → next foundational/bay question,
  - meaningfulness gate → conservative default (treat substantive-length,
    non-trivial replies as meaningful),
  - synthesis pass → skip silently, leaving raw captures intact and Bucket
    Updates unqueued (no data loss; can be re-run).
- Story Weave failures leave Bucket Updates pending/failed for later review and
  do not roll back raw captures (architecture invariant).
- Due-check is idempotent: it must not prepare duplicate check-ins for the same
  interval window.

### Testing

- **Meaningfulness gate:** skips filler, keeps real signal; stubbed-LLM fallback
  behaves sensibly.
- **Per-turn raw write:** a meaningful turn creates a companion Life Item + a
  Knowledge Chunk.
- **Session-end synthesis:** queues Bucket Updates and triggers Story Weave;
  raw captures survive a synthesis failure.
- **Question-gen fallback:** with the LLM stubbed, generation returns the next
  unanswered foundational/bay question.
- **Bidirectional behavior:** a volunteered fact yields a short acknowledgment +
  capture and does **not** generate a new question.
- **Due-check:** prepares a check-in only after the interval elapses; idempotent
  within a window.
- **Persona assembly:** preset + optional override compose into the prompt;
  defaults restore.
- **Timeline:** captured moments list in date order.

## Out of scope (deferred)

- In-conversation create-actions (Tasks / Plans / Logs / Routines) via Capture
  Proposals.
- Browser/OS notifications and a true background scheduler for away-from-app
  check-ins.
- Companion-managed recurring "Routines" (a net-new recurring-topic mechanism).
- Full retirement of the Logs module (kept in parallel during v0).
