from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.chat import ItemChatRequest, build_item_chat_context, chat_with_item
from app.db import connect, ensure_schema
from app.lifecycle import create_life_item, delete_life_item, review_life_item
from app.main import app
from app.modules import sync_module_registry
from app.modules.tasks import TaskCreate, TaskUpdate, create_task, remove_task, update_task
from app.user_model import ensure_goals_seed, ensure_story_buckets


@pytest.fixture(autouse=True)
def item_chat_ready(tmp_path) -> None:
    ensure_schema()
    sync_module_registry()
    with connect() as conn:
        ensure_story_buckets(tmp_path, conn)
        conn.commit()
    ensure_goals_seed(tmp_path)


def _request_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def test_item_chat_answers_from_task_payload_and_one_hop_connections(tmp_path) -> None:
    task = create_task(
        TaskCreate(
            title="Career Item Chat task",
            description="Discuss career work identity and professional context.",
            priority=2,
            module_status="ready",
            request_id=_request_id("item-chat-task"),
        ),
        review_root=tmp_path,
    )

    response = chat_with_item(
        task.id,
        ItemChatRequest(message="What should I remember about this task?"),
        root=tmp_path,
    )

    assert response.needs_context_chat is False
    assert response.context.life_item_id == task.id
    assert response.context.module_id == "tasks"
    assert response.context.payload["priority"] == 2
    assert response.context.connections
    assert "One-hop connections in scope" in response.answer

    remove_task(task.id)


def test_item_chat_shows_pending_connection_state() -> None:
    task = create_task(
        TaskCreate(
            title="Pending Item Chat",
            description="Connection Review has not run yet.",
            request_id=_request_id("item-chat-pending"),
        ),
        review=False,
    )

    response = chat_with_item(
        task.id,
        ItemChatRequest(message="Can we discuss this before review finishes?"),
    )

    assert response.context.connection_status == "pending"
    assert "Connection Review is pending" in response.answer

    remove_task(task.id)


def test_item_chat_payload_edits_are_visible_on_next_turn() -> None:
    task = create_task(
        TaskCreate(
            title="Mutable Item Chat",
            description="Initial task state.",
            priority=1,
            request_id=_request_id("item-chat-edit"),
        ),
        review=False,
    )

    update_task(
        task.id,
        TaskUpdate(priority=5, module_status="next"),
        review=False,
    )

    context = build_item_chat_context(task.id)

    assert context.payload["priority"] == 5
    assert context.payload["module_status"] == "next"

    remove_task(task.id)


def test_item_chat_flags_broad_context_without_silent_expansion(tmp_path) -> None:
    task = create_task(
        TaskCreate(
            title="Scoped Task",
            description="This task should not silently search all plans.",
            request_id=_request_id("item-chat-broad"),
        ),
        review_root=tmp_path,
    )

    response = chat_with_item(
        task.id,
        ItemChatRequest(message="What was the original plan this came from across all plans?"),
        root=tmp_path,
    )

    assert response.needs_context_chat is True
    assert response.suggested_action is not None
    assert response.suggested_action.label == "Open in Context Chat"
    assert "broader context" in response.answer

    remove_task(task.id)


def test_item_chat_includes_derived_chunks() -> None:
    item = create_life_item(
        module_id="logs",
        item_type="log",
        title="Chunked item",
        description="Item Chat should include derived chunks.",
        request_id=_request_id("item-chat-chunk"),
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO knowledge_chunks (life_item_id, content, metadata)
                VALUES (%s, 'Derived chunk text for item chat.', '{"kind": "test"}'::jsonb)
                """,
                (item.item["id"],),
            )
        conn.commit()

    response = chat_with_item(
        item.item["id"],
        ItemChatRequest(message="What evidence do you have?"),
    )

    assert len(response.context.derived_chunks) == 1
    assert response.context.derived_chunks[0].content == "Derived chunk text for item chat."

    delete_life_item(item.item["id"])


def test_item_chat_api_uses_current_item_context(tmp_path) -> None:
    task = create_task(
        TaskCreate(
            title="API Item Chat",
            description="Exercise Item Chat through HTTP.",
            priority=3,
            request_id=_request_id("item-chat-api"),
        ),
        review_root=tmp_path,
    )
    client = TestClient(app)

    response = client.post(
        f"/item-chat/{task.id}",
        json={"message": "Discuss this task briefly."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["context"]["life_item_id"] == str(task.id)
    assert body["context"]["module_id"] == "tasks"
    assert body["context"]["payload"]["priority"] == 3

    remove_task(task.id)


def test_item_chat_rejects_module_with_item_chat_disabled() -> None:
    item = create_life_item(
        module_id="chat",
        item_type="chat_surface",
        title="Chat config item",
        request_id=_request_id("disabled-item-chat"),
    )

    client = TestClient(app)
    response = client.post(
        f"/item-chat/{item.item['id']}",
        json={"message": "Can I discuss this?"},
    )

    assert response.status_code == 404

    delete_life_item(item.item["id"])
