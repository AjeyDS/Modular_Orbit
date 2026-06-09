from __future__ import annotations

from uuid import uuid4

import pytest

from app.db import connect, ensure_schema
from app.lifecycle import (
    LifeItemError,
    create_life_item,
    delete_life_item,
    set_lifecycle_status,
    update_life_item,
)
from app.modules import sync_module_registry


@pytest.fixture(autouse=True)
def registry_ready() -> None:
    ensure_schema()
    sync_module_registry()


def _request_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def test_create_generalized_life_item_uses_default_module_instance() -> None:
    result = create_life_item(
        module_id="logs",
        item_type="log",
        title="Logged a useful signal",
        description="The person noticed a useful pattern.",
        payload={"text": "Useful pattern"},
        source={"kind": "test"},
        request_id=_request_id("log"),
    )

    assert result.created is True
    assert result.item["title"] == "Logged a useful signal"
    assert result.item["connection_status"] == "pending"
    assert result.item["chunk_status"] == "pending"
    assert result.item["bucket_update_status"] == "pending"

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id AS module_id, mi.settings
                FROM life_items li
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE li.id = %s
                """,
                (result.item["id"],),
            )
            row = cur.fetchone()
            assert row["module_id"] == "logs"
            assert row["settings"]["bucket_updates_enabled"] is True

            cur.execute("DELETE FROM life_items WHERE id = %s", (result.item["id"],))
        conn.commit()


def test_create_life_item_is_idempotent_by_request_id() -> None:
    request_id = _request_id("idempotent")
    first = create_life_item(
        module_id="logs",
        item_type="log",
        title="Original title",
        request_id=request_id,
    )
    second = create_life_item(
        module_id="logs",
        item_type="log",
        title="Changed title should not overwrite",
        request_id=request_id,
    )

    assert first.created is True
    assert second.created is False
    assert second.item["id"] == first.item["id"]
    assert second.item["title"] == "Original title"

    delete_life_item(first.item["id"])


def test_create_extended_task_writes_side_table_in_same_flow() -> None:
    result = create_life_item(
        module_id="tasks",
        item_type="task",
        title="Draft Phase 3 tests",
        request_id=_request_id("task"),
        payload={"module_status": "ready"},
        side_table_data={"priority": 2, "module_status": "ready"},
    )

    assert result.created is True
    assert result.item["chunk_status"] == "not_needed"
    assert result.item["bucket_update_status"] == "pending"

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT priority, module_status FROM task_items WHERE life_item_id = %s",
                (result.item["id"],),
            )
            row = cur.fetchone()
            assert row["priority"] == 2
            assert row["module_status"] == "ready"

    delete_life_item(result.item["id"])


def test_idempotent_extended_task_does_not_duplicate_side_table() -> None:
    request_id = _request_id("task-idempotent")
    first = create_life_item(
        module_id="tasks",
        item_type="task",
        title="Only one task side row",
        request_id=request_id,
        side_table_data={"priority": 1},
    )
    second = create_life_item(
        module_id="tasks",
        item_type="task",
        title="Duplicate request",
        request_id=request_id,
        side_table_data={"priority": 5},
    )

    assert second.created is False

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS count, MAX(priority) AS priority FROM task_items WHERE life_item_id = %s",
                (first.item["id"],),
            )
            row = cur.fetchone()
            assert row["count"] == 1
            assert row["priority"] == 1

    delete_life_item(first.item["id"])


def test_life_item_service_rejects_status_outside_module_subset() -> None:
    with pytest.raises(LifeItemError):
        create_life_item(
            module_id="logs",
            item_type="log",
            title="Logs cannot be completed",
            request_id=_request_id("bad-status"),
            lifecycle_status="completed",
        )


def test_meaningful_update_requeues_async_statuses() -> None:
    result = create_life_item(
        module_id="logs",
        item_type="log",
        title="Before update",
        request_id=_request_id("update"),
    )

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE life_items
                SET connection_status = 'complete',
                    chunk_status = 'complete',
                    bucket_update_status = 'complete'
                WHERE id = %s
                """,
                (result.item["id"],),
            )
        conn.commit()

    updated = update_life_item(
        result.item["id"],
        title="After update",
        payload={"text": "Changed meaning"},
    )

    assert updated["title"] == "After update"
    assert updated["connection_status"] == "pending"
    assert updated["chunk_status"] == "pending"
    assert updated["bucket_update_status"] == "pending"

    delete_life_item(result.item["id"])


def test_set_lifecycle_status_uses_module_subset() -> None:
    task = create_life_item(
        module_id="tasks",
        item_type="task",
        title="Complete me",
        request_id=_request_id("complete-task"),
    )
    completed = set_lifecycle_status(task.item["id"], "completed")

    assert completed["lifecycle_status"] == "completed"

    delete_life_item(task.item["id"])


def test_delete_life_item_cascades_extended_rows() -> None:
    result = create_life_item(
        module_id="tasks",
        item_type="task",
        title="Delete cascades",
        request_id=_request_id("delete-task"),
        side_table_data={"priority": 3},
    )

    delete_life_item(result.item["id"])

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM life_items WHERE id = %s", (result.item["id"],))
            assert cur.fetchone()["count"] == 0
            cur.execute("SELECT COUNT(*) AS count FROM task_items WHERE life_item_id = %s", (result.item["id"],))
            assert cur.fetchone()["count"] == 0
