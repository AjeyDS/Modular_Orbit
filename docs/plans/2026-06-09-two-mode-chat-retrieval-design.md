# Two-Mode Chat Retrieval Pipeline — Design

Date: 2026-06-09
Status: Approved, ready for implementation planning

## Summary

Replace the four chat modes (free / context / deep / decision) with **two**:
**Fast** and **Understanding**. Fast is pure vector RAG over Knowledge Chunks.
Understanding adds a user-model layer: a cheap router selects 1–3 relevant Story
Buckets, those buckets frame the answer, and — only for broad queries — they
expand retrieval. A conditional single follow-up retrieval fills clear gaps.

This is the concrete, non-function-calling answer to the previously deferred
"chat structured querying / tool-use" item in
`docs/plans/2026-06-08-user-model-aware-modules-design.md`.

## The anti-dilution principle (core constraint)

The user model is for **understanding and framing the answer**, not for
polluting the retrieval query. Mixing all bucket content into the search drags
results off-topic. Therefore:

- Buckets shape **retrieval** ONLY when the query is broad/vague
  (e.g. "what should I focus on?").
- For a narrow query (e.g. "when's my dentist appointment?"), retrieval uses the
  user's own words; buckets sit on the **synthesis** side only.

## Decisions locked during brainstorming

- **Modes:** replace the four modes with `fast` and `understanding`.
- **Bucket selection:** an LLM router reads the 8 bucket `name + description`
  (one line each) and picks 1–3 — **no bucket vectorization**. There are only 8
  fixed, named, multi-topic buckets; embedding them is overkill and worse for
  selection than letting the model read short descriptions. Vectors stay for the
  raw-data layer (`knowledge_chunks`) only.
- **Pipeline depth:** single pass, plus **one** conditional targeted follow-up
  retrieval when a clear gap exists. Never a loop.
- **Breadth (narrow vs broad)** is judged by the same router call, with a
  lexical heuristic fallback.
- **Fast mode = zero user model** (pure chunk RAG).

## Current state (context)

`backend/app/chat/actions.py`:
- `ChatMode = Literal["free", "context", "deep", "decision"]`.
- `respond_to_chat` → `_generate_chat_answer` → `_build_answer_context`
  assembles five blocks (chunks, connections, story buckets, goals, module data)
  into a **single** `generate_text` call. No tool-calling, no model-driven
  queries.
- `_story_bucket_context` ([actions.py:563]) attaches **all 8** buckets on every
  turn, truncated to 1200 chars — the behavior bucket selection replaces.
- Capture-proposal detection (`_detect_capture_proposals`) runs per turn and is
  orthogonal to retrieval.

`backend/app/rag/retrieval.py`:
- `retrieve_chunks(query, limit)` does pgvector search over `knowledge_chunks`
  with a text-search fallback. Story Buckets are **not** in `knowledge_chunks`;
  they live as markdown in `story_buckets.content` and are not embedded.

Frontend: `frontend/src/pages/ChatPage.tsx` renders the four-mode selector.

## Architecture

### Modes

| Mode | Pipeline | LLM calls |
|------|----------|-----------|
| **Fast** | `query → retrieve_chunks(query) → answer` | 1 (answer) |
| **Understanding** | route+classify → focused retrieval → conditional 1 follow-up → synthesize | 2–3 |

### Understanding pipeline

1. **Route + classify** — one typed `generate_json` call. Input: query + the 8
   buckets' `name + description` (one line each, NOT their content). Output:
   ```json
   {
     "breadth": "narrow" | "broad",
     "buckets": ["career", "aspirations"],
     "expansion_terms": ["staff engineer", "mentoring"],
     "rationale": "one short line"
   }
   ```
   - `buckets`: 1–3 stable keys (clamp to known keys; clamp count to 3).
   - `expansion_terms`: populated ONLY when `breadth == "broad"`, else `[]`.
   - **Fallback (LLM down):** breadth via heuristic (wide-scope markers like
     "what should I", "everything", "my life", or very short/open questions →
     broad; else narrow); buckets via lexical token overlap between the query and
     each bucket's `display_name + description`, top 1–3 over a small threshold.

2. **First retrieval — focused.**
   - `narrow`: `retrieve_chunks(query)` verbatim. Buckets MUST NOT enter the
     search string (anti-dilution guard).
   - `broad`: `retrieve_chunks(query + " " + " ".join(expansion_terms))`.
     (Implementation may instead run a few small retrievals across the chosen
     buckets' themes and merge by score — single combined query is the simpler
     default.)

3. **Conditional second retrieval (at most one).** A lightweight sufficiency
   check (typed `generate_json`, or a deterministic heuristic fallback) reads the
   first results and returns `{ "sufficient": bool, "follow_up_query": str }`.
   If not sufficient and a non-empty `follow_up_query` is returned, run exactly
   one more `retrieve_chunks(follow_up_query)` and merge. Hard cap: one extra
   hop. Fallback: treat as sufficient (skip the follow-up).

4. **Synthesize.** The answer `generate_text` call receives:
   - the **original query** as the anchor,
   - the selected buckets' **full content** (framing/personalization),
   - the merged retrieved chunks (raw data),
   - (unchanged) connections/goals context if retained.

   System prompt: answer the user's actual question; use the user model to frame
   and personalize, not to wander off-topic.

### Code changes

- `ChatMode` → `Literal["fast", "understanding"]`. Update `ChatRequest`, the
  system-prompt selection, `_build_answer_context`, and `_generate_chat_answer`
  in `backend/app/chat/actions.py`.
- New helpers (all typed `generate_json` + deterministic fallback, matching the
  existing priority-advisor pattern): `_route_and_classify(message)`,
  `_select_buckets_fallback(message)`, `_sufficiency_check(query, chunks)`.
- New bucket-content fetch by stable key (full content for the chosen buckets).
- Replace `_story_bucket_context`'s attach-all behavior in the Understanding
  path with attach-selected. Fast path attaches none.
- Frontend `ChatPage.tsx`: replace the four-mode selector with a Fast /
  Understanding toggle; update any persisted/default mode value.
- Capture-proposal detection stays in both modes, unchanged.
- No embedding/vectorization of buckets.

### Error handling

- Every LLM call wrapped in `try/except (LLMUnavailable, Exception)` with a
  deterministic fallback (matches existing code). The pipeline must produce an
  answer even with the LLM fully stubbed.
- Router returning unknown/empty bucket keys → drop unknowns; if none remain,
  proceed with no buckets (degrade toward Fast-like behavior) rather than error.
- `retrieve_chunks` already falls back from vector to text search internally.

### Testing

- Router fallback returns sensible bucket keys with the LLM stubbed.
- **Narrow query anti-dilution guard:** assert the retrieval query string passed
  to `retrieve_chunks` does NOT contain bucket content/expansion terms.
- **Broad query:** assert `expansion_terms` are applied to the retrieval query.
- Sufficiency check triggers **at most one** extra `retrieve_chunks` call
  (assert call count ≤ 2 in Understanding mode).
- **Fast mode:** assert no router/bucket-selection/sufficiency calls happen and
  no bucket content is attached.
- Existing chat tests updated for the two-mode `ChatMode`.

## Out of scope (deferred)

- True LLM function-calling / agentic multi-hop retrieval (>1 follow-up).
- Vectorizing Story Buckets (revisit only if buckets are later split into many
  sub-buckets).
- Surfacing side-table fields (task `due_window`, plan progress) into retrieval —
  separate from this pipeline; tracked in the user-model-aware-modules design.
