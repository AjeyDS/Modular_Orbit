# Thinking-Step Chat Pipeline (Round 7) — Design

Date: 2026-06-15
Status: Approved, ready for implementation planning

## Summary

Replace the growing pile of hand-coded intent detectors and per-question prompt
clauses (`_is_focus_query`, `_is_advice_query`, focus/gap clauses) with a single
adaptive **Thinking** step. When a question arrives, a dedicated LLM call reasons
about *how to approach it* (using the user-model index) and emits a freeform
**strategy** plus retrieval hints; routing/retrieval/synthesis then run per that
plan. This generalizes the whack-a-mole prompt tuning into one reasoning layer.

Chosen shape: **a separate dedicated thinking call** (not folding it into the
router) — cleaner step boundaries, simpler downstream prompts, better output, at
the cost of +1 LLM call per Understanding turn (accepted).

## Decisions locked

- **Separate Thinking call** before routing/retrieval (Option B).
- **Freeform strategy:** the planner writes the `approach` itself per question
  (using the user-model index, and structured data via the downstream steps).
- **Primary path = planner;** the hand-coded focus/advice clauses and intent
  detectors become **deterministic fallback only** (LLM-down path).
- **Understanding mode only.** Fast stays single-pass (pure chunk RAG).
- **Deferred:** a true agentic loop (think → retrieve → re-think). The existing
  single conditional sufficiency follow-up remains the only re-retrieval.

## Context (current state, `app/chat/actions.py`)

- Understanding pipeline today: `_route_and_classify` (LLM router → breadth,
  buckets, modules, expansion) → `_understanding_retrieval` (RAG + 1 conditional
  `_sufficiency_check`) → structured/bucket/connection/goal context →
  `generate_text` synthesis. SSE mirror in `respond_to_chat_stream` with stage
  events.
- Hand-coded intent: `_is_focus_query`, `_is_advice_query` (round 5/6) union the
  actionable modules and the system prompt carries focus-ranking + gap clauses.
- `_chat_system_prompt(mode)` holds base + formatting + understanding clauses.

## Architecture

### New Understanding flow

```
Think (LLM #1) → Route (LLM #2, seeded by plan) → Retrieve (deterministic)
  → conditional sufficiency follow-up → Synthesize (LLM, strategy-directed)
```

### 1. Think step (`_think(message) -> ThinkingPlan`)

- Build a compact **user-model index**: active bucket `display_name + description`
  (one line each), goal titles (+status/horizon), the queryable module list
  (tasks/plans/goals/routines), and a one-line recent-activity hint.
- One `generate_json` call. Output:
  ```json
  {
    "question_type": "lookup|gap_analysis|prioritize|how_to|reflection|open",
    "approach": "freeform: how to tackle THIS question; what to weigh; what a great answer looks like",
    "retrieval_hint": "freeform: which life areas / modules / data to pull and why"
  }
  ```
- `ThinkingPlan` dataclass holds the three fields.
- **Fallback** (LLM down / invalid): derive a plan deterministically — use
  `_is_focus_query`/`_is_advice_query` to set `question_type`
  (prioritize/gap_analysis) and a curated `approach` snippet; else
  `question_type="open"` with a generic approach. Never raises.

### 2. Route (seeded)

- `_route_and_classify(message, plan)` gains the plan: its prompt includes
  `plan.retrieval_hint` and `question_type` to pick `buckets`/`modules`/`breadth`/
  `expansion_terms`. Keep the existing lexical fallback. The deterministic
  focus/advice module-union still applies (now also triggerable by
  `question_type in {prioritize, gap_analysis}`).

### 3. Retrieve

- Unchanged: RAG chunks + selected buckets + structured module data +
  connections + goals; one conditional sufficiency follow-up.

### 4. Synthesize (strategy-directed)

- The synthesis prompt injects `plan.approach` as the **strategy directive**
  ("Approach for this answer: …"). This replaces the hard-coded focus-ranking /
  gap clauses as the primary guidance. Keep the base rules (grounded personal
  facts; may contribute general advice; clean formatting; plain values) always.
- The curated focus/gap clause text is retained only inside the deterministic
  fallback `approach` (so LLM-down answers still behave).

### 5. Streaming

- `respond_to_chat_stream` emits a new first stage `{"stage":"thinking"}`
  (label "Thinking it through…") before `routing`. Order: thinking → routing →
  retrieving → (reading_story / checking_state) → writing → answer → done.

### Error handling

- Each LLM call wrapped in `try/except (LLMUnavailable, Exception)` with a
  deterministic fallback; the full pipeline must answer with the LLM stubbed
  (Think → fallback plan; Route → lexical; Synthesize → fallback context answer).
- Plan fields clamped: unknown `question_type` → "open"; empty `approach` →
  curated default.

### Testing

- `_think` fallback returns a valid `ThinkingPlan` with the LLM stubbed; focus/
  advice phrasings map to prioritize/gap_analysis question_types via fallback.
- `_think` LLM path parses fields (monkeypatched `generate_json`).
- The plan's `approach` reaches the synthesis prompt (assert the answer-prompt
  builder includes the approach text).
- Router consumes `retrieval_hint` (monkeypatch router `generate_json`; assert
  prompt contains the hint).
- Understanding pipeline still produces an answer with the LLM fully stubbed.
- SSE stream emits `thinking` before `routing` and still ends with `done`.
- Fast mode unchanged: no thinking/route calls.

## Out of scope (deferred)

- Agentic re-think loop (think → retrieve → re-think → retrieve).
- Web grounding (separate deferred design from round 6).
- Applying the thinking step to Fast mode or the companion.
