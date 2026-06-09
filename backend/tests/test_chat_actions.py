from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.chat import ChatRequest, ConfirmCaptureProposalRequest, confirm_capture_proposal, respond_to_chat
from app.chat.actions import _build_answer_context, _detect_capture_proposals
from app.db import connect, ensure_schema
from app.main import app
from app.modules.documents import DocumentCreate, create_document, remove_document
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


def test_questions_do_not_produce_capture_suggestions() -> None:
    assert _detect_capture_proposals("what's my EAD start date?") == []
    assert _detect_capture_proposals("when is my appointment?") == []


def test_confirming_goal_proposal_creates_tentative_goal() -> None:
    from app.chat.actions import (
        ConfirmCaptureProposalRequest,
        _persist_preview,
        _proposal_for_module,
        confirm_capture_proposal,
    )
    from app.user_model.goals import list_goals

    session_id = _session_id("goal-confirm")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_sessions (id) VALUES (%s) ON CONFLICT DO NOTHING",
                (session_id,),
            )
        conn.commit()

    proposal = _proposal_for_module("goals", "become a staff engineer", explicit=True)
    preview = _persist_preview(session_id, proposal)
    resp = confirm_capture_proposal(ConfirmCaptureProposalRequest(proposal_id=preview.id))
    assert resp.goal_id is not None
    assert any(g.goal_id == resp.goal_id and g.status == "tentative" for g in list_goals())


def test_explicit_add_goal_detected() -> None:
    proposals = _detect_capture_proposals("add this as a goal: become a staff engineer")
    assert proposals and proposals[0].module_id == "goals"
    assert proposals[0].item_type == "goal"


def test_explicit_add_still_works_inside_a_question_form() -> None:
    proposals = _detect_capture_proposals("add this to tasks: renew passport")
    assert proposals and proposals[0].module_id == "tasks"


def test_fast_mode_attaches_no_buckets(tmp_path) -> None:
    _ready(tmp_path)
    from app.chat.actions import _build_answer_context
    fast_ctx = _build_answer_context("fast", "what are my career goals")
    understanding_ctx = _build_answer_context("understanding", "what should I focus on in my career")
    assert "Story Buckets:" not in fast_ctx
    assert "Story Buckets:" in understanding_ctx


def test_understanding_retrieval_caps_followups(tmp_path, monkeypatch) -> None:
    _ready(tmp_path)
    import app.chat.actions as actions
    from app.chat.actions import _understanding_retrieval, RouteDecision

    calls = {"n": 0}

    def fake_retrieve(query, *, limit=4):
        calls["n"] += 1
        return []

    monkeypatch.setattr(actions, "retrieve_chunks", fake_retrieve)
    monkeypatch.setattr(actions, "_sufficiency_check", lambda message, chunks: (False, "dentist friday"))

    _understanding_retrieval("when is my dentist appointment", RouteDecision(breadth="narrow", buckets=["health"]))
    assert calls["n"] <= 2


def test_retrieval_query_does_not_dilute_narrow(tmp_path) -> None:
    _ready(tmp_path)
    from app.chat.actions import _retrieval_query, RouteDecision
    narrow = RouteDecision(breadth="narrow", buckets=["career"], expansion_terms=["promotion", "mentoring"])
    broad = RouteDecision(breadth="broad", buckets=["career", "aspirations"], expansion_terms=["promotion", "mentoring"])
    msg = "when is my dentist appointment"
    assert _retrieval_query(msg, narrow) == msg
    assert "promotion" in _retrieval_query(msg, broad)
    assert _retrieval_query(msg, broad).startswith(msg)


def test_router_fallback_selects_buckets_and_breadth(tmp_path) -> None:
    _ready(tmp_path)
    from app.chat.actions import _route_and_classify
    narrow = _route_and_classify("when is my dentist appointment on friday")
    broad = _route_and_classify("what are the main things I should focus on in my life right now")
    assert narrow.breadth == "narrow"
    assert broad.breadth == "broad"
    assert all(key in {
        "who_am_i", "interests_and_works", "career", "health", "relationships", "habits", "aspirations"
    } for key in broad.buckets)
    assert 1 <= len(broad.buckets) <= 3
    assert narrow.expansion_terms == []


def test_chat_mode_accepts_two_modes(tmp_path) -> None:
    _ready(tmp_path)
    fast = respond_to_chat(ChatRequest(session_id=_session_id("fast"), mode="fast", message="hi there orbit"))
    understanding = respond_to_chat(ChatRequest(session_id=_session_id("u"), mode="understanding", message="hi there orbit"))
    assert fast.mode == "fast"
    assert understanding.mode == "understanding"


def test_explicit_task_request_creates_preview(tmp_path) -> None:
    _ready(tmp_path)
    response = respond_to_chat(
        ChatRequest(
            session_id=_session_id("explicit-task"),
            mode="understanding",
            message="add this to tasks: Build the suggested chat action preview",
        )
    )

    assert response.mode == "understanding"
    assert len(response.suggestions) == 1
    suggestion = response.suggestions[0]
    assert suggestion.module_id == "tasks"
    assert suggestion.item_type == "task"
    assert suggestion.explicit_request is True
    assert suggestion.confidence_bucket == "high"
    assert suggestion.should_create_bucket_update is True


def test_suggested_task_respects_threshold_and_session_cap(tmp_path) -> None:
    _ready(tmp_path)
    session_id = _session_id("suggested-cap")

    first = respond_to_chat(
        ChatRequest(
            session_id=session_id,
            message="I need to build the first useful task for Orbit tomorrow.",
        )
    )
    second = respond_to_chat(
        ChatRequest(
            session_id=session_id,
            message="I should write the second useful task for Orbit tomorrow.",
        )
    )
    third = respond_to_chat(
        ChatRequest(
            session_id=session_id,
            message="Remind me to write the third useful task for Orbit tomorrow.",
        )
    )

    assert len(first.suggestions) == 1
    assert len(second.suggestions) == 1
    assert len(third.suggestions) == 0


def test_explicit_request_bypasses_session_cap(tmp_path) -> None:
    _ready(tmp_path)
    session_id = _session_id("explicit-bypass")

    respond_to_chat(
        ChatRequest(session_id=session_id, message="I need to build a useful Orbit task one.")
    )
    respond_to_chat(
        ChatRequest(session_id=session_id, message="I should build a useful Orbit task two.")
    )
    explicit = respond_to_chat(
        ChatRequest(
            session_id=session_id,
            message="add this to tasks: Build a task even after the suggestion cap",
        )
    )

    assert len(explicit.suggestions) == 1
    assert explicit.suggestions[0].explicit_request is True


def test_low_confidence_message_surfaces_no_suggestion(tmp_path) -> None:
    _ready(tmp_path)
    response = respond_to_chat(
        ChatRequest(
            session_id=_session_id("low-confidence"),
            message="Interesting.",
        )
    )

    assert response.suggestions == []


def test_standard_chat_fallback_surfaces_retrieved_document_context(tmp_path) -> None:
    _ready(tmp_path)
    document = create_document(
        DocumentCreate(
            original_name="Resume.pdf",
            content="Resume says Python, machine learning, RAG pipelines, and data science projects.",
            unique_name="resume",
            request_id=f"chat-resume-{uuid4().hex}",
        ),
        review=False,
    )

    response = respond_to_chat(
        ChatRequest(
            session_id=_session_id("resume-context"),
            mode="understanding",
            message="What does my resume say about RAG?",
        )
    )

    assert "retrieve context for this turn" in response.answer
    assert "Resume.pdf" in response.answer
    assert "RAG" in response.answer

    remove_document(document.id)


def test_context_chat_prioritizes_rag_chunks_over_recent_module_data(tmp_path) -> None:
    _ready(tmp_path)
    document = create_document(
        DocumentCreate(
            original_name="Resume.pdf",
            content="Resume says Python, machine learning, RAG pipelines, and data science projects.",
            unique_name="resume",
            request_id=f"chat-context-resume-{uuid4().hex}",
        ),
        review=False,
    )

    context = _build_answer_context("understanding", "What does my resume say about RAG?")

    assert "Knowledge Chunks:" in context
    assert "Story Buckets:" in context
    assert context.index("Knowledge Chunks:") < context.index("Story Buckets:")
    assert "- From Resume.pdf" in context

    remove_document(document.id)


def test_ignore_is_no_signal_in_v0(tmp_path) -> None:
    _ready(tmp_path)
    session_id = _session_id("ignore")

    response = respond_to_chat(
        ChatRequest(
            session_id=session_id,
            message="I need to keep this suggested task as only a preview.",
        )
    )

    proposal_id = response.suggestions[0].id
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status, created_life_item_id FROM capture_proposals WHERE id = %s", (proposal_id,))
            row = cur.fetchone()

    assert row["status"] == "previewed"
    assert row["created_life_item_id"] is None


def test_confirm_task_proposal_creates_life_item_once(tmp_path) -> None:
    _ready(tmp_path)
    response = respond_to_chat(
        ChatRequest(
            session_id=_session_id("confirm-task"),
            message="add this to tasks: Confirm the chat proposal into a task",
        )
    )
    proposal_id = response.suggestions[0].id

    first = confirm_capture_proposal(ConfirmCaptureProposalRequest(proposal_id=proposal_id))
    second = confirm_capture_proposal(ConfirmCaptureProposalRequest(proposal_id=proposal_id))

    assert first.life_item_id == second.life_item_id
    assert first.module_id == "tasks"
    assert first.status == "accepted"

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT li.title, m.id AS module_id
                FROM life_items li
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE li.id = %s
                """,
                (first.life_item_id,),
            )
            row = cur.fetchone()

    assert row["module_id"] == "tasks"
    assert row["title"] == "Confirm the chat proposal into a task"


def test_explicit_plan_confirmation_creates_plan_steps(tmp_path) -> None:
    _ready(tmp_path)
    response = respond_to_chat(
        ChatRequest(
            session_id=_session_id("confirm-plan"),
            message="make this a plan:\nDesign chat actions\nBuild confirmation flow",
        )
    )

    confirmed = confirm_capture_proposal(
        ConfirmCaptureProposalRequest(proposal_id=response.suggestions[0].id)
    )

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM plan_steps WHERE life_item_id = %s", (confirmed.life_item_id,))
            count = cur.fetchone()["count"]

    assert confirmed.module_id == "plans"
    assert count == 2


def test_chat_api_respond_and_confirm(tmp_path) -> None:
    _ready(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/chat/respond",
        json={
            "session_id": _session_id("api-chat"),
            "mode": "fast",
            "message": "log this: Today I learned that Orbit chat actions need previews.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "fast"
    assert body["suggestions"][0]["module_id"] == "logs"

    confirm_response = client.post(
        "/chat/capture-proposals/confirm",
        json={"proposal_id": body["suggestions"][0]["id"]},
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["module_id"] == "logs"
