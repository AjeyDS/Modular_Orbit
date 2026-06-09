from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.chat import (
    ChatRequest,
    list_chat_messages,
    list_chat_sessions,
    respond_to_chat,
)
from app.db import connect, ensure_schema
from app.main import app
from app.modules import sync_module_registry
from app.user_model import ensure_goals_seed, ensure_story_buckets


def _ready(tmp_path) -> None:
    ensure_schema()
    sync_module_registry()
    with connect() as conn:
        ensure_story_buckets(tmp_path, conn)
        conn.commit()
    ensure_goals_seed(tmp_path)


def _session_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def test_respond_to_chat_persists_messages_and_sets_title(tmp_path) -> None:
    _ready(tmp_path)
    session_id = _session_id("persist")

    respond_to_chat(
        ChatRequest(
            session_id=session_id,
            mode="context",
            message="Help me think through whether to switch teams",
        )
    )
    respond_to_chat(
        ChatRequest(
            session_id=session_id,
            mode="context",
            message="What other factors should I weigh?",
        )
    )

    messages = list_chat_messages(session_id)
    assert [m.role for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0].content == "Help me think through whether to switch teams"
    assert messages[0].mode == "context"
    assert messages[1].mode is None  # assistant rows leave mode null

    sessions = list_chat_sessions()
    matching = [s for s in sessions if s.id == session_id]
    assert len(matching) == 1
    session = matching[0]
    assert session.title == "Help me think through whether to switch teams"
    assert session.message_count == 4
    assert session.last_message_at is not None


def test_session_listing_excludes_counter_only_sessions_and_orders_by_recency(
    tmp_path,
) -> None:
    _ready(tmp_path)
    older = _session_id("older")
    newer = _session_id("newer")

    respond_to_chat(ChatRequest(session_id=older, message="First message in older session"))
    respond_to_chat(ChatRequest(session_id=newer, message="First message in newer session"))

    # Insert a counter-only legacy row directly — must NOT show up in listing.
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_sessions (id) VALUES (%s) ON CONFLICT DO NOTHING",
                (_session_id("counter-only"),),
            )
        conn.commit()

    sessions = list_chat_sessions()
    ids_in_order = [s.id for s in sessions]
    assert newer in ids_in_order
    assert older in ids_in_order
    assert ids_in_order.index(newer) < ids_in_order.index(older)
    counter_only_ids = [s.id for s in sessions if s.id.startswith("counter-only-")]
    assert counter_only_ids == []


def test_rename_and_delete_session_endpoints(tmp_path) -> None:
    _ready(tmp_path)
    session_id = _session_id("crud")
    respond_to_chat(
        ChatRequest(session_id=session_id, message="Original title from first message")
    )

    client = TestClient(app)

    rename = client.patch(
        f"/api/chat/sessions/{session_id}",
        json={"title": "Switching teams discussion"},
    )
    assert rename.status_code == 200
    assert rename.json()["title"] == "Switching teams discussion"

    listing = client.get("/api/chat/sessions")
    assert listing.status_code == 200
    titles = {item["id"]: item["title"] for item in listing.json()}
    assert titles[session_id] == "Switching teams discussion"

    delete = client.delete(f"/api/chat/sessions/{session_id}")
    assert delete.status_code == 204

    after = client.get("/api/chat/sessions")
    assert session_id not in {item["id"] for item in after.json()}

    missing_messages = client.get(f"/api/chat/sessions/{session_id}/messages")
    assert missing_messages.status_code == 404
