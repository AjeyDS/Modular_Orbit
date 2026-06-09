from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.chat import ChatRequest
from app.chat.actions import respond_to_chat_stream
from app.db import connect, ensure_schema
from app.llm import LLMUnavailable
from app.llm.client import generate_text_stream
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


def test_generate_text_stream_raises_when_disabled() -> None:
    with pytest.raises(LLMUnavailable):
        list(generate_text_stream("hi", system="s"))


def test_stream_emits_stages_then_answer_and_done(tmp_path) -> None:
    _ready(tmp_path)
    events = list(
        respond_to_chat_stream(
            ChatRequest(session_id=f"s1-{uuid4().hex}", mode="understanding", message="hello")
        )
    )
    stages = [e["stage"] for e in events]
    assert stages[0] in {"routing", "retrieving"}
    assert "writing" in stages
    assert any(e["stage"] == "answer" for e in events)
    assert stages[-1] == "done"
    done = events[-1]
    assert "suggestions" in done


def test_stream_emits_checking_state_for_structured_query(tmp_path) -> None:
    _ready(tmp_path)
    events = list(
        respond_to_chat_stream(
            ChatRequest(
                session_id=f"s1-{uuid4().hex}",
                mode="understanding",
                message="what tasks are overdue?",
            )
        )
    )
    stages = [e["stage"] for e in events]
    assert "checking_state" in stages
    assert stages.index("checking_state") > stages.index("routing")
    assert stages.index("retrieving") > stages.index("checking_state")


def test_stream_skips_checking_state_for_non_structured_query(tmp_path) -> None:
    _ready(tmp_path)
    events = list(
        respond_to_chat_stream(
            ChatRequest(
                session_id=f"s1-{uuid4().hex}",
                mode="understanding",
                message="tell me a story about the ocean",
            )
        )
    )
    stages = [e["stage"] for e in events]
    assert "checking_state" not in stages


def test_sse_endpoint_streams_events(tmp_path) -> None:
    _ready(tmp_path)
    client = TestClient(app)
    with client.stream(
        "POST",
        "/chat/respond/stream",
        json={"session_id": f"s1-{uuid4().hex}", "mode": "fast", "message": "hi"},
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        payloads = []
        for line in response.iter_lines():
            if line and line.startswith("data:"):
                payloads.append(json.loads(line[len("data:") :].strip()))
    assert payloads[-1]["stage"] == "done"
