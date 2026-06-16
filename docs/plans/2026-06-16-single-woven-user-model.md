# Single Woven User Model — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the 7 Story Buckets feed with one append-only `user_facts`
stream synthesized by a background LLM weave into a single living narrative
(`user_model_weave`), fed to every LLM call as "woven doc + unwoven tail".

**Architecture:** Capture (companion answers, life-item events, manual notes) →
`user_facts` (append-only, Postgres). A threshold on the unwoven tail triggers a
background `weave_user_model()` that LLM-synthesizes the fixed-section narrative
and marks facts woven. `build_user_model_context()` feeds woven doc + tail,
replacing the 7 per-bucket truncation sites. Legacy `bucket_updates`/`story_weave`
left in place but unwired from the feed.

**Tech Stack:** Python 3 / FastAPI, psycopg3, Postgres (pgvector), Gemini via
`app.llm` (`generate_text`/`generate_json`, `LLMUnavailable`). Tests: pytest
against a dedicated test DB; `llm_enabled()` is `False` under pytest.

**Design doc:** `docs/plans/2026-06-15-single-woven-user-model-design.md`

**Conventions to follow:**
- Schema: idempotent `CREATE TABLE IF NOT EXISTS` + `ALTER ... ADD COLUMN IF NOT
  EXISTS` in `backend/app/db/schema.py::ensure_schema()`.
- DB access: `from app.db import transaction` (write) / `connect` (read), cursors
  yield dict rows.
- LLM: wrap calls in `try/except (LLMUnavailable, Exception)` with a deterministic
  fallback.
- Tests truncate mutable tables in `backend/tests/conftest.py` — new tables must
  be added there.
- Run tests from `backend/`: `cd backend && python -m pytest`.

---

### Task 1: Schema for `user_facts` and `user_model_weave`

**Files:**
- Modify: `backend/app/db/schema.py` (inside `ensure_schema()`, after the
  `story_weave_runs` block ~line 359)
- Modify: `backend/tests/conftest.py:28-54` (add both tables to `TRUNCATE`)
- Test: `backend/tests/test_user_facts.py` (new)

**Step 1: Write the failing test**

```python
# backend/tests/test_user_facts.py
from __future__ import annotations
from app.db import connect

def test_user_facts_and_weave_tables_exist():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.user_facts') AS t")
        assert cur.fetchone()["t"] == "user_facts"
        cur.execute("SELECT to_regclass('public.user_model_weave') AS t")
        assert cur.fetchone()["t"] == "user_model_weave"

def test_user_facts_defaults():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO user_facts (source, text) VALUES ('manual', 'hi') RETURNING woven, salience"
        )
        row = cur.fetchone()
        assert row["woven"] is False
        assert row["salience"] == "normal"
        conn.rollback()
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_user_facts.py -v`
Expected: FAIL — `to_regclass` returns `None`.

**Step 3: Add the DDL** in `ensure_schema()` after the `story_weave_runs` table:

```python
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS user_facts (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        source TEXT NOT NULL
            CHECK (source IN ('companion', 'life_item', 'manual', 'import')),
        text TEXT NOT NULL,
        ref JSONB NOT NULL DEFAULT '{}'::jsonb,
        salience TEXT NOT NULL DEFAULT 'normal'
            CHECK (salience IN ('normal', 'high')),
        woven BOOLEAN NOT NULL DEFAULT FALSE,
        woven_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """
)
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS user_model_weave (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        version INTEGER NOT NULL,
        content TEXT NOT NULL,
        fact_count_at_weave INTEGER NOT NULL DEFAULT 0,
        woven_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """
)
cur.execute(
    "CREATE INDEX IF NOT EXISTS idx_user_facts_unwoven "
    "ON user_facts(created_at) WHERE woven = FALSE"
)
cur.execute(
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_model_weave_version "
    "ON user_model_weave(version)"
)
```

Add `user_facts,` and `user_model_weave,` to the `TRUNCATE TABLE` list in
`conftest.py::_truncate_mutable_tables` (top of the list, before `life_items`).

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_user_facts.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/db/schema.py backend/tests/conftest.py backend/tests/test_user_facts.py
git commit -m "feat(user-model): user_facts + user_model_weave schema"
```

---

### Task 2: `capture_fact()` and fact query helpers

**Files:**
- Create: `backend/app/user_model/facts.py`
- Modify: `backend/app/user_model/__init__.py` (export `capture_fact`,
  `list_unwoven_facts`, `unwoven_budget`)
- Test: `backend/tests/test_user_facts.py` (extend)

**Step 1: Write failing tests**

```python
def test_capture_fact_appends_unwoven():
    from app.user_model import capture_fact, list_unwoven_facts
    capture_fact(source="manual", text="Family runs Ajey Pavers in Trichy.")
    facts = list_unwoven_facts()
    assert len(facts) == 1
    assert facts[0]["text"].startswith("Family runs")
    assert facts[0]["woven"] is False

def test_unwoven_budget_counts_and_chars():
    from app.user_model import capture_fact, unwoven_budget
    capture_fact(source="companion", text="a" * 100)
    capture_fact(source="life_item", text="b" * 50, ref={"life_item_id": "x", "kind": "task"})
    count, chars = unwoven_budget()
    assert count == 2
    assert chars == 150
```

**Step 2: Run to verify fail**

Run: `cd backend && python -m pytest tests/test_user_facts.py -k capture -v`
Expected: FAIL — `ImportError: capture_fact`.

**Step 3: Implement `facts.py`**

```python
"""Append-only user fact stream feeding the woven User Model."""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from psycopg import Connection
from psycopg.types.json import Jsonb
from app.db import connect, transaction

def capture_fact(
    *,
    source: str,
    text: str,
    ref: Mapping[str, Any] | None = None,
    salience: str = "normal",
    conn: Connection | None = None,
) -> dict[str, Any]:
    """Append one raw fact to the stream. Idempotency is the caller's concern."""
    text = text.strip()
    if not text:
        raise ValueError("Fact text must be non-empty")
    if conn is None:
        with transaction() as owned:
            return capture_fact(source=source, text=text, ref=ref, salience=salience, conn=owned)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_facts (source, text, ref, salience)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (source, text, Jsonb(dict(ref or {})), salience),
        )
        return dict(cur.fetchone())

def list_unwoven_facts(conn: Connection | None = None) -> list[dict[str, Any]]:
    if conn is None:
        with connect() as owned:
            return list_unwoven_facts(owned)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM user_facts WHERE woven = FALSE ORDER BY created_at ASC"
        )
        return [dict(r) for r in cur.fetchall()]

def unwoven_budget(conn: Connection | None = None) -> tuple[int, int]:
    """Return (count, total_chars) of unwoven facts — the weave trigger input."""
    facts = list_unwoven_facts(conn)
    return len(facts), sum(len(f["text"]) for f in facts)
```

Export the three names from `backend/app/user_model/__init__.py`.

**Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_user_facts.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/user_model/facts.py backend/app/user_model/__init__.py backend/tests/test_user_facts.py
git commit -m "feat(user-model): capture_fact + unwoven fact queries"
```

---

### Task 3: Life-item capture hook (one hook, all modules)

**Files:**
- Modify: `backend/app/lifecycle/life_items.py` (`create_life_item` ~line 143,
  `update_life_item` ~line 196, `delete_life_item` ~line 222)
- Test: `backend/tests/test_user_facts.py` (extend)

**Design:** capture a fact whenever a durable life item is created/updated/
deleted. Use the item's `title`/`item_type` for `text`, and `ref =
{"life_item_id": id, "kind": item_type}`. On create, only when `result.created`
is True (respect idempotency). On delete, capture a retraction fact BEFORE the
row is deleted (so the title is still available).

**Step 1: Write failing test**

```python
def test_create_life_item_captures_fact(seed_task_module):  # reuse existing module fixtures
    from app.modules.tasks import create_task   # or whichever create entrypoint tests use
    from app.user_model import list_unwoven_facts
    create_task(title="Finish Home Credit writeup", request_id="t-1")
    facts = [f for f in list_unwoven_facts() if f["source"] == "life_item"]
    assert any("Home Credit" in f["text"] for f in facts)
    assert facts[0]["ref"].get("life_item_id")
```

> Note: mirror the exact create entrypoint and fixtures used in
> `backend/tests/test_tasks_module.py`. Read that test first.

**Step 2: Run to verify fail**

Run: `cd backend && python -m pytest tests/test_user_facts.py -k life_item -v`
Expected: FAIL — no `life_item` fact captured.

**Step 3: Implement the hook**

Add a private helper in `life_items.py`:

```python
def _capture_life_item_fact(item: dict, verb: str) -> None:
    # Local import avoids a module-load cycle (user_model imports db, not lifecycle).
    from app.user_model import capture_fact
    title = (item.get("title") or "").strip()
    if not title:
        return
    kind = item.get("item_type") or "item"
    capture_fact(
        source="life_item",
        text=f"{verb} {kind}: {title}",
        ref={"life_item_id": str(item["id"]), "kind": kind},
    )
```

- In `create_life_item`, before `return LifeItemResult(...)`, add:
  `if created: _capture_life_item_fact(item, "Added")`
- In `update_life_item`, before `return dict(row)` (the success path), add:
  `_capture_life_item_fact(dict(row), "Updated")`
- In `delete_life_item`, change the DELETE to `RETURNING id, title, item_type`,
  and after confirming the row existed, call
  `_capture_life_item_fact(dict(row), "Removed")`.

**Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_user_facts.py tests/test_tasks_module.py -v`
Expected: PASS (and existing task tests still green).

**Step 5: Commit**

```bash
git add backend/app/lifecycle/life_items.py backend/tests/test_user_facts.py
git commit -m "feat(user-model): capture life-item events as facts"
```

---

### Task 4: Companion answers capture facts

**Files:**
- Modify: `backend/app/modules/companion.py` (the answer-handling path that
  currently routes to a bucket update — near `bucket_update_status` usage)
- Test: `backend/tests/test_companion.py` (extend)

**Step 1:** Read `test_companion.py` to find the answer-submit entrypoint. Write a
test asserting that submitting a companion answer appends a `source='companion'`
fact with the answer text.

**Step 2:** Run — expect FAIL.

**Step 3:** In the companion answer handler, after persisting the answer, call
`capture_fact(source="companion", text=<answer text>, ref={"bucket_key": target_bucket_key})`.
Leave the existing bucket-update write in place for now (unwired later).

**Step 4:** Run companion tests — expect PASS.

**Step 5:** Commit `feat(user-model): companion answers append facts`.

---

### Task 5: `weave_user_model()` — LLM synthesis with deterministic fallback

**Files:**
- Create: `backend/app/user_model/weave.py`
- Modify: `backend/app/user_model/__init__.py` (export `weave_user_model`,
  `current_woven_doc`, `WEAVE_FACT_THRESHOLD`, `WEAVE_CHAR_THRESHOLD`)
- Test: `backend/tests/test_user_model_weave.py` (new)

**Section template constant** (the fixed sections from the design doc):

```python
SECTION_TEMPLATE = (
    "# Identity\n\n# Work & Career\n\n# Personal Life\n\n"
    "# Top of Mind\n\n# Brief History\n\n## Recent\n\n## Earlier\n\n"
    "## Long-term background\n"
)
WEAVE_FACT_THRESHOLD = 8
WEAVE_CHAR_THRESHOLD = 1500
```

**Behavior:**
1. Read current doc (highest `version`, or `SECTION_TEMPLATE` if none).
2. Read unwoven facts; if none, return without writing.
3. Build prompt (current doc + facts) and call `generate_text`. On
   `LLMUnavailable`/any error, fall back to `_deterministic_weave(doc, facts)`
   which appends each fact as a bullet under a `# Top of Mind` block.
4. Insert a new `user_model_weave` row with `version = prev + 1`,
   `fact_count_at_weave = total facts so far`.
5. Mark the woven facts `woven = TRUE, woven_at = now()` in the SAME transaction.

**Step 1: Write failing tests** (LLM is off under pytest → exercises fallback)

```python
# backend/tests/test_user_model_weave.py
from app.user_model import capture_fact, weave_user_model, current_woven_doc, list_unwoven_facts

def test_weave_creates_version_and_marks_facts():
    capture_fact(source="manual", text="Targeting Data Scientist + DE roles.")
    capture_fact(source="manual", text="OPT starts mid-June 2026.")
    result = weave_user_model()
    assert result["version"] == 1
    doc = current_woven_doc()
    assert "Data Scientist" in doc["content"]
    assert list_unwoven_facts() == []   # all folded

def test_weave_noop_when_no_unwoven_facts():
    assert weave_user_model() is None

def test_weave_preserves_prior_content_across_versions():
    capture_fact(source="manual", text="Family runs Ajey Pavers.")
    weave_user_model()
    capture_fact(source="manual", text="From Trichy, Tamil Nadu.")
    weave_user_model()
    doc = current_woven_doc()
    assert "Ajey Pavers" in doc["content"]
    assert "Trichy" in doc["content"]
    assert doc["version"] == 2
```

**Step 2:** Run — expect FAIL (`ImportError`).

**Step 3: Implement `weave.py`** (full code):

```python
"""Synthesize unwoven facts into the single woven User Model document."""
from __future__ import annotations
from typing import Any
from psycopg import Connection
from app.db import transaction, connect
from app.llm import LLMUnavailable, generate_text
from app.user_model.facts import list_unwoven_facts

SECTION_TEMPLATE = (
    "# Identity\n\n# Work & Career\n\n# Personal Life\n\n"
    "# Top of Mind\n\n# Brief History\n\n## Recent\n\n## Earlier\n\n"
    "## Long-term background\n"
)
WEAVE_FACT_THRESHOLD = 8
WEAVE_CHAR_THRESHOLD = 1500
_WEAVE_BUDGET_TOKENS = 1600

_SYSTEM = (
    "You maintain a person's life narrative. Fold the new observations into the "
    "existing document. Keep EXACTLY these sections and order: Identity; Work & "
    "Career; Personal Life; Top of Mind; Brief History (Recent, Earlier, "
    "Long-term background). Preserve Identity verbatim unless a fact directly "
    "revises it. Demote aging Top-of-Mind items into Recent then Earlier as they "
    "cool. Honor high-salience facts. Output ONLY the full updated markdown."
)

def current_woven_doc(conn: Connection | None = None) -> dict[str, Any] | None:
    if conn is None:
        with connect() as owned:
            return current_woven_doc(owned)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM user_model_weave ORDER BY version DESC LIMIT 1"
        )
        row = cur.fetchone()
        return dict(row) if row else None

def _deterministic_weave(doc: str, facts: list[dict]) -> str:
    bullets = "\n".join(
        f"- {f['text']}" + (" *(important)*" if f["salience"] == "high" else "")
        for f in facts
    )
    marker = "# Top of Mind"
    if marker in doc:
        return doc.replace(marker, f"{marker}\n{bullets}", 1)
    return f"{doc.rstrip()}\n\n{marker}\n{bullets}\n"

def _llm_weave(doc: str, facts: list[dict]) -> str:
    fact_lines = "\n".join(
        f"- ({f['source']}/{f['salience']}) {f['text']}" for f in facts
    )
    prompt = (
        f"CURRENT DOCUMENT:\n{doc}\n\nNEW OBSERVATIONS:\n{fact_lines}\n\n"
        f"Return the full updated document under {_WEAVE_BUDGET_TOKENS} tokens."
    )
    return generate_text(prompt, system=_SYSTEM, temperature=0.3,
                         max_output_tokens=_WEAVE_BUDGET_TOKENS).strip()

def weave_user_model(conn: Connection | None = None) -> dict[str, Any] | None:
    if conn is None:
        with transaction() as owned:
            return weave_user_model(owned)
    facts = list_unwoven_facts(conn)
    if not facts:
        return None
    prev = current_woven_doc(conn)
    base = prev["content"] if prev else SECTION_TEMPLATE
    next_version = (prev["version"] + 1) if prev else 1
    try:
        content = _llm_weave(base, facts)
        if not content:
            raise LLMUnavailable("empty weave")
    except (LLMUnavailable, Exception):
        content = _deterministic_weave(base, facts)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) AS c FROM user_facts")
        total = cur.fetchone()["c"]
        cur.execute(
            """
            INSERT INTO user_model_weave (version, content, fact_count_at_weave)
            VALUES (%s, %s, %s) RETURNING *
            """,
            (next_version, content, total),
        )
        woven = dict(cur.fetchone())
        cur.execute(
            "UPDATE user_facts SET woven = TRUE, woven_at = now() "
            "WHERE id = ANY(%s)",
            ([f["id"] for f in facts],),
        )
    return woven

def should_weave(conn: Connection | None = None) -> bool:
    from app.user_model.facts import unwoven_budget
    count, chars = unwoven_budget(conn)
    return count >= WEAVE_FACT_THRESHOLD or chars >= WEAVE_CHAR_THRESHOLD
```

Export `weave_user_model`, `current_woven_doc`, `should_weave`,
`SECTION_TEMPLATE`, thresholds from `__init__.py`.

**Step 4:** Run: `cd backend && python -m pytest tests/test_user_model_weave.py -v`
Expected: PASS.

**Step 5:** Commit `feat(user-model): weave_user_model synthesis + fallback`.

---

### Task 6: Background trigger + manual re-weave endpoint

**Files:**
- Create: `backend/app/api/user_model_weave.py` (router:
  `POST /api/user-model/reweave`, `GET /api/user-model/doc`)
- Modify: `backend/app/main.py` (include the router)
- Modify: capture call sites to schedule a weave when `should_weave()` — see note
- Test: `backend/tests/test_user_model_weave.py` + an API test

**Trigger strategy:** keep capture pure (no weave inside `capture_fact`). Instead,
add a thin `maybe_weave_in_background(background_tasks)` the **API layer** calls
after any request that captured facts:

```python
# in the relevant FastAPI route, after the mutation:
if should_weave():
    background_tasks.add_task(weave_user_model)
```

For non-request capture paths (inline lifecycle), call `weave_user_model()`
synchronously only if `should_weave()` — acceptable because it's threshold-gated
and rare. Document this in the route.

**Step 1:** Write an API test: capture 8 facts via the manual "add note" endpoint
(Task 10) or directly, POST `/api/user-model/reweave`, assert a doc version is
returned and unwoven facts are cleared. Also unit-test `should_weave()` boundary
(7 facts → False, 8 → True).

**Step 2:** Run — expect FAIL.

**Step 3:** Implement the router (mirror `backend/app/api/story_weave.py`
structure) and `should_weave` boundary; wire `background_tasks.add_task` in the
note/companion routes.

**Step 4:** Run API + weave tests — expect PASS.

**Step 5:** Commit `feat(user-model): reweave endpoint + background trigger`.

---

### Task 7: `build_user_model_context()` feed builder

**Files:**
- Create: `backend/app/user_model/context.py`
- Modify: `backend/app/user_model/__init__.py` (export)
- Test: `backend/tests/test_user_model_context.py` (new)

**Behavior:** return `woven_doc.content` (trimmed to a char budget, default 4000)
+ a "## Recently (not yet woven)" block listing up to N newest unwoven facts as
`- [source] text`. Empty/first-run → return just the tail, or a minimal stub.

**Step 1: Write failing tests**

```python
def test_context_includes_doc_and_tail():
    from app.user_model import capture_fact, weave_user_model, build_user_model_context
    capture_fact(source="manual", text="Builder-first, direct, fast iteration.")
    weave_user_model()
    capture_fact(source="life_item", text="Added task: LeetCode Blind 75")
    ctx = build_user_model_context()
    assert "Builder-first" in ctx
    assert "Recently (not yet woven)" in ctx
    assert "Blind 75" in ctx

def test_context_empty_is_safe():
    from app.user_model import build_user_model_context
    assert isinstance(build_user_model_context(), str)
```

**Step 2:** Run — expect FAIL.

**Step 3:** Implement `context.py` using `current_woven_doc` + `list_unwoven_facts`
(newest first, capped at e.g. 8). Provide a `budget: int = 4000` param.

**Step 4:** Run — expect PASS.

**Step 5:** Commit `feat(user-model): build_user_model_context feed`.

---

### Task 8: Swap the 7 bucket feed sites to the woven feed

**Files (each a small modify + its test):**
- `backend/app/modules/companion.py:208` `build_companion_context()` — replace the
  per-bucket loop with `build_user_model_context()` (keep recent-activity block).
- `backend/app/chat/actions.py:990` `_selected_bucket_context()` and `:1111`
  `_bucket_catalog()` — feed woven doc instead of bucket content.
- `backend/app/chat/item_chat.py:211` `_get_connected_bucket_text()` — woven doc.
- `backend/app/modules/documents.py:368` and `backend/app/modules/tasks.py:527` —
  swap `list_story_bucket_items()` content for `build_user_model_context()`.

**Per site, do TDD:** read the existing test that covers the call site; update it
to assert the woven doc text appears (and bucket-truncation no longer does);
make the change; run that module's tests.

**Step 5 (after all sites):** Commit
`refactor(user-model): feed woven doc in place of 7-bucket truncation`.

> Do these as separate commits per file if review prefers smaller diffs.

---

### Task 9: Migration — seed the first woven doc from existing buckets

**Files:**
- Modify: `backend/app/db/bootstrap.py` (call a new `seed_woven_user_model()`)
- Create: `backend/app/user_model/migrate.py`
- Test: `backend/tests/test_user_model_weave.py` (extend)

**Behavior (idempotent):** if `user_model_weave` is empty, read active
`story_buckets` content, emit one `import` fact per non-empty bucket (mapping
`who_am_i`→Identity etc. via a prefix in the fact text), then run
`weave_user_model()` once to produce version 1. Guard so it never re-runs when a
doc already exists.

**Step 1:** Test: with seeded buckets containing text, `seed_woven_user_model()`
produces a version-1 doc containing that text; calling it twice is a no-op
(version stays 1).

**Steps 2–4:** Implement + verify.

**Step 5:** Commit `feat(user-model): seed initial woven doc from story buckets`.

---

### Task 10: Minimal surface — view doc, list facts, add note

**Files:**
- Modify: `backend/app/api/user_model_weave.py` (`GET /api/user-model/facts`,
  `POST /api/user-model/notes` → `capture_fact(source="manual", salience="high")`
  + background reweave check)
- Frontend: add a read-only "User Model" view + "Add note" box (mirror existing
  settings panels under `frontend/`)
- Test: API tests for the three endpoints

Manual notes land as **high-salience** facts (design decision: manual edits are
facts, not in-place doc edits). TDD each endpoint.

**Step 5:** Commit `feat(user-model): view doc + add-note surface`.

---

### Task 11: Unwire legacy per-bucket weave from the feed (cleanup)

**Files:**
- Modify: `backend/app/lifecycle/connection_review.py` /
  `backend/app/lifecycle/derived.py` — stop the feed depending on
  `bucket_updates`/`story_weave`. Keep the tables/code (no destructive drop) but
  remove inline `weave_story_bucket` calls from document/curious create paths now
  that facts + woven doc are the source of truth.
- Test: ensure document/curious module tests still pass without the bucket weave.

This is the only "remove" task and is intentionally last, after the woven model
is proven. **Do not drop `story_buckets`/`bucket_updates` tables** — leave for a
later, separate deprecation once you trust the new model in real use.

**Step 5:** Commit `refactor(user-model): unwire legacy per-bucket weave from feed`.

---

## Final verification

Run the full suite from `backend/`:

```bash
cd backend && python -m pytest -q
```

Expected: all green. Then manually (with LLM enabled) capture a few life items +
notes, hit `POST /api/user-model/reweave`, and read `GET /api/user-model/doc` to
confirm a coherent single narrative in the fixed sections.

## Notes for the executor

- `user_model/*.md` files are **gitignored** and irrelevant at runtime now —
  do not resurrect them.
- The weave LLM call only runs outside pytest; never write tests asserting LLM
  prose. Assert structure, versions, and `woven` flags.
- Keep `capture_fact` free of weave logic — triggering lives at the API/lifecycle
  edge so it's easy to make fully async later.
