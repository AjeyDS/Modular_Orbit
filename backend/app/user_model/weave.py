"""Synthesize unwoven facts into the single woven User Model document."""
from __future__ import annotations

import logging
from typing import Any

import fastapi
from psycopg import Connection

from app.db import connect, transaction
from app.llm import LLMUnavailable, generate_text
from app.user_model.facts import list_unwoven_facts

logger = logging.getLogger(__name__)

_WEAVE_LOCK_KEY = 778899001

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
        cur.execute("SELECT * FROM user_model_weave ORDER BY version DESC LIMIT 1")
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
    return generate_text(
        prompt, system=_SYSTEM, temperature=0.3, max_output_tokens=_WEAVE_BUDGET_TOKENS
    ).strip()


def _synthesize(base: str, facts: list[dict]) -> str:
    """Compute woven content via LLM, falling back to deterministic weave."""
    try:
        content = _llm_weave(base, facts)
        if not content:
            raise LLMUnavailable("empty weave")
    except (LLMUnavailable, Exception):
        content = _deterministic_weave(base, facts)
    return content


def _write_woven(conn: Connection, content: str, facts: list[dict]) -> dict[str, Any]:
    """Insert a new woven version and mark the given facts woven, on the passed conn."""
    prev = current_woven_doc(conn)
    next_version = (prev["version"] + 1) if prev else 1
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
            "UPDATE user_facts SET woven = TRUE, woven_at = now() WHERE id = ANY(%s)",
            ([f["id"] for f in facts],),
        )
    return woven


def weave_user_model(conn: Connection | None = None) -> dict[str, Any] | None:
    if conn is not None:
        # Caller-managed transaction: caller owns serialization.
        facts = list_unwoven_facts(conn)
        if not facts:
            return None
        prev = current_woven_doc(conn)
        base = prev["content"] if prev else SECTION_TEMPLATE
        content = _synthesize(base, facts)
        return _write_woven(conn, content, facts)

    # Owned path: serialize concurrent weaves with a session-level advisory lock
    # on a dedicated connection, and keep the LLM call OUT of the write transaction.
    lock_conn = connect()
    try:
        with lock_conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", (_WEAVE_LOCK_KEY,))
        lock_conn.commit()  # connect() has no autocommit; release the lock's txn

        with connect() as read_conn:
            facts = list_unwoven_facts(read_conn)
            if not facts:
                return None
            prev = current_woven_doc(read_conn)
            base = prev["content"] if prev else SECTION_TEMPLATE

        # LLM synthesis happens with NO write transaction open.
        content = _synthesize(base, facts)

        with transaction() as write_conn:
            return _write_woven(write_conn, content, facts)
    finally:
        with lock_conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (_WEAVE_LOCK_KEY,))
        lock_conn.commit()
        lock_conn.close()


def should_weave(conn: Connection | None = None) -> bool:
    from app.user_model.facts import unwoven_budget

    count, chars = unwoven_budget(conn)
    return count >= WEAVE_FACT_THRESHOLD or chars >= WEAVE_CHAR_THRESHOLD


def _weave_best_effort() -> None:
    """Run a weave as a background task; never let a failure escape into the ASGI stack."""
    try:
        weave_user_model()
    except Exception:
        logger.warning("Background weave failed", exc_info=True)


def schedule_weave_if_needed(background_tasks: fastapi.BackgroundTasks) -> None:
    """If the unwoven tail has crossed the threshold, schedule a weave to run after the response."""
    if should_weave():
        background_tasks.add_task(_weave_best_effort)
