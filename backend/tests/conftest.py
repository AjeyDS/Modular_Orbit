from __future__ import annotations

import os

import pytest

from app.db import connect, ensure_schema
from app.core.config import settings
from app.modules import sync_module_registry
from app.user_model import ensure_goals_seed, ensure_story_buckets


@pytest.fixture(autouse=True)
def clean_mutable_app_data() -> None:
    """Keep backend tests from leaving fake Life Items in the local app DB."""
    _assert_safe_test_database()
    ensure_schema()
    _truncate_mutable_tables()
    _restore_static_state()
    yield
    _truncate_mutable_tables()
    _restore_static_state()


def _truncate_mutable_tables() -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                TRUNCATE TABLE
                    generated_outputs,
                    goals,
                    capture_proposals,
                    chat_messages,
                    chat_sessions,
                    task_priority_suggestion_runs,
                    story_weave_runs,
                    bucket_updates,
                    knowledge_chunks,
                    item_connections,
                    plan_steps,
                    plan_step_items,
                    plan_items,
                    document_items,
                    routine_completions,
                    task_items,
                    routine_items,
                    companion_messages,
                    life_items,
                    module_settings,
                    module_instances
                RESTART IDENTITY CASCADE
                """
            )
        conn.commit()


def _restore_static_state() -> None:
    sync_module_registry()
    ensure_story_buckets()
    ensure_goals_seed()


def _assert_safe_test_database() -> None:
    database_url = settings.database_url
    if os.environ.get("ORBIT_ALLOW_TEST_DB_CLEANUP") == "1":
        return
    if "test" in database_url.rsplit("/", 1)[-1]:
        return
    raise RuntimeError(
        "Refusing to run destructive backend test cleanup against a non-test database. "
        "Set DATABASE_URL to a dedicated test database, or set ORBIT_ALLOW_TEST_DB_CLEANUP=1 intentionally."
    )
