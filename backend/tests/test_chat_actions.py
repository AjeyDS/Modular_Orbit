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


def test_is_focus_query() -> None:
    from app.chat.actions import _is_focus_query

    assert _is_focus_query("what should I focus on today?") is True
    assert _is_focus_query("how should I prioritize my week?") is True
    assert _is_focus_query("when is my dentist appointment?") is False


def test_is_advice_query() -> None:
    from app.chat.actions import _is_advice_query

    assert _is_advice_query("what can I learn next to fuel my career?") is True
    assert _is_advice_query("how can I improve from here?") is True
    assert _is_advice_query("when is my dentist appointment?") is False


def test_think_fallback_classifies_focus_and_advice() -> None:
    from app.chat.actions import ThinkingPlan, _think

    plan1 = _think("what should I focus on today?")
    assert isinstance(plan1, ThinkingPlan)
    assert plan1.question_type in {"prioritize", "open"}
    assert plan1.approach
    plan2 = _think("what can I learn next to fuel my career?")
    assert plan2.question_type in {"gap_analysis", "open"}


def test_think_llm_path(monkeypatch) -> None:
    import app.chat.actions as actions

    monkeypatch.setattr(
        actions,
        "generate_json",
        lambda *args, **kwargs: {
            "question_type": "lookup",
            "approach": "Give the exact value plainly.",
            "retrieval_hint": "tasks and documents",
        },
    )
    plan = actions._think("when is my dentist appointment?")
    assert plan.question_type == "lookup"
    assert "exact value" in plan.approach
    assert "tasks" in plan.retrieval_hint


def test_router_uses_retrieval_hint(monkeypatch) -> None:
    import app.chat.actions as actions
    from app.chat.actions import ThinkingPlan, _route_and_classify

    captured: dict[str, str] = {}

    def fake(prompt, *, system, **kwargs):
        captured["prompt"] = prompt
        return {
            "breadth": "narrow",
            "buckets": ["career"],
            "modules": ["tasks"],
            "expansion_terms": [],
        }

    monkeypatch.setattr(actions, "generate_json", fake)
    _route_and_classify(
        "help me",
        ThinkingPlan("prioritize", "rank things", "focus on tasks and routines"),
    )
    assert "focus on tasks and routines" in captured["prompt"] or "prioritize" in captured["prompt"]


def test_router_plan_optional_back_compat() -> None:
    from app.chat.actions import _route_and_classify

    decision = _route_and_classify("what tasks are overdue?")
    assert "tasks" in decision.modules


def test_advice_query_forces_actionable_modules() -> None:
    from app.chat.actions import _route_and_classify

    decision = _route_and_classify("what can I learn next to fuel my career?")
    assert {"tasks", "plans", "routines", "goals"} <= set(decision.modules)
    assert decision.breadth == "broad"


def test_advice_query_includes_structured_context(tmp_path) -> None:
    _ready(tmp_path)
    from app.modules.tasks import TaskCreate, create_task

    create_task(TaskCreate(title="Renew passport"), review=False)
    ctx = _build_answer_context("understanding", "what can I learn next to fuel my career?")
    assert "Structured data" in ctx
    assert "Renew passport" in ctx


def test_focus_query_forces_actionable_modules() -> None:
    from app.chat.actions import _route_and_classify

    decision = _route_and_classify("what should I focus on today?")
    assert {"tasks", "plans", "routines", "goals"} <= set(decision.modules)
    assert decision.breadth == "broad"


def test_focus_query_includes_structured_context(tmp_path) -> None:
    _ready(tmp_path)
    from app.modules.tasks import TaskCreate, create_task

    create_task(TaskCreate(title="Renew passport"), review=False)
    ctx = _build_answer_context("understanding", "what should I focus on today?")
    assert "Structured data" in ctx
    assert "Renew passport" in ctx


def test_router_selects_modules_via_lexical_fallback() -> None:
    from app.chat.actions import _route_and_classify, QUERYABLE_MODULES

    d1 = _route_and_classify("what tasks are overdue?")
    assert "tasks" in d1.modules
    d2 = _route_and_classify("did I do my routine today?")
    assert "routines" in d2.modules
    d3 = _route_and_classify("tell me a story about the ocean")
    assert d3.modules == []
    d4 = _route_and_classify("my short-term goals?")
    assert "goals" in d4.modules
    d5 = _route_and_classify("how far is my OPT plan?")
    assert "plans" in d5.modules
    assert d1.modules == [m for m in d1.modules if m in QUERYABLE_MODULES]


def test_structured_context_renders_selected_modules(tmp_path) -> None:
    _ready(tmp_path)
    from app.chat.actions import _structured_context
    from app.modules.tasks import TaskCreate, create_task
    from app.user_model.goals import create_goal

    create_task(TaskCreate(title="Renew passport"), review=False)
    create_goal(title="Start an LLC", status="active", horizon="short_term")
    block = _structured_context(["tasks", "goals"])
    assert "Renew passport" in block
    assert "Start an LLC" in block


def test_structured_context_empty_when_no_modules() -> None:
    from app.chat.actions import _structured_context

    assert _structured_context([]) == ""


def test_understanding_context_includes_structured_block_for_task_query(tmp_path) -> None:
    _ready(tmp_path)
    from app.modules.tasks import TaskCreate, create_task

    create_task(TaskCreate(title="File taxes"), review=False)
    ctx = _build_answer_context("understanding", "what tasks are overdue?")
    assert "Structured data" in ctx
    assert "File taxes" in ctx


def test_fast_mode_has_no_structured_block(tmp_path) -> None:
    _ready(tmp_path)
    from app.modules.tasks import TaskCreate, create_task

    create_task(TaskCreate(title="File taxes"), review=False)
    ctx = _build_answer_context("fast", "what tasks are overdue?")
    assert "Structured data" not in ctx


def test_collect_sources_dedups_and_labels() -> None:
    from app.chat.actions import RouteDecision, _collect_sources
    from app.rag.retrieval import RetrievedChunk

    chunks = [
        RetrievedChunk(id="1", life_item_id="a", title="OPT Action Plan", content="x", source_type="document"),
        RetrievedChunk(id="2", life_item_id="a", title="OPT Action Plan", content="y", source_type="document"),
        RetrievedChunk(id="3", life_item_id="b", title="Resume", content="z", source_type="document"),
    ]
    decision = RouteDecision(breadth="broad", buckets=["career"], modules=["tasks"])
    refs = _collect_sources(chunks, decision)
    labels = [(r.kind, r.label) for r in refs]
    assert ("document", "OPT Action Plan") in labels
    assert ("document", "Resume") in labels
    assert labels.count(("document", "OPT Action Plan")) == 1
    assert ("bucket", "career") in labels or any(r.kind == "bucket" for r in refs)
    assert any(r.kind == "module" and r.label.lower() == "tasks" for r in refs)


def test_collect_sources_fast_mode_chunks_only() -> None:
    from app.chat.actions import _collect_sources
    from app.rag.retrieval import RetrievedChunk

    chunks = [RetrievedChunk(id="1", life_item_id="a", title="Resume", content="z", source_type="document")]
    refs = _collect_sources(chunks, None)
    assert all(r.kind in {"document", "item"} for r in refs)


def test_chat_response_includes_sources(tmp_path) -> None:
    _ready(tmp_path)
    from app.chat.actions import ChatRequest, respond_to_chat

    resp = respond_to_chat(ChatRequest(session_id=_session_id("sources"), mode="understanding", message="hello"))
    assert isinstance(resp.sources, list)


def test_system_prompt_mentions_clean_formatting() -> None:
    from app.chat.actions import _chat_system_prompt

    prompt = _chat_system_prompt("understanding").lower()
    assert "bullet" in prompt or "format" in prompt


def test_understanding_prompt_has_focus_ranking_guidance() -> None:
    from app.chat.actions import _FOCUS_APPROACH, _chat_system_prompt

    prompt = _chat_system_prompt("understanding").lower()
    assert "approach" in prompt
    focus = _FOCUS_APPROACH.lower()
    assert "prioritize" in focus or "rank" in focus
    assert "due" in focus


def test_prompt_discourages_raw_field_labels() -> None:
    from app.chat.actions import _chat_system_prompt

    prompt = _chat_system_prompt("understanding").lower()
    assert "plain" in prompt or "raw field" in prompt or "verbatim" in prompt


def test_prompt_allows_advice_but_guards_personal_facts() -> None:
    from app.chat.actions import _chat_system_prompt

    prompt = _chat_system_prompt("understanding").lower()
    assert "never invent" in prompt or "do not invent" in prompt
    assert "general" in prompt and ("suggest" in prompt or "gap" in prompt)


def test_understanding_prompt_has_gap_instruction() -> None:
    from app.chat.actions import _GAP_APPROACH, _chat_system_prompt

    prompt = _chat_system_prompt("understanding").lower()
    assert "approach" in prompt
    gap = _GAP_APPROACH.lower()
    assert "have not" in gap or "haven't" in gap or "not already listed" in gap
    assert "fabricate" in gap or "do not invent specific" in gap


def test_answer_prompt_includes_plan_approach() -> None:
    from app.chat.actions import ChatRequest, ThinkingPlan, _answer_prompt

    prompt = _answer_prompt(
        message="x",
        context="ctx",
        suggestions=[],
        mode="understanding",
        plan=ThinkingPlan("gap_analysis", "Find gaps beyond their inputs.", ""),
    )
    assert "Find gaps beyond their inputs." in prompt


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


def test_recent_history_returns_last_turns_in_order() -> None:
    from app.chat.actions import _recent_history
    from app.chat.sessions import insert_chat_message, upsert_session_for_message
    from app.db import transaction

    sid = _session_id("hist")
    # Separate transactions so created_at differs per turn, matching production
    # (now() is constant within a single transaction).
    with transaction() as conn:
        upsert_session_for_message(conn, sid, initial_title="t")
        insert_chat_message(conn, session_id=sid, role="user", content="first")
    with transaction() as conn:
        insert_chat_message(conn, session_id=sid, role="assistant", content="answer one")
    with transaction() as conn:
        insert_chat_message(conn, session_id=sid, role="user", content="second")
    hist = _recent_history(sid, limit=6)
    assert [r for r, _ in hist] == ["user", "assistant", "user"]
    assert hist[0][1] == "first" and hist[-1][1] == "second"


def test_recent_history_empty_for_new_session() -> None:
    from app.chat.actions import _recent_history

    assert _recent_history("does-not-exist") == []


def test_think_fallback_resolved_question_is_message() -> None:
    from app.chat.actions import _think

    p = _think("prioritize this")  # LLM disabled -> fallback
    assert p.resolved_question == "prioritize this"


def test_think_resolves_with_history(monkeypatch) -> None:
    import app.chat.actions as actions

    captured = {}

    def fake(prompt, *, system, **k):
        captured["prompt"] = prompt
        return {
            "question_type": "prioritize",
            "approach": "rank them",
            "retrieval_hint": "",
            "resolved_question": "prioritize the learning areas: MLOps, Kubernetes",
        }

    monkeypatch.setattr(actions, "generate_json", fake)
    hist = [("user", "what can I learn?"), ("assistant", "MLOps, Kubernetes, IaC")]
    p = actions._think("prioritize this", hist)
    assert "MLOps" in p.resolved_question
    assert "what can I learn" in captured["prompt"] or "MLOps" in captured["prompt"]


def test_resolved_question_drives_retrieval(monkeypatch) -> None:
    import app.chat.actions as actions

    seen: dict[str, str] = {}
    monkeypatch.setattr(
        actions,
        "_think",
        lambda m, h=None: actions.ThinkingPlan(
            "prioritize", "rank", "", resolved_question="prioritize MLOps and Kubernetes"
        ),
    )

    def fake_retrieve(q, **k):
        seen.setdefault("q", q)
        return []

    monkeypatch.setattr(actions, "retrieve_chunks", fake_retrieve)
    actions._build_answer_context("understanding", "prioritize this")
    assert seen["q"] == "prioritize MLOps and Kubernetes" or "MLOps" in seen.get("q", "")


def test_answer_prompt_includes_recent_history() -> None:
    from app.chat.actions import _answer_prompt

    prompt = _answer_prompt(
        message="x",
        context="ctx",
        suggestions=[],
        plan=None,
        history=[("user", "what can I learn?"), ("assistant", "MLOps")],
    )
    assert "Recent conversation" in prompt and "MLOps" in prompt
