# Chat Formatting & Sources (Round 4) — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Render chat answers as markdown (no literal asterisks), nudge the prompt toward clean formatting, and append a deterministic "Sources" footer built from what was actually retrieved.

**Architecture:** Frontend gains `react-markdown` + `remark-gfm` to render assistant bubbles. Backend adds a pure `_collect_sources(chunks, decision)` helper feeding a new `sources` field on `ChatResponse` and the SSE `done` event; the prompt gets a formatting nudge. Fast mode reports chunk sources only.

**Tech Stack:** Python/FastAPI/pytest backend; React/TS/Vite frontend (no unit-test harness — verify via app).

**Design doc:** `docs/plans/2026-06-12-chat-formatting-sources-design.md`

**Sequencing:** execute AFTER `docs/plans/2026-06-11-usermodel-chat-refinements.md` (Sources includes round-3 structured modules).

**Conventions:** backend tests `cd backend && python -m pytest` against a test DB; chat tests in `test_chat_actions.py` / `test_chat_streaming.py`.

---

## Phase A — Backend: deterministic Sources

### Task A1: `SourceRef` + `_collect_sources`

**Files:** Modify `backend/app/chat/actions.py`. Test: `backend/tests/test_chat_actions.py`.

**Step 1: Failing test**

```python
from app.chat.actions import _collect_sources, RouteDecision
from app.rag.retrieval import RetrievedChunk


def test_collect_sources_dedups_and_labels() -> None:
    chunks = [
        RetrievedChunk(id="1", life_item_id="a", title="OPT Action Plan", content="x", source_type="document"),
        RetrievedChunk(id="2", life_item_id="a", title="OPT Action Plan", content="y", source_type="document"),
        RetrievedChunk(id="3", life_item_id="b", title="Resume", content="z", source_type="document"),
    ]
    decision = RouteDecision(breadth="broad", buckets=["career"], modules=["tasks"])
    refs = _collect_sources(chunks, decision)
    labels = [(r.kind, r.label) for r in refs]
    assert ("document", "OPT Action Plan") in labels
    assert ("document", "Resume") in labels
    assert labels.count(("document", "OPT Action Plan")) == 1   # deduped
    assert ("bucket", "career") in labels or any(r.kind == "bucket" for r in refs)
    assert any(r.kind == "module" and r.label.lower() == "tasks" for r in refs)


def test_collect_sources_fast_mode_chunks_only() -> None:
    chunks = [RetrievedChunk(id="1", life_item_id="a", title="Resume", content="z", source_type="document")]
    refs = _collect_sources(chunks, None)
    assert all(r.kind in {"document", "item"} for r in refs)
```

**Step 2: Run → fail.** `cd backend && python -m pytest tests/test_chat_actions.py -k collect_sources -v`

**Step 3: Implement**

```python
from pydantic import BaseModel
from typing import Literal

class SourceRef(BaseModel):
    kind: Literal["document", "item", "bucket", "module"]
    label: str

_MODULE_LABELS = {"tasks": "Tasks", "plans": "Plans", "goals": "Goals", "routines": "Routines"}

def _collect_sources(chunks: list, decision=None) -> list[SourceRef]:
    refs: list[SourceRef] = []
    seen: set[tuple[str, str]] = set()
    def add(kind, label):
        label = (label or "").strip()
        if not label or (kind, label.lower()) in seen:
            return
        seen.add((kind, label.lower())); refs.append(SourceRef(kind=kind, label=label))
    for c in (chunks or [])[:6]:
        kind = "document" if getattr(c, "source_type", "") == "document" else "item"
        add(kind, getattr(c, "title", ""))
    if decision is not None:
        for b in getattr(decision, "buckets", []) or []:
            add("bucket", b)
        for m in getattr(decision, "modules", []) or []:
            add("module", _MODULE_LABELS.get(m, m))
    return refs
```

(If bucket display names are preferred over keys, map via the bucket catalog; keys are acceptable for v0.)

**Step 4: Run → pass.** **Step 5: Commit** `git commit -m "feat(chat): deterministic source collection"`

---

### Task A2: Surface `sources` on response + stream

**Files:** Modify `backend/app/chat/actions.py` (`ChatResponse`, `respond_to_chat`, `respond_to_chat_stream`, and expose chunks/decision to the non-streaming path). Test: `test_chat_actions.py`, `test_chat_streaming.py`.

**Step 1: Failing test**

```python
def test_chat_response_includes_sources(tmp_path) -> None:
    from app.chat.actions import respond_to_chat, ChatRequest
    # seed a chunk-producing item so retrieval returns something, or assert sources is a list
    resp = respond_to_chat(ChatRequest(session_id="s1", mode="understanding", message="hello"))
    assert isinstance(resp.sources, list)


def test_stream_done_includes_sources() -> None:
    from app.chat.actions import respond_to_chat_stream, ChatRequest
    events = list(respond_to_chat_stream(ChatRequest(session_id="s2", mode="fast", message="hi")))
    assert "sources" in events[-1]
```

**Step 2: Run → fail.**

**Step 3: Implement**
- `ChatResponse`: add `sources: list[SourceRef] = []`.
- Refactor the understanding context builder so both paths can reach the `chunks` + `decision` used (e.g., `_build_answer_context` returns `(context, chunks, decision)` or add a sibling helper); keep Fast returning its chunks. Compute `sources = _collect_sources(chunks, decision_or_None)`.
- `respond_to_chat`: include `sources` in the returned `ChatResponse` (and persist on the assistant message alongside `suggestions` if messages store extra data).
- `respond_to_chat_stream`: add `"sources": [s.model_dump() for s in sources]` to the final `done` event.

**Step 4: Run → pass.** Run full `cd backend && python -m pytest`. **Step 5: Commit** `git commit -m "feat(chat): return sources on response and stream"`

---

### Task A3: Formatting nudge in the system prompt

**Files:** Modify `backend/app/chat/actions.py` (`_chat_system_prompt`). Test: `test_chat_actions.py`.

**Step 1: Failing test**

```python
def test_system_prompt_mentions_clean_formatting() -> None:
    from app.chat.actions import _chat_system_prompt
    p = _chat_system_prompt("understanding").lower()
    assert "bullet" in p or "format" in p
```

**Step 2: Run → fail. Step 3:** append to both mode prompts: "Format cleanly: short paragraphs; use bullet lists only when they genuinely help; avoid heavy bolding and stacked headings; at most one bullet level." **Step 4: pass. Step 5:** `git commit -m "feat(chat): restrained formatting guidance"`

---

## Phase B — Frontend (verify via app)

### Task B1: Markdown component + deps
- `cd frontend && npm install react-markdown remark-gfm`.
- Create `frontend/src/components/Markdown.tsx` wrapping `ReactMarkdown` with `remarkGfm` and Tailwind classes (tight `p/ul/li/strong/em/code/h*`).
- Verify `npx tsc --noEmit`. Commit `feat(frontend): markdown renderer component`.

### Task B2: Render answers as markdown
- `ChatPage.tsx`: replace the raw assistant `<p className="whitespace-pre-wrap">{message.content}</p>` (≈line 356) and the streaming `<p>` (≈line 405) with `<Markdown>{content}</Markdown>`. Leave user bubbles plain.
- Verify in-app: a multi-bullet answer renders real bullets/bold, **no literal `*`**, including while streaming. Commit `feat(chat): render assistant answers as markdown`.

### Task B3: Sources footer
- Extend the chat API client + message type with `sources` (from `/chat/respond`, the stream `done` event, and persisted history).
- `ChatPage.tsx`: under each assistant answer with `sources.length`, render a compact "Sources" strip — small chips labeled by `kind` (e.g. doc/bucket/module icon + label).
- Verify in-app: "what do you know about me?" shows a Sources strip; a generic answer with no retrieval shows none. Commit `feat(chat): sources footer`.

---

## Phase C — Final verification

### Task C1: Suite + smoke
1. `cd backend && python -m pytest` → green. `cd frontend && npx tsc --noEmit` → clean.
2. Rebuild `docker compose up --build`. Ask "what do you know about me?" and "what should I focus on today?" → clean formatting (no stars), tidy Sources footer reflecting the buckets/modules/documents used; Fast mode shows chunk sources only.
3. **REQUIRED SUB-SKILL:** superpowers:requesting-code-review, then superpowers:finishing-a-development-branch.

---

## Notes & deferred
- Inline per-fact citations; clickable sources opening the item/document; markdown for companion bubbles.
