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


def list_recent_facts(limit: int = 20, conn: Connection | None = None) -> list[dict[str, Any]]:
    if conn is None:
        with connect() as owned:
            return list_recent_facts(limit, owned)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM user_facts ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def unwoven_budget(conn: Connection | None = None) -> tuple[int, int]:
    """Return (count, total_chars) of unwoven facts — the weave trigger input."""
    facts = list_unwoven_facts(conn)
    return len(facts), sum(len(f["text"]) for f in facts)
