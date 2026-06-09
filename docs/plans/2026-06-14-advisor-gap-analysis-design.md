# Advisor Gap Analysis (Round 6) — Design

Date: 2026-06-14
Status: Approved, ready for implementation planning

## Summary

Chat answers only *recombine what the user already entered* — they never suggest
what the user is **missing** or **should learn next**. Cause: the system prompt
says "use the provided context only; do not invent," which blocks legitimate
advice along with hallucination. Fix (no internet): let the advisor contribute
**general knowledge + gap analysis**, clearly separated from private facts, and
explicitly instruct it to surface concrete next steps the user hasn't listed.

Web access stays **out of scope** for implementation this round; the gated-web
approach is captured as a deferred design (below) for a later step.

## Decisions locked

- **Base-model gap analysis now** (no internet): prompt change + advice-intent
  detection. ~zero extra cost/latency.
- **Two content rules:** private facts → grounded only, never invent; general
  knowledge/advice/gap analysis → the advisor may and should contribute, framed
  as suggestions.
- **Gap instruction:** when asked what to learn/improve/do next, compare current
  state (structured data) against what the goals typically require and surface
  things the user hasn't already listed.
- **Hallucination guard:** suggest skill areas/topics/resource *types*, not
  invented specific course names or URLs (that's what gated web is for later).
- **Web grounding:** deferred design only, not built this round.

## Context (current state)

- `app/chat/actions.py::_chat_system_prompt`: base says "Use the provided Story
  Buckets, Goals, module data, Connections, and Knowledge Chunks only as context;
  do not invent private facts." Understanding mode already has focus-ranking
  guidance (round 5) and `_is_focus_query` force-includes actionable modules.
- No web/grounding/tools wired into the Gemini calls (`llm/client.py`).
- Round 5's `_route_and_classify` unions `modules` with the actionable set for
  focus queries — the same mechanism advice queries will reuse.

## Architecture

### 1. Prompt: separate facts from advice + gap instruction

In `_chat_system_prompt` base, replace the single "only as context; do not
invent" line with two explicit rules:

- "The provided Story Buckets, Goals, module data, Connections, and Knowledge
  Chunks are the source of truth for facts ABOUT THE PERSON — never invent or
  guess personal facts."
- "You MAY and SHOULD contribute general world knowledge, opinions, and gap
  analysis (skills, learning paths, what's commonly needed for the person's
  goals). Frame these clearly as suggestions or possibilities, never as facts
  about the person."

Add an advice/gap clause (understanding mode):

- "When the person asks what to learn, improve, or do next, don't just
  recombine what they already have. Compare their current skills/projects/
  routines against what their goals typically require, and surface 1–3 concrete
  things they have NOT already listed (a real gap), each with a one-line why.
  Suggest skill areas, topics, and types of resources — do NOT fabricate
  specific course names, products, or links."

### 2. Advice-intent detection → force-include actionable modules

- Add `_is_advice_query(message)` with markers: `what can i learn`,
  `what should i learn`, `what to learn`, `what am i missing`, `how do i
  improve`, `how can i improve`, `level up`, `fuel my career`, `make the most`,
  `what's next`, `whats next`, `what should i do next`.
- In `_route_and_classify`, extend the existing focus union so it also fires for
  advice queries: if `_is_focus_query(message) or _is_advice_query(message)`,
  union `modules` with `{"tasks","plans","routines","goals"}` and set
  `breadth = "broad"`. (One shared block; reuse round-5 logic.)
- This guarantees the model has the user's current baseline (structured data) to
  find gaps against.

### Error handling / testing

- Deterministic detectors; prompt-only behavior otherwise. Fast mode unchanged
  (no advice ranking; it answers from retrieved knowledge).
- Tests:
  - `_is_advice_query` truthy for "what can I learn next to fuel my career?",
    falsy for "when is my dentist appointment?".
  - `_route_and_classify("what can I learn next…")` yields
    `modules ⊇ {tasks,plans,routines,goals}`.
  - `_chat_system_prompt("understanding")` mentions both: not inventing personal
    facts AND contributing general knowledge/gap analysis (assert keywords like
    "gap"/"suggest"/"general").
  - Behavioral (verify via app): an advice answer includes at least one
    beyond-inputs suggestion, framed as a recommendation, with no fabricated
    course links.

## Deferred design — gated web grounding (NOT built this round)

For a later step, to add freshness (current courses, trending tools, job-market):

- `_is_fresh_query(message)` markers: `current`, `latest`, `trending`, `right
  now`, `this year`, `2026`, `courses available`, `job market`, `salary`,
  `in demand`.
- When fresh + advice/focus intent, run a Gemini **Google Search grounded** call
  (new `llm/client.py` path using the search tool), synthesize with citations.
- Surface grounded web pages as `SourceRef(kind="web", label=…, url=…)` flowing
  into the round-4 Sources footer.
- Default OFF; only for fresh queries (evergreen advice stays base-model to avoid
  top-SEO-listicle noise). Adds latency + per-grounded-request cost; needs
  citation parsing and a separate call config.

## Out of scope

- Web grounding implementation (deferred design above).
- A standalone Decision Mode.
