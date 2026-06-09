from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import connect, ensure_schema
from app.lifecycle import LifeItemError
from app.main import app
from app.modules import sync_module_registry
from app.modules.tasks import (
    TaskCreate,
    TaskPrioritySuggestionUpdate,
    TaskUpdate,
    archive_task,
    complete_task,
    create_task,
    generate_task_priority_suggestion,
    get_task_priority_suggestion,
    list_tasks,
    remove_task,
    revert_task_rewrite,
    update_task_priority_suggestion,
    update_task,
)
from app.user_model import ensure_goals_seed, ensure_story_buckets


@pytest.fixture(autouse=True)
def tasks_ready(tmp_path) -> None:
    ensure_schema()
    sync_module_registry()
    with connect() as conn:
        ensure_story_buckets(tmp_path, conn)
        conn.commit()
    ensure_goals_seed(tmp_path)


def _request_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def test_create_task_writes_life_item_side_table_and_review(tmp_path) -> None:
    task = create_task(
        TaskCreate(
            title="Career work task",
            description="Professional context and career work identity.",
            due_date="2026-05-20",
            priority=2,
            module_status="ready",
            request_id=_request_id("task-create"),
        ),
        review_root=tmp_path,
    )

    assert task.title == "Career work task"
    assert task.lifecycle_status == "active"
    assert task.connection_status == "complete"
    assert task.chunk_status == "not_needed"
    assert task.bucket_update_status in {"complete", "not_needed"}
    assert task.priority == 2
    assert task.module_status == "ready"

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id AS module_id, ti.priority
                FROM life_items li
                JOIN task_items ti ON ti.life_item_id = li.id
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE li.id = %s
                """,
                (task.id,),
            )
            row = cur.fetchone()
            assert row["module_id"] == "tasks"
            assert row["priority"] == 2

            cur.execute("SELECT COUNT(*) AS count FROM item_connections WHERE source_life_item_id = %s", (task.id,))
            assert cur.fetchone()["count"] >= 1

    remove_task(task.id)


def test_create_task_defaults_due_window_this_week(tmp_path) -> None:
    task = create_task(
        TaskCreate(title="ship it", request_id=_request_id("task-due-window-default")),
        review=False,
        review_root=tmp_path,
    )

    assert task.due_window == "this_week"

    remove_task(task.id)


def test_create_task_exact_window_with_date(tmp_path) -> None:
    from datetime import date

    task = create_task(
        TaskCreate(
            title="dentist",
            due_window="exact",
            due_date=date(2026, 7, 1),
            request_id=_request_id("task-due-window-exact"),
        ),
        review=False,
        review_root=tmp_path,
    )

    assert task.due_window == "exact"
    assert task.due_date == date(2026, 7, 1)

    remove_task(task.id)


def test_create_task_preserves_original_on_rewrite(tmp_path) -> None:
    task = create_task(
        TaskCreate(
            title="email bob re: the q3 thing maybe",
            description="follow up",
            request_id=_request_id("task-rewrite-original"),
        ),
        review_root=tmp_path,
    )

    assert task.original_title == "email bob re: the q3 thing maybe"
    assert task.original_description == "follow up"
    assert task.rewrite_status in {"complete", "skipped"}
    assert task.title

    remove_task(task.id)


def test_revert_task_rewrite_restores_original(tmp_path) -> None:
    task = create_task(
        TaskCreate(
            title="orig title",
            description="orig body",
            request_id=_request_id("task-rewrite-revert"),
        ),
        review_root=tmp_path,
    )

    update_task(task.id, TaskUpdate(title="rewritten title"), review=False)
    reverted = revert_task_rewrite(task.id)

    assert reverted.title == "orig title"
    assert reverted.description == "orig body"

    remove_task(task.id)


def test_update_task_keeps_payload_and_side_table_in_sync(tmp_path) -> None:
    task = create_task(
        TaskCreate(
            title="Update me",
            description="Old description",
            priority=1,
            module_status="blocked",
            request_id=_request_id("task-update"),
        ),
        review=False,
        review_root=tmp_path,
    )

    updated = update_task(
        task.id,
        TaskUpdate(
            title="Updated task",
            description="New description",
            priority=4,
            module_status="next",
        ),
    )

    assert updated.title == "Updated task"
    assert updated.description == "New description"
    assert updated.priority == 4
    assert updated.module_status == "next"
    assert updated.connection_status == "complete"

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM life_items WHERE id = %s", (task.id,))
            payload = cur.fetchone()["payload"]
            assert payload["priority"] == 4
            assert payload["module_status"] == "next"

    remove_task(task.id)


def test_update_task_can_clear_optional_exact_fields() -> None:
    task = create_task(
        TaskCreate(
            title="Clear optional fields",
            due_date="2026-05-25",
            priority=2,
            module_status="blocked",
            request_id=_request_id("task-clear"),
        ),
        review=False,
    )

    updated = update_task(
        task.id,
        TaskUpdate(due_date=None, priority=None, module_status=None),
        review=False,
    )

    assert updated.due_date is None
    assert updated.priority is None
    assert updated.module_status is None

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM life_items WHERE id = %s", (task.id,))
            payload = cur.fetchone()["payload"]
            assert payload["due_date"] is None
            assert payload["priority"] is None
            assert payload["module_status"] is None

    remove_task(task.id)


def test_complete_archive_and_delete_task() -> None:
    task = create_task(
        TaskCreate(title="Complete then delete", request_id=_request_id("task-complete")),
        review=False,
    )

    completed = complete_task(task.id)
    assert completed.lifecycle_status == "completed"
    assert completed.completed_at is not None

    archived = archive_task(task.id)
    assert archived.lifecycle_status == "archived"

    remove_task(task.id)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM life_items WHERE id = %s", (task.id,))
            assert cur.fetchone()["count"] == 0
            cur.execute("SELECT COUNT(*) AS count FROM task_items WHERE life_item_id = %s", (task.id,))
            assert cur.fetchone()["count"] == 0


def test_priority_suggestion_fallback_persists_and_can_update() -> None:
    first = create_task(
        TaskCreate(title="Due today", due_date="2026-05-15", priority=3, request_id=_request_id("suggest-one")),
        review=False,
    )
    second = create_task(
        TaskCreate(title="Later task", due_date="2026-06-01", priority=5, request_id=_request_id("suggest-two")),
        review=False,
    )

    suggestion = generate_task_priority_suggestion()

    assert suggestion.id is not None
    assert suggestion.status == "active"
    assert suggestion.panel_visible is True
    assert suggestion.ranked
    assert suggestion.ranked[0].task_id == first.id

    loaded = get_task_priority_suggestion()
    assert loaded.id == suggestion.id

    updated = update_task_priority_suggestion(
        suggestion.id,
        TaskPrioritySuggestionUpdate(sort_enabled=True, panel_visible=False),
    )
    assert updated.sort_enabled is True
    assert updated.panel_visible is False

    remove_task(first.id)
    remove_task(second.id)


def test_new_task_invalidates_active_priority_suggestion() -> None:
    create_task(TaskCreate(title="Existing focus", request_id=_request_id("suggest-existing")), review=False)
    suggestion = generate_task_priority_suggestion()
    assert suggestion.status == "active"

    create_task(TaskCreate(title="New task clears suggestion", request_id=_request_id("suggest-clear")), review=False)

    assert get_task_priority_suggestion().status == "empty"


def test_invalid_llm_task_ids_are_ignored(monkeypatch) -> None:
    task = create_task(TaskCreate(title="Real task", request_id=_request_id("suggest-real")), review=False)

    def fake_generate_json(*args, **kwargs):
        return {
            "summary": "Ignore fake ids.",
            "ranked": [
                {"task_id": str(uuid4()), "title": "Fake", "reason": "Should be dropped."},
                {"task_id": str(task.id), "title": "Real task", "reason": "This one exists."},
            ],
            "skippable": [{"task_id": str(uuid4()), "title": "Fake skip", "reason": "Also dropped."}],
        }

    monkeypatch.setattr("app.modules.tasks.generate_json", fake_generate_json)

    suggestion = generate_task_priority_suggestion()

    assert [entry.task_id for entry in suggestion.ranked] == [task.id]
    assert suggestion.skippable == []

    remove_task(task.id)


def test_list_tasks_filters_by_lifecycle_status() -> None:
    active = create_task(
        TaskCreate(title="Active task", request_id=_request_id("active-task")),
        review=False,
    )
    completed = create_task(
        TaskCreate(title="Completed task", request_id=_request_id("completed-task")),
        review=False,
    )
    complete_task(completed.id)

    active_ids = {task.id for task in list_tasks(status="active", limit=20)}
    completed_ids = {task.id for task in list_tasks(status="completed", limit=20)}

    assert active.id in active_ids
    assert completed.id not in active_ids
    assert completed.id in completed_ids

    remove_task(active.id)
    remove_task(completed.id)


def test_task_service_rejects_unknown_task() -> None:
    with pytest.raises(LifeItemError):
        remove_task(uuid4())


def test_tasks_api_create_update_complete_delete() -> None:
    client = TestClient(app)
    request_id = _request_id("api-task")

    create_response = client.post(
        "/modules/tasks",
        json={
            "title": "Build Task API",
            "description": "Exercise extended storage through HTTP.",
            "priority": 3,
            "module_status": "ready",
            "request_id": request_id,
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["title"] == "Build Task API"
    assert created["priority"] == 3

    update_response = client.patch(
        f"/modules/tasks/{created['id']}",
        json={
            "title": "Build polished Task API",
            "priority": 5,
            "module_status": "next",
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["title"] == "Build polished Task API"
    assert update_response.json()["priority"] == 5

    complete_response = client.post(f"/modules/tasks/{created['id']}/complete")
    assert complete_response.status_code == 200
    assert complete_response.json()["lifecycle_status"] == "completed"
    assert complete_response.json()["completed_at"] is not None

    archive_response = client.post(f"/modules/tasks/{created['id']}/archive")
    assert archive_response.status_code == 404

    archived_list_response = client.get("/modules/tasks", params={"status": "archived"})
    assert archived_list_response.status_code == 422

    delete_response = client.delete(f"/modules/tasks/{created['id']}")
    assert delete_response.status_code == 204

    get_deleted = client.get(f"/modules/tasks/{created['id']}")
    assert get_deleted.status_code == 404
