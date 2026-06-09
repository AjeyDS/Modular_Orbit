# Chat Formatting & Sources (Round 4) — Design

Date: 2026-06-12
Status: Approved, ready for implementation planning

## Summary

Polish the main chat's answers. Two complaints from testing:

1. **"Stars everywhere."** The model emits good markdown, but the UI prints it
   raw (`<p className="whitespace-pre-wrap">{message.content}</p>`, no markdown
   library), so `**bold**` and `*` bullets show as literal asterisks.
2. **No references.** The user wants a neat "where this came from" footer.

Fix: render markdown, nudge the prompt toward restrained formatting, and append a
**deterministic** Sources footer built from what was actually retrieved (no
model-generated citations → no hallucinated references).

Sequencing: execute **after** round 3
(`2026-06-11-usermodel-chat-refinements`) so the Sources footer can include the
structured modules (tasks/plans/goals/routines) that round 3 adds.

## Decisions locked during brainstorming

- **Markdown rendering:** add `react-markdown` + `remark-gfm`; render assistant
  bubbles + the streaming buffer through it. User + companion messages stay plain.
- **References:** **deterministic Sources footer**, not model citations. Built
  from the answer's actual retrieval; returned as structured data and rendered
  separate from the model text.
- **Prompt:** light formatting nudge (short paragraphs, sparing bullets, minimal
  bold, no stacked headings).
- **Scope:** main chat (Understanding + Fast). Companion unchanged.

## Current state (context)

- `frontend/package.json`: no markdown library. `ChatPage.tsx:356` renders
  assistant content as raw text; `:405` renders the streaming buffer raw.
- `backend/app/chat/actions.py`: `_build_answer_context(mode, message)` returns a
  context **string**; `respond_to_chat` → `_generate_chat_answer`; the SSE path
  `respond_to_chat_stream` computes `decision`/`chunks` itself and ends with a
  `{"stage":"done","suggestions":[...]}` event. `ChatResponse` has
  `mode, answer, suggestions`.
- Retrieval descriptors available: `RetrievedChunk.title` + `source_type`
  (chunks), selected Story Buckets (`decision.buckets` → display names),
  structured modules (`decision.modules`, round 3), connections.

## Architecture

### 1. Markdown rendering (frontend)

- Add deps `react-markdown` + `remark-gfm`.
- New `frontend/src/components/Markdown.tsx`: wraps `<ReactMarkdown remarkPlugins={[remarkGfm]}>` with Tailwind classes for `p/ul/ol/li/strong/em/code/h*` sized to the chat type scale (tight spacing).
- `ChatPage.tsx`: render assistant `message.content` and the live `streamingContent` via `<Markdown>` instead of the raw `<p>`. Keep user bubbles as plain text.

### 2. Restrained formatting (prompt)

- In `_chat_system_prompt`, append: "Format cleanly: short paragraphs; use
  bullet lists only when they genuinely help; avoid heavy bolding and stacked
  headings; no more than one level of bullets."

### 3. Deterministic Sources footer

- **Model:** `SourceRef = {kind: Literal["document","item","bucket","module"], label: str}`. Add `sources: list[SourceRef] = []` to `ChatResponse`.
- **Collection** (`_collect_sources(chunks, decision)` helper): dedup, ordered —
  - chunks → one `SourceRef(kind="document"/"item", label=chunk.title)` per distinct title (cap ~6),
  - each selected bucket → `SourceRef(kind="bucket", label=<display_name>)`,
  - each `decision.modules` entry → `SourceRef(kind="module", label=<Tasks/Plans/Goals/Routines>)`.
  - Fast mode: chunks only (no decision).
- **Wiring:**
  - `respond_to_chat`: compute sources alongside the answer; include in `ChatResponse`.
  - `respond_to_chat_stream`: include `"sources": [...]` in the final `done` event (it already has `decision` + `chunks` in scope).
  - To get chunks/decision into the non-streaming path cleanly, have
    `_build_answer_context` (or a small sibling) also return the `chunks` +
    `decision` it used, or refactor the understanding branch to expose them so
    both paths share `_collect_sources`. (DRY: one collector, both callers.)
- **Frontend:** render a compact **"Sources"** strip beneath the answer — small
  labeled chips grouped/iconned by `kind` — only when `sources` is non-empty.
  Part of the message record (persisted like `suggestions`).

### Error handling

- `_collect_sources` is pure/deterministic; empty retrieval → `[]` → no footer.
- Markdown component must tolerate partial/streaming markdown (react-markdown
  renders incomplete markdown gracefully; acceptable mid-stream).

### Testing

- **Backend:** `_collect_sources` dedups and labels chunks/buckets/modules;
  Understanding answer returns buckets+modules+chunks; Fast returns chunks only;
  empty retrieval → `[]`. `ChatResponse`/`done` event carry `sources`.
- **Frontend (verify via app):** an Understanding answer renders real bold +
  bullets (no literal `*`) and shows a Sources strip; a no-context answer shows
  no strip; streaming answer renders formatted text live.

## Out of scope (deferred)

- Model-generated inline citations / per-fact attribution.
- Markdown rendering for companion bubbles.
- Clickable sources that open the underlying item/document (could come later).
