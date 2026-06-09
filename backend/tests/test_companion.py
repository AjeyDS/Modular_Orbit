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


def test_curious_module_has_companion_defaults() -> None:
    from app.modules import sync_module_registry

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
