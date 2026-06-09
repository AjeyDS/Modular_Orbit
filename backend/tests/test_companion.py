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
