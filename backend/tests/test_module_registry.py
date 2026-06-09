from __future__ import annotations

from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from app.db import connect, ensure_schema
from app.modules import (
    INITIAL_MODULES,
    ModuleDefinition,
    ModuleRegistryError,
    get_module_definition,
    restore_module_instance_defaults,
    sync_module_registry,
    validate_module_registry,
)


@pytest.fixture(autouse=True)
def schema_ready() -> None:
    ensure_schema()


def test_initial_module_definitions_follow_contract() -> None:
    validate_module_registry()

    module_ids = {definition.module_id for definition in INITIAL_MODULES}
    assert {
        "curious",
        "logs",
        "tasks",
        "plans",
        "goals",
        "chat",
        "documents",
        "recommendations",
        "strategies",
    } <= module_ids

    for definition in INITIAL_MODULES:
        assert "active" in definition.valid_lifecycle_statuses
        assert "deleted" in definition.valid_lifecycle_statuses
        assert definition.retrieval_policy.mode in {"none", "summary", "full_text", "selective"}
        assert definition.retrieval_policy.min_signal in {"always", "meaningful_only", "confirmed_only"}
        assert definition.retrieval_policy.delete_behavior in {"delete", "archive"}
        if definition.retrieval_policy.mode == "none":
            assert definition.retrieval_policy.create_chunks is False
            assert definition.retrieval_policy.default_chunk_status == "not_needed"
        if definition.storage_strategy == "extended":
            assert definition.side_table
            assert definition.side_table_rationale
        else:
            assert definition.side_table is None
            assert definition.side_table_rationale is None


def test_registry_rejects_duplicate_module_ids() -> None:
    with pytest.raises(ModuleRegistryError):
        validate_module_registry((INITIAL_MODULES[0], INITIAL_MODULES[0]))


def test_module_definition_rejects_invalid_extended_storage() -> None:
    with pytest.raises(ValueError):
        ModuleDefinition(
            module_id="bad_tasks",
            name="Bad Tasks",
            description="Invalid extended module",
            roles=("capture",),
            storage_strategy="extended",
            valid_lifecycle_statuses=("active", "deleted"),
        )


def test_get_module_definition_returns_registered_module() -> None:
    tasks = get_module_definition("tasks")

    assert tasks.name == "Tasks"
    assert tasks.storage_strategy == "extended"
    assert tasks.side_table == "task_items"


def test_sync_module_registry_upserts_initial_modules() -> None:
    expected_ids = [definition.module_id for definition in INITIAL_MODULES]

    with connect() as conn:
        sync_module_registry(conn)
        sync_module_registry(conn)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, storage_strategy, valid_lifecycle_statuses, side_table
                FROM modules
                WHERE id = ANY(%s)
                """,
                (expected_ids,),
            )
            rows = {row["id"]: row for row in cur.fetchall()}

        assert set(expected_ids) <= set(rows)
        assert rows["tasks"]["storage_strategy"] == "extended"
        assert rows["tasks"]["side_table"] == "task_items"
        assert rows["documents"]["storage_strategy"] == "extended"
        assert rows["documents"]["side_table"] == "document_items"
        assert rows["plans"]["storage_strategy"] == "extended"
        assert rows["plans"]["side_table"] == "plan_items"
        assert rows["tasks"]["valid_lifecycle_statuses"] == [
            "active",
            "completed",
            "archived",
            "deleted",
        ]
        assert rows["logs"]["valid_lifecycle_statuses"] == ["active", "archived", "deleted"]
        assert rows["curious"]["storage_strategy"] == "generalized"
        assert rows["curious"]["valid_lifecycle_statuses"] == [
            "active",
            "completed",
            "archived",
            "deleted",
        ]
        conn.rollback()


def test_restore_module_instance_defaults() -> None:
    with connect() as conn:
        sync_module_registry(conn)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO module_instances (module_id, display_name, settings)
                VALUES ('chat', %s, %s)
                RETURNING id
                """,
                (
                    f"Chat {uuid4().hex}",
                    Jsonb({"default_mode": "quick", "max_suggestions_per_session": 99}),
                ),
            )
            instance_id = cur.fetchone()["id"]

        defaults = restore_module_instance_defaults(conn, instance_id)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT mi.settings AS instance_settings, ms.settings AS module_settings
                FROM module_instances mi
                JOIN module_settings ms ON ms.module_instance_id = mi.id
                WHERE mi.id = %s
                """,
                (instance_id,),
            )
            row = cur.fetchone()

        assert defaults == {
            "default_mode": "standard",
            "max_suggestions_per_session": 2,
        }
        assert row["instance_settings"] == defaults
        assert row["module_settings"] == defaults
        conn.rollback()
