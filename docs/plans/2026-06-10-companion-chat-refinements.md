# Companion + Chat Refinements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refine the Curious Companion (conversation lifecycle, on-demand light questions, volunteered-info-to-Logs, end controls) and the main Chat (suppress bogus capture cards on questions; real SSE streaming with live status).

**Architecture:** Extend the existing companion session model with an open/closed `session_state`; route volunteered captures to real Log Life Items (`review=False`) while keeping session-end synthesis for user-model enrichment; add an on-demand ask endpoint and a stricter, conversational question prompt; guard chat capture detection against questions; add streaming LLM + an SSE chat endpoint emitting pipeline stage events and answer deltas, with the non-streaming path as fallback.

**Tech Stack:** Python 3 / FastAPI / psycopg / Gemini (`google.genai`) backend; pytest (LLM auto-disabled under pytest → fallbacks are default; monkeypatch to test LLM paths). React + TypeScript + Vite frontend (no unit-test harness — verify via the app).

**Design doc:** `docs/plans/2026-06-10-companion-chat-refinements-design.md`

**Conventions:** see `docs/plans/2026-06-09-curious-companion.md` header. Run backend tests with `cd backend && python -m pytest` against a test DB (DATABASE_URL containing "test"). Companion tests live in `backend/tests/test_companion.py`; reuse its `_ready_companion(tmp_path)` helper. Chat tests in `backend/tests/test_chat_actions.py`.

---

## Phase A — Companion conversation lifecycle

### Task A1: Session state open/closed; open-session lookup

**Files:**
- Modify: `backend/app/modules/companion.py` (`get_or_create_companion_session`, `end_companion_session`)
- Test: `backend/tests/test_companion.py`

**Step 1: Write the failing test**

```python
from app.modules.companion import (
    get_or_create_companion_session, end_companion_session, record_user_turn,
)


def test_ending_closes_session_and_opens_fresh_one(tmp_path) -> None:
    _ready_companion(tmp_path)
    first = get_or_create_companion_session()
    record_user_turn(first["id"], "My EAD card was approved today")

    end_companion_session()

    second = get_or_create_companion_session()
    assert second["id"] != first["id"]
    assert second["payload"]["session_state"] == "open"
    # First session is now closed.
    from app.lifecycle import get_life_item
    assert get_life_item(first["id"])["payload"]["session_state"] == "closed"
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py -k ending_closes -v`
Expected: FAIL (singleton returns same id; no `session_state`).

**Step 3: Write minimal implementation**

- In `get_or_create_companion_session`, add `AND li.payload ->> 'session_state' = 'open'` to the SELECT; set `"session_state": "open"` in the create payload.
- In `end_companion_session`, after synth+weave, `UPDATE life_items SET payload = jsonb_set(payload, '{session_state}', '"closed"'), updated_at = now() WHERE id = %s` for the current session.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py -k ending_closes -v`
Expected: PASS. Also run full companion suite: `cd backend && python -m pytest tests/test_companion.py -v`.

**Step 5: Commit**

```bash
git add backend/app/modules/companion.py backend/tests/test_companion.py
git commit -m "feat(companion): open/closed session lifecycle with rotation on end"
```

---

### Task A2: Typed end-intent ends the conversation gracefully

**Files:**
- Modify: `backend/app/modules/companion.py` (`respond_to_user_turn`)
- Test: `backend/tests/test_companion.py`

**Step 1: Write the failing test**

```python
from app.modules.companion import respond_to_user_turn, get_or_create_companion_session
from app.lifecycle import get_life_item


def test_typed_goodbye_ends_session(tmp_path) -> None:
    _ready_companion(tmp_path)
    session = get_or_create_companion_session()
    reply = respond_to_user_turn("talk to you later")
    assert reply["kind"] == "ended"
    assert get_life_item(session["id"])["payload"]["session_state"] == "closed"
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py -k typed_goodbye -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

Add near the top of `respond_to_user_turn`, before recording the turn:

```python
_END_MARKERS = ("bye", "goodbye", "talk to you later", "talk later", "that's all", "thats all", "gotta go", "see you")

def _is_end_intent(text: str) -> bool:
    cleaned = text.strip().lower().rstrip("!.")
    return cleaned in _END_MARKERS or cleaned.startswith(("bye", "talk to you later", "talk later"))
```

In `respond_to_user_turn`: if `_is_end_intent(text)`, record the user turn (transcript only — it is filler, no log), insert a short sign-off assistant message (`meta={"kind":"signoff"}`, content via persona `generate_text` with fallback `"Talk soon — take care."`), call `end_companion_session()`, and return `{"kind":"ended","message":<signoff>}`.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py -k typed_goodbye -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/modules/companion.py backend/tests/test_companion.py
git commit -m "feat(companion): typed end-intent gracefully ends conversation"
```

---

## Phase B — On-demand ask + conversational question style

### Task B1: Conversational question generation prompt + Skip support

**Files:**
- Modify: `backend/app/modules/companion.py` (`generate_companion_question`, `_companion_ask`)
- Test: `backend/tests/test_companion.py`

**Step 1: Write the failing test**

```python
import app.modules.companion as companion


def test_question_generation_prompt_constrains_style(tmp_path) -> None:
    _ready_companion(tmp_path)
    captured = {}
    def fake_generate_json(prompt, *, system, **k):
        captured["system"] = system
        return {"opening_message": "What's been the best part of your week?",
                "target_bucket_key": "habits", "quick_replies": [{"id": "a", "label": "Work"}],
                "rationale": "light"}
    monkey = companion
    import pytest
    # use monkeypatch fixture instead in real test signature

def test_question_style_system_prompt(tmp_path, monkeypatch) -> None:
    _ready_companion(tmp_path)
    captured = {}
    def fake(prompt, *, system, **k):
        captured["system"] = system
        return {"opening_message": "What's been good lately?", "target_bucket_key": "habits",
                "quick_replies": [{"id": "a", "label": "Work"}], "rationale": "light"}
    monkeypatch.setattr(companion, "generate_json", fake)
    q = companion.generate_companion_question(exclude_bucket=None)
    assert "conversational" in captured["system"].lower() or "short" in captured["system"].lower()
    assert q["quick_replies"]
```

(Delete the scratch first function; keep `test_question_style_system_prompt`.)

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py -k question_style -v`
Expected: FAIL (the style language and `exclude_bucket` param are missing).

**Step 3: Write minimal implementation**

- Add an explicit style instruction to the generation `system` prompt: *"Ask ONE small, concrete, conversational question, answerable in a few words or more — never an essay prompt. Offer 2–4 short quick-reply options when natural; the person can also type freely."*
- Add `exclude_bucket: str | None = None` param to `generate_companion_question`; when set, instruct the model to avoid that bucket and, in the foundational fallback, skip a pending question whose `target_bucket_key == exclude_bucket` if possible.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py -k question_style -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/modules/companion.py backend/tests/test_companion.py
git commit -m "feat(companion): conversational question style + exclude_bucket for skip"
```

---

### Task B2: On-demand ask + skip endpoints

**Files:**
- Modify: `backend/app/modules/companion.py` (add `ask_companion_question()`, `skip_companion_question(bucket_key)`)
- Modify: `backend/app/api/curious.py` (routes)
- Test: `backend/tests/test_companion.py`

**Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient
from app.main import app
from app.db import connect


def test_on_demand_ask_persists_question(tmp_path) -> None:
    _ready_companion(tmp_path)
    client = TestClient(app)
    resp = client.post("/modules/curious/companion/ask")
    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"]["kind"] == "question"
    assert body["reply"]["message"]
    # Persisted as an assistant question on the open session.
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM companion_messages WHERE role='assistant' AND meta->>'kind'='question'")
            assert cur.fetchone()["c"] == 1
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py -k on_demand_ask -v`
Expected: FAIL (route 404).

**Step 3: Write minimal implementation**

- `ask_companion_question() -> CompanionMessageResponse`: `session = get_or_create_companion_session(); reply = _companion_ask(session["id"]); return CompanionMessageResponse(reply=CompanionReply(**reply))`.
- `skip_companion_question(bucket_key: str | None) -> CompanionMessageResponse`: `_companion_ask(session["id"], exclude_bucket=bucket_key)` (thread `exclude_bucket` through `_companion_ask` → `generate_companion_question`).
- Routes in `api/curious.py`:
  - `POST /companion/ask` → `ask_companion_question()`
  - `POST /companion/skip` (`{bucket_key?: str}`) → `skip_companion_question(...)`

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py -k on_demand_ask -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/modules/companion.py backend/app/api/curious.py backend/tests/test_companion.py
git commit -m "feat(companion): on-demand ask + skip endpoints"
```

---

## Phase C — Volunteered info → Logs (still enriches user model)

### Task C1: Route meaningful captures to Log items; drop curious_capture + timeline

**Files:**
- Modify: `backend/app/modules/companion.py` (`record_user_turn`, `synthesize_companion_session`, `get_companion_state`, remove `CompanionTimelineEntry` + `CompanionState.timeline`)
- Test: `backend/tests/test_companion.py`

**Step 1: Write the failing test**

```python
from app.modules.companion import record_user_turn, get_or_create_companion_session
from app.db import connect


def test_meaningful_turn_creates_log_not_curious_capture(tmp_path) -> None:
    _ready_companion(tmp_path)
    session = get_or_create_companion_session()
    record_user_turn(session["id"], "My EAD card was approved today")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM life_items WHERE item_type='curious_capture'")
            assert cur.fetchone()["c"] == 0
            cur.execute(
                """
                SELECT COUNT(*) AS c FROM life_items li
                JOIN module_instances mi ON mi.id = li.module_instance_id
                WHERE mi.module_id = 'logs' AND li.item_type = 'log'
                """
            )
            assert cur.fetchone()["c"] == 1
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py -k creates_log_not -v`
Expected: FAIL (still creates curious_capture; no log).

**Step 3: Write minimal implementation**

- In `record_user_turn`: after inserting the transcript row, if meaningful:
  ```python
  from app.modules.logs import LogCreate, create_log
  create_log(
      LogCreate(
          text=text,
          request_id=f"companion-capture-{message_id}",
          source={"kind": "companion_capture", "session_id": str(session_id)},
      ),
      review=False,
  )
  ```
  Remove the `curious_capture` `create_life_item` + knowledge_chunks + status-update block.
- In `synthesize_companion_session`: replace the `curious_capture` lookups. `link_item_id` should be the most recent companion-sourced Log id for this session (query `life_items` joined to logs where `source ->> 'session_id' = session_id`), else fall back to `session_id`. Drop the trailing `UPDATE ... curious_capture ...` statement.
- In `get_companion_state`: remove the `curious_capture` query and `timeline`. Delete `CompanionTimelineEntry` and the `timeline` field from `CompanionState`.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py -k creates_log_not -v`
Expected: PASS

**Step 6: Confirm enrichment still works**

Re-run the existing synthesis/weave tests:
Run: `cd backend && python -m pytest tests/test_companion.py -k "synthesis or weave_merges" -v`
Expected: PASS (bucket updates still queued and merged).

**Step 7: Commit**

```bash
git add backend/app/modules/companion.py backend/tests/test_companion.py
git commit -m "feat(companion): volunteered info becomes Logs, still enriches user model"
```

---

## Phase D — Chat: suppress capture cards on questions

### Task D1: Question/lookup guard in capture detection

**Files:**
- Modify: `backend/app/chat/actions.py` (`_detect_capture_proposals`)
- Test: `backend/tests/test_chat_actions.py`

**Step 1: Write the failing test**

```python
from app.chat.actions import _detect_capture_proposals


def test_questions_do_not_produce_capture_suggestions() -> None:
    assert _detect_capture_proposals("what's my EAD start date?") == []
    assert _detect_capture_proposals("when is my appointment?") == []


def test_explicit_add_still_works_inside_a_question_form() -> None:
    proposals = _detect_capture_proposals("add this to tasks: renew passport")
    assert proposals and proposals[0].module_id == "tasks"
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_chat_actions.py -k capture_suggestions -v`
Expected: FAIL (question currently yields a suggestion).

**Step 3: Write minimal implementation**

In `_detect_capture_proposals`, after `_detect_explicit` (which returns first if matched), add a guard before suggested detection:

```python
def _is_question_or_lookup(message: str) -> bool:
    text = message.strip().lower()
    if text.endswith("?"):
        return True
    first = text.split()[0] if text.split() else ""
    return first in {
        "what", "when", "where", "who", "why", "how", "which",
        "is", "are", "do", "does", "did", "can", "could", "should", "will",
    }
```

```python
def _detect_capture_proposals(message: str) -> list[DetectedProposal]:
    explicit = _detect_explicit(message)
    if explicit:
        return [explicit]
    if _is_question_or_lookup(message):
        return []
    suggested = _detect_suggested_with_llm(message) or _detect_suggested(message)
    return [suggested] if suggested else []
```

Also tighten the `_detect_suggested_with_llm` system prompt: add "Never propose for questions or information lookups."

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_chat_actions.py -k capture_suggestions -v`
Expected: PASS. Run the full chat suite: `cd backend && python -m pytest tests/test_chat_actions.py -v`.

**Step 5: Commit**

```bash
git add backend/app/chat/actions.py backend/tests/test_chat_actions.py
git commit -m "fix(chat): suppress capture suggestions on questions/lookups"
```

---

## Phase E — Chat: real SSE streaming

### Task E1: Streaming text generation helper

**Files:**
- Modify: `backend/app/llm/client.py` (add `generate_text_stream`)
- Test: `backend/tests/test_chat_streaming.py` (new)

**Step 1: Write the failing test**

```python
# backend/tests/test_chat_streaming.py
from __future__ import annotations
import pytest
from app.llm import LLMUnavailable
from app.llm.client import generate_text_stream


def test_generate_text_stream_raises_when_disabled() -> None:
    # LLM disabled under pytest.
    with pytest.raises(LLMUnavailable):
        list(generate_text_stream("hi", system="s"))
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_chat_streaming.py -k raises_when_disabled -v`
Expected: FAIL (function not defined).

**Step 3: Write minimal implementation**

```python
from collections.abc import Iterator

def generate_text_stream(
    prompt: str, *, system: str, temperature: float = 0.5, max_output_tokens: int = 1200,
) -> Iterator[str]:
    if not llm_enabled():
        raise LLMUnavailable("LLM calls are disabled")
    client = genai.Client(api_key=settings.gemini_api_key)
    stream = client.models.generate_content_stream(
        model=_normalize_model_name(settings.gemini_chat_model),
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system, temperature=temperature, max_output_tokens=max_output_tokens,
        ),
    )
    for chunk in stream:
        text = getattr(chunk, "text", None)
        if text:
            yield text
```

Export from `app/llm/__init__.py` if it re-exports symbols (check and add `generate_text_stream`).

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_chat_streaming.py -k raises_when_disabled -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/llm/client.py backend/app/llm/__init__.py backend/tests/test_chat_streaming.py
git commit -m "feat(chat): streaming text generation helper"
```

---

### Task E2: Streaming responder yields stage events + answer + done

**Files:**
- Modify: `backend/app/chat/actions.py` (add `respond_to_chat_stream(request)`)
- Test: `backend/tests/test_chat_streaming.py`

**Step 1: Write the failing test**

```python
from app.chat.actions import respond_to_chat_stream
from app.chat import ChatRequest


def test_stream_emits_stages_then_answer_and_done(tmp_path) -> None:
    # LLM disabled under pytest → deterministic fallback path; must still terminate with done.
    events = list(respond_to_chat_stream(ChatRequest(session_id="s1", mode="understanding", message="hello")))
    stages = [e["stage"] for e in events]
    assert stages[0] in {"routing", "retrieving"}
    assert "writing" in stages
    assert any(e["stage"] == "answer" for e in events)
    assert stages[-1] == "done"
    done = events[-1]
    assert "suggestions" in done
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_chat_streaming.py -k emits_stages -v`
Expected: FAIL (function not defined).

**Step 3: Write minimal implementation**

`respond_to_chat_stream(request)` mirrors `respond_to_chat` persistence (upsert session, insert user message, run guarded `_detect_capture_proposals`/`_should_surface`/`_persist_preview`) but is a generator:

```python
def respond_to_chat_stream(request):
    # persist user message (reuse helpers from respond_to_chat)
    ...
    detected = _detect_capture_proposals(request.message)
    suggestions = [_persist_preview(...) for ... if _should_surface(...)]

    if request.mode == "understanding":
        yield {"stage": "routing"}
        decision = _route_and_classify(request.message)
        yield {"stage": "retrieving"}
        chunks = _understanding_retrieval(request.message, decision, ...)
        yield {"stage": "reading_story"}
        context = _build_answer_context_from(decision, chunks, request.message)  # refactor to reuse
    else:
        yield {"stage": "retrieving"}
        context = _build_answer_context(request.mode, request.message)

    yield {"stage": "writing"}
    system = _chat_system_prompt(request.mode)
    prompt = _answer_prompt(request, context, suggestions)  # extract the existing prompt builder
    answer_parts = []
    try:
        for delta in generate_text_stream(prompt, system=system, temperature=0.45,
                                          max_output_tokens=2200 if request.mode=="understanding" else 1300):
            answer_parts.append(delta)
            yield {"stage": "answer", "delta": delta}
        answer = "".join(answer_parts)
    except (LLMUnavailable, Exception):
        answer = _fallback_context_answer(request.mode, context, bool(suggestions))
        yield {"stage": "answer", "delta": answer}

    # persist assistant message (reuse insert_chat_message)
    yield {"stage": "done", "suggestions": [s.model_dump(mode="json") for s in suggestions]}
```

Refactor minimally: extract the prompt-building block from `_generate_chat_answer` into `_answer_prompt(...)` and reuse it in both paths (DRY). Keep `_build_answer_context` usable for the fast path; for understanding, reuse the already-computed `decision`/`chunks` to avoid double retrieval.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_chat_streaming.py -k emits_stages -v`
Expected: PASS. Re-run `cd backend && python -m pytest tests/test_chat_actions.py -v` to confirm no regression from the refactor.

**Step 5: Commit**

```bash
git add backend/app/chat/actions.py backend/tests/test_chat_streaming.py
git commit -m "feat(chat): streaming responder with pipeline stage events"
```

---

### Task E3: SSE endpoint

**Files:**
- Modify: `backend/app/api/chat.py`
- Modify: `backend/app/chat/__init__.py` (export `respond_to_chat_stream` if needed)
- Test: `backend/tests/test_chat_streaming.py`

**Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient
from app.main import app
import json


def test_sse_endpoint_streams_events(tmp_path) -> None:
    client = TestClient(app)
    with client.stream("POST", "/chat/respond/stream",
                        json={"session_id": "s1", "mode": "fast", "message": "hi"}) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        payloads = []
        for line in r.iter_lines():
            if line and line.startswith("data:"):
                payloads.append(json.loads(line[len("data:"):].strip()))
    assert payloads[-1]["stage"] == "done"
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_chat_streaming.py -k sse_endpoint -v`
Expected: FAIL (404).

**Step 3: Write minimal implementation**

```python
from fastapi.responses import StreamingResponse
import json
from app.chat import respond_to_chat_stream

@router.post("/respond/stream")
def respond_to_chat_stream_endpoint(payload: ChatRequest) -> StreamingResponse:
    def gen():
        for event in respond_to_chat_stream(payload):
            yield f"data: {json.dumps(event)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_chat_streaming.py -k sse_endpoint -v`
Expected: PASS. Then full backend suite: `cd backend && python -m pytest`.

**Step 5: Commit**

```bash
git add backend/app/api/chat.py backend/app/chat/__init__.py backend/tests/test_chat_streaming.py
git commit -m "feat(chat): SSE streaming endpoint"
```

---

## Phase F — Frontend (verify via the app; no unit-test harness)

> Verify each task by running the app with the `/run` skill and exercising the flow; screenshot with `mcp__Claude_Preview__preview_screenshot`.

### Task F1: API client — companion ask/skip + chat stream

**Files:** Modify `frontend/src/lib/api.ts`

**Steps:**
- Add `askCompanionQuestion()`, `skipCompanionQuestion(bucketKey?)` calling the new endpoints.
- Add `streamChat({session_id, mode, message}, handlers)` that POSTs to `/chat/respond/stream`, reads `response.body` via `getReader()`, splits on `\n\n`, parses `data:` JSON, and invokes `onStage`, `onAnswerDelta`, `onDone(suggestions)`; on any error, fall back to `respondToChat`.
- Remove `timeline` from the companion state type.
- Verify: `cd frontend && npx tsc --noEmit` clean.

**Commit:** `git commit -m "feat(frontend): companion ask/skip + chat streaming client"`

---

### Task F2: Curious page — lifecycle controls, ask button, remove timeline

**Files:** Modify `frontend/src/pages/CuriousPage.tsx`

**Steps:**
- Add an **"Ask me something"** button → `askCompanionQuestion()` → append the question.
- Render `Skip` / `Talk later` quick chips on companion question turns: `Skip` → `skipCompanionQuestion(targetBucketKey)`; `Talk later` → `endCompanionSession()` then clear the thread to empty.
- Add a persistent **"Done"** control that ends + clears the thread.
- On `ended`/`signoff` reply kind, clear the visible thread (fresh session).
- **Remove** the captured-moments timeline + "N captured moments" counter.
- Keep quick-reply chips for question options; free-text input always present.
- Verify: send updates, end via "Talk later", confirm fresh empty thread; click "Ask me something" → a light question appears.

**Commit:** `git commit -m "feat(companion): lifecycle controls + ask button; drop timeline"`

---

### Task F3: Chat page — live streaming status + answer

**Files:** Modify `frontend/src/pages/ChatPage.tsx`

**Steps:**
- Switch send to `streamChat(...)`. Map stages to friendly labels: `routing→"Reading your story"`, `retrieving→"Searching your knowledge"`, `reading_story→"Pulling it together"`, `writing→"Writing"`. Show a live status line on the pending assistant bubble.
- Append `answer` deltas to the streaming assistant message; on `done`, attach `suggestions` and finalize.
- On stream error, fall back to the existing `respondToChat` path.
- Verify: ask "what's my EAD start date?" → status line cycles, answer streams in, **no** bogus save card; ask "I need to renew my passport" → a suggestion still appears.

**Commit:** `git commit -m "feat(chat): live streaming status + streamed answer"`

---

## Phase G — Final verification

### Task G1: Full suite + manual smoke

**Steps:**
1. `cd backend && python -m pytest` → all green.
2. `cd frontend && npx tsc --noEmit` → clean.
3. Manual smoke via `/run`:
   - Companion: volunteered update → short ack, appears in **Logs** (not Curious); "Ask me something" → light question with chips + free text; "Talk later" → thread resets; reopening still works.
   - Chat: question → streamed answer + live status, no bogus card; explicit/real intent → suggestion still shows.
   - User model still enriched: end a companion conversation, check `/user-model` for the woven fact.
4. **REQUIRED SUB-SKILL:** superpowers:requesting-code-review before merge, then superpowers:finishing-a-development-branch.

**Commit:** none (verification only).

---

## Notes & deferred (do NOT build now)

- Past-conversation browser / history UI.
- Notifications, background scheduler, multi-question batching.
- Retiring Logs or Curious onboarding questions.
