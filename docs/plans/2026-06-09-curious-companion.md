# Curious → Companion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Evolve the Curious module into a persona-driven conversational companion that proactively checks in, asks targeted questions and receives volunteered updates, harvests raw-per-turn + synthesizes at session end into the user model, and subsumes Logs via a dated timeline.

**Architecture:** Reuse Curious's existing "question → Life Item + Knowledge Chunk + Bucket Update → Story Weave" pipeline. Add a companion **session** (a `curious_session` Life Item with `session_type='companion'`), a `companion_messages` transcript table, `curious_capture` Life Items for meaningful turns (the raw + timeline records), an LLM question-generation call (activating the dormant `dynamic` tier) with deterministic fallback, a meaningfulness gate, a session-end synthesis pass that queues `curious_companion`-tagged Bucket Updates, a lazy due-check for proactive check-ins, and a new conversational frontend. Logs module stays running in parallel.

**Tech Stack:** Python 3 / FastAPI / psycopg (raw SQL) / pgvector backend; pytest (LLM auto-disabled under pytest, so fallbacks are the default test path; monkeypatch `generate_json` to test LLM paths). React + TypeScript + Vite + framer-motion frontend (no unit-test harness — verify via the app).

**Design doc:** `docs/plans/2026-06-09-curious-companion-design.md`

**Conventions to mirror:**
- DB access via `from app.db import transaction` / `connect`; raw SQL with `%s` params; `psycopg.types.json.Jsonb` for jsonb.
- LLM calls: `from app.llm import LLMUnavailable, generate_json, generate_text`, always wrapped in `try/except (LLMUnavailable, Exception)` with a deterministic fallback.
- Life Items created via `from app.lifecycle import create_life_item, get_life_item, set_lifecycle_status` (returns object with `.created` and `.item`).
- New tables: add DDL to `backend/app/db/bootstrap.py` (the file `ensure_schema()` runs) and add the table name to the `TRUNCATE` list in `backend/tests/conftest.py::_truncate_mutable_tables`.
- Tests live in `backend/tests/test_*.py`; run with `cd backend && python -m pytest`. Tests need a test Postgres DB (DATABASE_URL with "test" in the name). Mirror `test_curious_module.py::_ready` / conftest patterns.

---

## Phase A — Foundations: schema + settings

### Task A1: Add `companion_messages` table

**Files:**
- Modify: `backend/app/db/bootstrap.py` (add DDL near other `CREATE TABLE` statements)
- Modify: `backend/tests/conftest.py:25-52` (add `companion_messages` to the TRUNCATE list, before `life_items`)
- Test: `backend/tests/test_companion.py` (new)

**Step 1: Write the failing test**

```python
# backend/tests/test_companion.py
from __future__ import annotations

from app.db import connect, ensure_schema


def test_companion_messages_table_exists() -> None:
    ensure_schema()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'companion_messages'
                ORDER BY column_name
                """
            )
            columns = {row["column_name"] for row in cur.fetchall()}
    assert {"id", "session_id", "role", "content", "meta", "created_at"} <= columns
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py::test_companion_messages_table_exists -v`
Expected: FAIL (table does not exist → empty column set).

**Step 3: Write minimal implementation**

Add to `backend/app/db/bootstrap.py` alongside the other table DDL:

```sql
CREATE TABLE IF NOT EXISTS companion_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES life_items(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('assistant', 'user')),
    content TEXT NOT NULL,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_companion_messages_session
    ON companion_messages (session_id, created_at);
```

Add `companion_messages,` to the `TRUNCATE TABLE` list in `conftest.py` (place it before `life_items` so the FK cascade order is safe).

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py::test_companion_messages_table_exists -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/db/bootstrap.py backend/tests/conftest.py backend/tests/test_companion.py
git commit -m "feat(companion): add companion_messages table"
```

---

### Task A2: Add companion settings to the Curious module definition

**Files:**
- Modify: `backend/app/modules/definitions.py` (the `default_settings` dict in the `curious` module def, ~lines 40-48)
- Test: `backend/tests/test_companion.py`

**Step 1: Write the failing test**

```python
def test_curious_module_has_companion_defaults() -> None:
    from app.modules import sync_module_registry
    from app.db import connect

    ensure_schema()
    sync_module_registry()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT default_settings FROM modules WHERE id = 'curious'")
            settings = cur.fetchone()["default_settings"]

    assert settings["companion_enabled"] is True
    assert settings["companion_persona_preset"] == "warm"
    assert settings["companion_persona_override"] == ""
    assert settings["companion_checkins_per_day"] == 0
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py::test_curious_module_has_companion_defaults -v`
Expected: FAIL with KeyError on `companion_enabled`.

**Step 3: Write minimal implementation**

Add to the curious `default_settings` dict in `definitions.py`:

```python
            "companion_enabled": True,
            "companion_persona_preset": "warm",
            "companion_persona_override": "",
            "companion_checkins_per_day": 0,
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py::test_curious_module_has_companion_defaults -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/modules/definitions.py backend/tests/test_companion.py
git commit -m "feat(companion): add companion settings defaults to Curious module"
```

---

## Phase B — Persona assembly

### Task B1: Persona preset + override → system prompt

**Files:**
- Create: `backend/app/modules/companion.py` (new — holds all companion logic)
- Test: `backend/tests/test_companion.py`

**Step 1: Write the failing test**

```python
from app.modules.companion import build_persona_prompt


def test_persona_prompt_includes_preset_and_override() -> None:
    prompt = build_persona_prompt(preset="coach", override="Call me by my first name.")
    assert "coach" in prompt.lower() or "push" in prompt.lower()
    assert "Call me by my first name." in prompt


def test_persona_prompt_unknown_preset_falls_back_to_warm() -> None:
    prompt = build_persona_prompt(preset="nonsense", override="")
    assert prompt  # non-empty
    assert "warm" in prompt.lower() or "encourag" in prompt.lower()
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py -k persona -v`
Expected: FAIL (module/function does not exist).

**Step 3: Write minimal implementation**

```python
# backend/app/modules/companion.py
"""Curious Companion: conversational, persona-driven user-model harvesting."""

from __future__ import annotations

PERSONA_PRESETS: dict[str, str] = {
    "warm": "You are warm, encouraging, and gentle. Celebrate small wins briefly.",
    "coach": "You are a focused coach. You encourage but also gently push for clarity and follow-through.",
    "gentle": "You are calm and low-pressure. Never nag; give the person plenty of space.",
    "direct": "You are concise and direct. No fluff; respect the person's time.",
}

_COMPANION_BASE = (
    "You are Orbit's companion: a personal presence getting to know one person over time. "
    "Keep every turn short — a sentence or two. Never produce lists, essays, or code. "
    "Either ask one targeted question, or warmly acknowledge what the person just shared. "
    "Do not interrogate. Use what you know to make the person feel understood."
)


def build_persona_prompt(*, preset: str, override: str) -> str:
    style = PERSONA_PRESETS.get(preset, PERSONA_PRESETS["warm"])
    parts = [_COMPANION_BASE, style]
    if override.strip():
        parts.append(f"Additional instructions from the person: {override.strip()}")
    return " ".join(parts)
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py -k persona -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/modules/companion.py backend/tests/test_companion.py
git commit -m "feat(companion): persona preset + override prompt assembly"
```

---

## Phase C — Conversation: session, transcript, meaningfulness gate, raw capture

### Task C1: Get-or-create the companion session

**Files:**
- Modify: `backend/app/modules/companion.py`
- Test: `backend/tests/test_companion.py`

**Step 1: Write the failing test**

Use the `_ready` helper pattern from `test_curious_module.py` (copy it into `test_companion.py`, or import story-bucket/goal seeders). Minimal:

```python
from app.modules.companion import get_or_create_companion_session


def test_companion_session_is_stable(tmp_path) -> None:
    _ready_companion(tmp_path)
    first = get_or_create_companion_session()
    second = get_or_create_companion_session()
    assert first["id"] == second["id"]
    assert first["payload"]["session_type"] == "companion"
```

Add a `_ready_companion(tmp_path)` mirroring `test_curious_module.py::_ready` (ensure_schema, sync_module_registry, delete curious life items, ensure_story_buckets(tmp_path, conn), ensure_goals_seed(tmp_path)).

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py -k session_is_stable -v`
Expected: FAIL (function not defined).

**Step 3: Write minimal implementation**

Mirror `curious.py::_get_or_create_onboarding_session`, but with `session_type='companion'` and `request_id="companion-session"`. Mark its lifecycle side-statuses not-needed (reuse the pattern; you may import `_mark_session_lifecycle_not_needed` from curious or inline an equivalent). Return `result.item` / existing row.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py -k session_is_stable -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/modules/companion.py backend/tests/test_companion.py
git commit -m "feat(companion): stable companion session life item"
```

---

### Task C2: Meaningfulness gate (deterministic fallback first)

**Files:**
- Modify: `backend/app/modules/companion.py`
- Test: `backend/tests/test_companion.py`

**Step 1: Write the failing test**

```python
from app.modules.companion import is_meaningful_reply


def test_meaningfulness_gate_skips_filler() -> None:
    # Under pytest the LLM is disabled, so this exercises the deterministic fallback.
    assert is_meaningful_reply("ok") is False
    assert is_meaningful_reply("thanks!") is False
    assert is_meaningful_reply("My EAD card was approved today") is True
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py -k meaningfulness -v`
Expected: FAIL (function not defined).

**Step 3: Write minimal implementation**

```python
from app.llm import LLMUnavailable, generate_json

_FILLER = {"ok", "okay", "k", "thanks", "thank you", "thx", "yes", "no", "sure", "yep", "nope", "cool", "great", "lol", "haha"}


def is_meaningful_reply(text: str) -> bool:
    cleaned = text.strip().lower().rstrip("!.")
    if not cleaned:
        return False
    try:
        data = generate_json(
            f'Reply:\n"{text}"\n\nReturn JSON: {{"meaningful": bool}}. '
            "meaningful=true only if the reply states a fact, update, feeling, or "
            "preference worth remembering about the person; false for greetings/acks/filler.",
            system="You judge whether a chat reply carries durable signal about the person. Return only JSON.",
            temperature=0.0,
            max_output_tokens=80,
        )
        return bool(data.get("meaningful", False))
    except (LLMUnavailable, Exception):
        # Deterministic fallback: filler words / very short replies are not meaningful.
        if cleaned in _FILLER:
            return False
        return len(cleaned.split()) >= 3
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py -k meaningfulness -v`
Expected: PASS

**Step 6: Add an LLM-path test (monkeypatch)**

```python
def test_meaningfulness_gate_uses_llm_when_available(monkeypatch) -> None:
    import app.modules.companion as companion
    monkeypatch.setattr(companion, "generate_json", lambda *a, **k: {"meaningful": True})
    assert companion.is_meaningful_reply("ok") is True  # LLM overrides filter
```

Run: `cd backend && python -m pytest tests/test_companion.py -k meaningfulness -v` → PASS

**Step 7: Commit**

```bash
git add backend/app/modules/companion.py backend/tests/test_companion.py
git commit -m "feat(companion): meaningfulness gate with deterministic fallback"
```

---

### Task C3: Record a user turn — transcript + raw capture for meaningful replies

**Files:**
- Modify: `backend/app/modules/companion.py`
- Test: `backend/tests/test_companion.py`

**Step 1: Write the failing test**

```python
from app.db import connect
from app.modules.companion import record_user_turn, get_or_create_companion_session


def test_meaningful_user_turn_creates_capture_and_chunk(tmp_path) -> None:
    _ready_companion(tmp_path)
    session = get_or_create_companion_session()

    record_user_turn(session["id"], "My EAD card was approved today")

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role, content FROM companion_messages WHERE session_id = %s",
                (session["id"],),
            )
            messages = cur.fetchall()
            cur.execute(
                "SELECT COUNT(*) AS c FROM life_items WHERE item_type = 'curious_capture'"
            )
            captures = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM knowledge_chunks")
            chunks = cur.fetchone()["c"]

    assert any(m["role"] == "user" and "EAD" in m["content"] for m in messages)
    assert captures == 1
    assert chunks >= 1


def test_filler_user_turn_records_message_but_no_capture(tmp_path) -> None:
    _ready_companion(tmp_path)
    session = get_or_create_companion_session()
    record_user_turn(session["id"], "thanks!")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM life_items WHERE item_type = 'curious_capture'")
            assert cur.fetchone()["c"] == 0
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py -k user_turn -v`
Expected: FAIL (function not defined).

**Step 3: Write minimal implementation**

`record_user_turn(session_id, text)`:
1. Insert a `companion_messages` row (`role='user'`, `content=text`).
2. If `is_meaningful_reply(text)`:
   - `create_life_item(module_id="curious", item_type="curious_capture", title=_derive_title(text), description=text, payload={"text": text, "session_id": str(session_id)}, source={"kind": "companion_capture", "session_id": str(session_id)}, request_id=f"companion-capture-{<message_id>}")`. (Use the inserted message id to make the request_id idempotent.)
   - Insert a `knowledge_chunks` row (`source_type='companion_capture'`, content=text, metadata jsonb with session_id).
   - Mark the capture Life Item `chunk_status='complete'`, `bucket_update_status='pending'`, `connection_status='complete'` (bucket update happens at synthesis time).

Reuse `_derive_title` (import from `app.modules.curious` or duplicate the small helper). Keep all writes for the meaningful branch inside one `transaction()`.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py -k user_turn -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/modules/companion.py backend/tests/test_companion.py
git commit -m "feat(companion): record user turns + raw capture for meaningful replies"
```

---

## Phase D — Companion replies: question generation + bidirectional acknowledgment

### Task D1: Build companion context (user model + goals + tasks/plans + asked-coverage)

**Files:**
- Modify: `backend/app/modules/companion.py`
- Test: `backend/tests/test_companion.py`

**Step 1: Write the failing test**

```python
from app.modules.companion import build_companion_context


def test_companion_context_includes_buckets_and_goals(tmp_path) -> None:
    _ready_companion(tmp_path)
    ctx = build_companion_context()
    assert "Story Buckets" in ctx or "buckets" in ctx.lower()
    assert isinstance(ctx, str) and ctx.strip()
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py -k companion_context -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

Assemble a compact string from:
- Active story buckets: `SELECT stable_key, display_name, description, content FROM story_buckets WHERE status='active'` (truncate content to ~400 chars each).
- Goals: reuse `from app.user_model import list_goals` (title + status + short body).
- Active tasks/plans: lightweight queries — `SELECT title FROM life_items WHERE item_type IN ('task','plan') AND lifecycle_status='active' ORDER BY created_at DESC LIMIT 10`.
- Already-asked coverage: distinct `target_bucket_key` from existing `curious_answer`/`curious_capture` items, so the generator can avoid repetition.

Return the joined string. Keep it under ~2k chars.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py -k companion_context -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/modules/companion.py backend/tests/test_companion.py
git commit -m "feat(companion): assemble companion context from user model/goals/tasks"
```

---

### Task D2: Generate the next companion question (LLM + fallback to foundational queue)

**Files:**
- Modify: `backend/app/modules/companion.py`
- Test: `backend/tests/test_companion.py`

**Step 1: Write the failing test**

```python
from app.modules.companion import generate_companion_question


def test_question_generation_falls_back_to_foundational_when_llm_down(tmp_path) -> None:
    _ready_companion(tmp_path)
    # LLM disabled under pytest → deterministic fallback.
    q = generate_companion_question()
    assert q["opening_message"]
    assert q["target_bucket_key"] in {
        "who_am_i", "goals", "interests_and_works", "career",
        "health", "relationships", "habits", "aspirations",
    }


def test_question_generation_uses_llm_when_available(tmp_path, monkeypatch) -> None:
    _ready_companion(tmp_path)
    import app.modules.companion as companion
    monkeypatch.setattr(
        companion, "generate_json",
        lambda *a, **k: {
            "opening_message": "How did the EAD news land for you?",
            "target_bucket_key": "career",
            "quick_replies": [],
            "rationale": "follow up on milestone",
        },
    )
    q = companion.generate_companion_question()
    assert q["opening_message"] == "How did the EAD news land for you?"
    assert q["target_bucket_key"] == "career"
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py -k question_generation -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

`generate_companion_question()`:
- Build persona (from the curious module-instance settings — read `default_settings` merged with instance settings; a helper `_companion_settings()` that reads the curious module instance row) + `build_companion_context()`.
- One `generate_json` call returning `{opening_message, target_bucket_key, quick_replies, rationale}`. Clamp `target_bucket_key` to `KNOWN_BUCKET_KEYS` (import from `app.chat.actions` or redefine the 8 keys locally).
- **Fallback** on `(LLMUnavailable, Exception)` or invalid output: return the next unanswered foundational question by reusing Curious's queue. Concretely: call `from app.modules.curious import get_curious_page_state`; take `pending_questions[0]` if present and map to `{opening_message: question.question_text, target_bucket_key: question.target_bucket_key, quick_replies: [option dicts], rationale: "foundational fallback"}`. If none pending, return a generic check-in (`opening_message="How are things going today?"`, `target_bucket_key="who_am_i"`, `quick_replies=[]`).

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py -k question_generation -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/modules/companion.py backend/tests/test_companion.py
git commit -m "feat(companion): question generation with foundational fallback"
```

---

### Task D3: Companion reply to a user turn — bidirectional (acknowledge vs ask)

**Files:**
- Modify: `backend/app/modules/companion.py`
- Test: `backend/tests/test_companion.py`

**Step 1: Write the failing test**

```python
from app.modules.companion import respond_to_user_turn
from app.db import connect


def test_volunteered_fact_gets_short_ack_not_a_question(tmp_path, monkeypatch) -> None:
    _ready_companion(tmp_path)
    import app.modules.companion as companion
    # Force the "is this volunteered new info?" path to acknowledge.
    monkeypatch.setattr(companion, "generate_text", lambda *a, **k: "Got it — that's great.")
    reply = respond_to_user_turn("My EAD card was approved today")
    assert reply["kind"] == "acknowledge"
    assert reply["message"]
    # And it should NOT have generated a brand-new question turn.
    assert "quick_replies" not in reply or reply["quick_replies"] == []
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py -k volunteered_fact -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

`respond_to_user_turn(text)`:
1. `session = get_or_create_companion_session()`.
2. `record_user_turn(session["id"], text)` (transcript + raw capture).
3. Decide reply shape. Heuristic (deterministic, LLM-optional): if the **last assistant message** for the session was a question (meta.kind == 'question'/'checkin'), and the user's reply is meaningful, default to a brief **acknowledge** (the user answered). If the user volunteered without an outstanding question, also acknowledge. The companion only **asks** a fresh question when there is no outstanding question to answer.
4. For `acknowledge`: produce a short warm line via `generate_text` (persona system prompt, `max_output_tokens=120`); fallback to a fixed `"Got it — thanks for sharing that."`. Insert as a `companion_messages` assistant row with `meta={"kind":"acknowledge"}`. Return `{"kind":"acknowledge","message":...}`.
5. For `ask`: call `generate_companion_question()`, insert assistant message with `meta={"kind":"question","target_bucket_key":...,"quick_replies":...}`, return `{"kind":"question","message":opening_message,"quick_replies":...,"target_bucket_key":...}`.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py -k volunteered_fact -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/modules/companion.py backend/tests/test_companion.py
git commit -m "feat(companion): bidirectional reply (acknowledge vs ask)"
```

---

## Phase E — Session-end synthesis → bucket updates → weave

### Task E1: Synthesis pass queues `curious_companion` Bucket Updates

**Files:**
- Modify: `backend/app/modules/companion.py`
- Test: `backend/tests/test_companion.py`

**Step 1: Write the failing test**

```python
from app.modules.companion import synthesize_companion_session, get_or_create_companion_session, record_user_turn
from app.db import connect


def test_synthesis_queues_bucket_updates_from_captures(tmp_path, monkeypatch) -> None:
    _ready_companion(tmp_path)
    import app.modules.companion as companion
    session = get_or_create_companion_session()
    record_user_turn(session["id"], "My EAD card was approved today")

    # LLM stubbed: synthesis extracts one fact routed to career.
    monkeypatch.setattr(
        companion, "generate_json",
        lambda *a, **k: {"facts": [
            {"bucket_key": "career", "text": "Person's EAD work authorization was approved."}
        ]},
    )
    synthesize_companion_session(session["id"])

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT update_text, status, source_event FROM bucket_updates "
                "WHERE source_event ->> 'source' = 'curious_companion'"
            )
            rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert "EAD" in rows[0]["update_text"]


def test_synthesis_no_facts_when_llm_down(tmp_path) -> None:
    _ready_companion(tmp_path)
    session = get_or_create_companion_session()
    record_user_turn(session["id"], "My EAD card was approved today")
    # LLM disabled under pytest → fallback yields no synthesized facts, raw capture survives.
    synthesize_companion_session(session["id"])
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM life_items WHERE item_type = 'curious_capture'")
            assert cur.fetchone()["c"] == 1  # raw capture intact
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py -k synthesis -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

`synthesize_companion_session(session_id)`:
1. Load the transcript (`companion_messages` for the session, ordered).
2. One `generate_json` call: given the full conversation, return `{"facts":[{"bucket_key","text"}]}`. Clamp `bucket_key` to known keys; drop unknown.
3. For each fact: insert a `bucket_updates` row (`status='pending'`, `source_event={"source":"curious_companion", ...}`) linked to the bucket id (look up via `stable_key`) and to a representative capture Life Item id from this session (or the session id). Mark the relevant `curious_capture` items `bucket_update_status='complete'`.
4. **Fallback** `(LLMUnavailable, Exception)`: do nothing (no facts queued); raw captures remain. Log nothing noisy.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py -k synthesis -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/modules/companion.py backend/tests/test_companion.py
git commit -m "feat(companion): session-end synthesis queues curious_companion bucket updates"
```

---

### Task E2: Extend Curious weave to merge companion updates

**Files:**
- Modify: `backend/app/modules/curious.py:641-654` (`_pending_curious_story_bucket_ids` source filter)
- Test: `backend/tests/test_companion.py`

**Step 1: Write the failing test**

```python
from app.modules.curious import weave_pending_curious_updates


def test_weave_merges_companion_updates(tmp_path, monkeypatch) -> None:
    _ready_companion(tmp_path)
    import app.modules.companion as companion
    session = companion.get_or_create_companion_session()
    companion.record_user_turn(session["id"], "My EAD card was approved today")
    monkeypatch.setattr(
        companion, "generate_json",
        lambda *a, **k: {"facts": [
            {"bucket_key": "career", "text": "Person's EAD work authorization was approved."}
        ]},
    )
    companion.synthesize_companion_session(session["id"])

    result = weave_pending_curious_updates()
    merged = sum(r.merged_count for r in result.results)
    assert merged >= 1
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM story_buckets WHERE stable_key = 'career'")
            assert "EAD" in cur.fetchone()["content"]
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py -k weave_merges_companion -v`
Expected: FAIL (companion source not in the filter; merged stays 0).

**Step 3: Write minimal implementation**

In `curious.py::_pending_curious_story_bucket_ids`, extend the `IN (...)` list:

```sql
AND source_event ->> 'source' IN ('curious_bay', 'curious_dynamic', 'curious_companion')
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py -k weave_merges_companion -v`
Expected: PASS. Also run the full curious suite to confirm no regression: `cd backend && python -m pytest tests/test_curious_module.py -v`.

**Step 5: Commit**

```bash
git add backend/app/modules/curious.py backend/tests/test_companion.py
git commit -m "feat(companion): include companion updates in Curious weave"
```

---

## Phase F — Proactive check-in due-check

### Task F1: Lazy due-check prepares a check-in when the interval has elapsed

**Files:**
- Modify: `backend/app/modules/companion.py`
- Test: `backend/tests/test_companion.py`

**Step 1: Write the failing test**

```python
from app.modules.companion import prepare_due_checkin, get_or_create_companion_session
from app.db import connect


def test_due_check_prepares_checkin_when_enabled(tmp_path, monkeypatch) -> None:
    _ready_companion(tmp_path)
    import app.modules.companion as companion
    # Force frequency on and stub question generation.
    monkeypatch.setattr(companion, "_companion_settings", lambda: {
        "companion_enabled": True, "companion_checkins_per_day": 3,
        "companion_persona_preset": "warm", "companion_persona_override": "",
    })
    monkeypatch.setattr(companion, "generate_companion_question", lambda: {
        "opening_message": "Morning — how's the day shaping up?",
        "target_bucket_key": "habits", "quick_replies": [], "rationale": "checkin",
    })

    prepared = prepare_due_checkin()
    assert prepared is not None
    # Second immediate call should NOT prepare another (idempotent within interval).
    assert prepare_due_checkin() is None


def test_due_check_off_when_frequency_zero(tmp_path, monkeypatch) -> None:
    _ready_companion(tmp_path)
    import app.modules.companion as companion
    monkeypatch.setattr(companion, "_companion_settings", lambda: {
        "companion_enabled": True, "companion_checkins_per_day": 0,
        "companion_persona_preset": "warm", "companion_persona_override": "",
    })
    assert companion.prepare_due_checkin() is None
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py -k due_check -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

`prepare_due_checkin()`:
1. Read settings. If `not companion_enabled` or `companion_checkins_per_day <= 0`: return `None`.
2. `interval = timedelta(hours=24 / checkins_per_day)`.
3. Find the session; look at the latest assistant `companion_messages` row with `meta.kind == 'checkin'`.
   - If a check-in exists and is **unanswered** (no later user message): return `None` (one outstanding check-in at a time).
   - If the latest check-in's `created_at` is within `interval`: return `None` (not due).
4. Otherwise: `q = generate_companion_question()`, insert assistant message with `meta={"kind":"checkin", "target_bucket_key":..., "quick_replies":...}`, return the prepared check-in dict.

Use DB `now()` for time comparisons to stay consistent with Story Weave's `_db_now`.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py -k due_check -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/modules/companion.py backend/tests/test_companion.py
git commit -m "feat(companion): lazy due-check prepares proactive check-ins"
```

---

## Phase G — API surface

### Task G1: Companion endpoints

**Files:**
- Modify: `backend/app/api/curious.py`
- Modify: `backend/app/modules/companion.py` (add a `get_companion_state()` aggregator + Pydantic models)
- Test: `backend/tests/test_companion.py`

**Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient
from app.main import app


def test_companion_http_send_and_state(tmp_path) -> None:
    _ready_companion(tmp_path)
    client = TestClient(app)

    state = client.get("/modules/curious/companion/state")
    assert state.status_code == 200
    assert "messages" in state.json()

    sent = client.post("/modules/curious/companion/message", json={"message": "My EAD card was approved today"})
    assert sent.status_code == 200
    body = sent.json()
    assert body["reply"]["message"]

    # Timeline reflects the captured moment.
    state2 = client.get("/modules/curious/companion/state")
    assert any("EAD" in m.get("content", "") for m in state2.json()["messages"])
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companion.py -k http -v`
Expected: FAIL (routes 404).

**Step 3: Write minimal implementation**

Add to `companion.py`:
- Pydantic models: `CompanionMessage`, `CompanionReply`, `CompanionState` (fields: `messages: list[CompanionMessage]`, `timeline: list[...]`, `pending_checkin: CompanionMessage | None`, `settings: dict`).
- `get_companion_state()` aggregator: session transcript + captured-moment timeline + any prepared (unanswered) check-in + companion settings. Calls `prepare_due_checkin()` so opening the page materializes a due check-in.
- `send_companion_message(text) -> CompanionReply` wrapping `respond_to_user_turn`.
- `end_companion_session()` calling `synthesize_companion_session(...)` then `weave_pending_curious_updates()` (reuse from curious).

Add routes to `api/curious.py` under the existing `/modules/curious` prefix:
- `GET  /companion/state`  → `get_companion_state()`
- `POST /companion/message` (`{message: str}`) → `send_companion_message(...)`
- `POST /companion/end` → `end_companion_session()`

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companion.py -k http -v`
Expected: PASS. Then run the full backend suite: `cd backend && python -m pytest`.

**Step 5: Commit**

```bash
git add backend/app/api/curious.py backend/app/modules/companion.py backend/tests/test_companion.py
git commit -m "feat(companion): HTTP endpoints for companion state/message/end"
```

---

## Phase H — Frontend (verify via the app; no unit-test harness)

> For each frontend task, verify by running the app and exercising the flow. **REQUIRED SUB-SKILL:** use the `/run` skill (or `mcp__Claude_Preview__*`) to launch and drive the app.

### Task H1: API client functions

**Files:**
- Modify: `frontend/src/lib/api.ts` (add `fetchCompanionState`, `sendCompanionMessage`, `endCompanionSession` + types, mirroring existing curious client fns)

**Steps:** Add typed functions calling the three new endpoints; export `CompanionState`, `CompanionMessageItem`, `CompanionReply` types. Verify with `cd frontend && npx tsc --noEmit`.

**Commit:** `git commit -m "feat(companion): frontend api client"`

---

### Task H2: Replace the Curious card UI with a conversation thread

**Files:**
- Modify: `frontend/src/pages/CuriousPage.tsx`

**Steps:**
1. Render `companion.messages` as a chat thread (assistant left, user right), reusing the page's existing visual language (rounded cards, motion).
2. Add a text input + send. On send: optimistic append, call `sendCompanionMessage`, append the reply.
3. When an assistant message carries `meta.quick_replies`, render them as tappable chips that send the chosen label as the message.
4. Surface a prepared `pending_checkin` at the top as the companion's opening greeting.
5. Keep the existing weave triggers but point them at `endCompanionSession`: call on "Done for now", on idle (reuse `CURIOUS_IDLE_WEAVE_MS`), and on `pagehide`.

**Verify:** Launch the app, open Curious, send "My EAD card was approved today" → expect a short ack; send a vague "what should I focus on?" → expect a question. Confirm via `mcp__Claude_Preview__preview_screenshot`.

**Commit:** `git commit -m "feat(companion): conversational Curious thread UI"`

---

### Task H3: Dated captured-moments timeline (Logs stand-in)

**Files:**
- Modify: `frontend/src/pages/CuriousPage.tsx`

**Steps:** Replace/augment the "What Orbit's learned" accordion with a **dated timeline** of `companion.timeline` captured moments (newest first, grouped by day). Each entry shows the captured text + date.

**Verify:** After sending a few volunteered updates, confirm they appear in the timeline with dates.

**Commit:** `git commit -m "feat(companion): dated captured-moments timeline"`

---

### Task H4: Persona + check-in frequency settings

**Files:**
- Modify: `frontend/src/pages/CuriousPage.tsx` (`CuriousSettingsPopover`)

**Steps:** Add a persona preset selector (Warm/Coach/Gentle/Direct), a freeform override textarea, and a check-in frequency control (0 = off … N/day), wired through the existing `updateModuleInstanceSettings(curiousInstance.id, ...)` path used today.

**Verify:** Change preset → next companion turn reflects tone; set frequency > 0, reopen page after the interval → a prepared check-in appears.

**Commit:** `git commit -m "feat(companion): persona + check-in frequency settings"`

---

## Phase I — Final verification

### Task I1: Full suite + manual smoke

**Steps:**
1. `cd backend && python -m pytest` → all green (companion + curious + chat regressions).
2. `cd frontend && npx tsc --noEmit` → clean.
3. Manual smoke via `/run`:
   - Onboarding cold-start surfaces foundational questions conversationally.
   - Volunteered update → short ack + appears in timeline.
   - "Done for now" weaves a synthesized fact into the right bucket (check `/user-model`).
   - Frequency > 0 prepares a check-in after the interval.
4. **REQUIRED SUB-SKILL:** use superpowers:requesting-code-review before merge.

**Commit:** none (verification only). Then use superpowers:finishing-a-development-branch to merge/PR.

---

## Notes & deferred (do NOT build now)

- In-conversation create-actions (Tasks/Plans/Logs/Routines) via Capture Proposals.
- Browser/OS notifications + a true background scheduler (away-from-app check-ins).
- Companion-managed recurring "Routines."
- Full retirement of the Logs module (kept running in parallel during v0).
