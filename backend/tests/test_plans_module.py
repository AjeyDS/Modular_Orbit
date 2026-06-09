from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.chat import ItemChatRequest, chat_with_item
from app.db import connect, ensure_schema
from app.main import app
from app.modules import sync_module_registry
from app.modules.plans import (
    PlanCreate,
    PlanStepCreate,
    add_plan_step,
    archive_plan,
    complete_plan,
    complete_plan_step,
    create_plan,
    list_plans,
    remove_plan,
)
from app.modules.plan_parser import parse_plan_text
from app.user_model import ensure_goals_seed, ensure_story_buckets


def _request_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _ready(tmp_path) -> None:
    ensure_schema()
    sync_module_registry()
    with connect() as conn:
        ensure_story_buckets(tmp_path, conn)
        conn.commit()
    ensure_goals_seed(tmp_path)


def test_create_plan_writes_side_tables_summary_chunk_and_review(tmp_path) -> None:
    _ready(tmp_path)
    plan = create_plan(
        PlanCreate(
            title="Build Orbit plans",
            description="Plan Orbit work across goals and decisions.",
            steps=[
                PlanStepCreate(title="Design plan schema"),
                PlanStepCreate(title="Build plan API"),
            ],
            request_id=_request_id("plan-create"),
        ),
        review_root=tmp_path,
    )

    assert plan.title == "Build Orbit plans"
    assert plan.total_steps == 2
    assert plan.completed_steps == 0
    assert plan.progress_percent == 0
    assert plan.connection_status == "complete"
    assert plan.chunk_status == "complete"

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id AS module_id, pi.total_steps
                FROM life_items li
                JOIN plan_items pi ON pi.life_item_id = li.id
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE li.id = %s
                """,
                (plan.id,),
            )
            row = cur.fetchone()
            assert row["module_id"] == "plans"
            assert row["total_steps"] == 2

            cur.execute(
                "SELECT content FROM knowledge_chunks WHERE life_item_id = %s AND source_type = 'plan_summary'",
                (plan.id,),
            )
            assert "Design plan schema" in cur.fetchone()["content"]

            cur.execute("SELECT COUNT(*) AS count FROM plan_step_items WHERE plan_life_item_id = %s", (plan.id,))
            assert cur.fetchone()["count"] == 2

    remove_plan(plan.id)


def test_complete_step_recalculates_progress_and_summary_chunk(tmp_path) -> None:
    _ready(tmp_path)
    plan = create_plan(
        PlanCreate(
            title="Progress plan",
            steps=[
                PlanStepCreate(title="First step"),
                PlanStepCreate(title="Second step"),
            ],
            request_id=_request_id("plan-progress"),
        ),
        review=False,
    )

    updated = complete_plan_step(plan.id, plan.steps[0].id)

    assert updated.completed_steps == 1
    assert updated.total_steps == 2
    assert updated.progress_percent == 50
    assert updated.steps[0].status == "completed"
    assert updated.steps[0].completed_at is not None

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM life_items WHERE id = %s", (plan.id,))
            payload = cur.fetchone()["payload"]
            assert payload["progress_percent"] == 50
            assert payload["step_count"] == 2

            cur.execute(
                "SELECT metadata FROM knowledge_chunks WHERE life_item_id = %s AND source_type = 'plan_summary'",
                (plan.id,),
            )
            assert cur.fetchone()["metadata"]["progress_percent"] == 50

    remove_plan(plan.id)


def test_add_step_and_complete_plan(tmp_path) -> None:
    _ready(tmp_path)
    plan = create_plan(
        PlanCreate(title="Complete plan", request_id=_request_id("plan-complete")),
        review=False,
    )

    with_step = add_plan_step(plan.id, PlanStepCreate(title="Only step"))
    assert with_step.total_steps == 1
    assert with_step.progress_percent == 0

    completed = complete_plan(plan.id)
    assert completed.lifecycle_status == "completed"
    assert completed.completed_at is not None
    assert completed.completed_steps == 1
    assert completed.progress_percent == 100
    assert completed.steps[0].status == "completed"

    remove_plan(plan.id)


def test_list_archive_and_delete_plan(tmp_path) -> None:
    _ready(tmp_path)
    active = create_plan(
        PlanCreate(title="Active plan", request_id=_request_id("active-plan")),
        review=False,
    )
    archived = create_plan(
        PlanCreate(title="Archived plan", request_id=_request_id("archived-plan")),
        review=False,
    )
    archive_plan(archived.id)

    active_ids = {plan.id for plan in list_plans(status="active")}
    archived_ids = {plan.id for plan in list_plans(status="archived")}

    assert active.id in active_ids
    assert archived.id not in active_ids
    assert archived.id in archived_ids

    remove_plan(active.id)
    remove_plan(archived.id)


def test_delete_plan_cascades_side_tables_chunks_and_connections(tmp_path) -> None:
    _ready(tmp_path)
    plan = create_plan(
        PlanCreate(
            title="Delete plan",
            description="Orbit goals and decisions.",
            steps=[PlanStepCreate(title="Delete cascade step")],
            request_id=_request_id("delete-plan"),
        ),
        review_root=tmp_path,
    )

    remove_plan(plan.id)

    with connect() as conn:
        with conn.cursor() as cur:
            for table, key in (
                ("life_items", "id"),
                ("plan_items", "life_item_id"),
                ("plan_steps", "life_item_id"),
                ("knowledge_chunks", "life_item_id"),
                ("item_connections", "source_life_item_id"),
            ):
                cur.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE {key} = %s", (plan.id,))
                assert cur.fetchone()["count"] == 0


def test_plan_item_chat_includes_summary_chunk(tmp_path) -> None:
    _ready(tmp_path)
    plan = create_plan(
        PlanCreate(
            title="Chat with plan",
            description="Discuss this plan in context.",
            steps=[PlanStepCreate(title="A plan step")],
            request_id=_request_id("plan-chat"),
        ),
        review_root=tmp_path,
    )

    response = chat_with_item(
        plan.id,
        ItemChatRequest(message="What is the current plan progress?"),
        root=tmp_path,
    )

    assert response.context.module_id == "plans"
    assert response.context.derived_chunks
    assert "Derived chunks available" in response.answer

    remove_plan(plan.id)


def test_plans_api_create_step_complete_archive_delete(tmp_path) -> None:
    _ready(tmp_path)
    client = TestClient(app)

    create_response = client.post(
        "/modules/plans",
        json={
            "title": "API Plan",
            "description": "Exercise plan API.",
            "steps": [{"title": "Initial step"}],
            "request_id": _request_id("api-plan"),
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["title"] == "API Plan"
    assert created["total_steps"] == 1

    add_step_response = client.post(
        f"/modules/plans/{created['id']}/steps",
        json={"title": "Second step"},
    )
    assert add_step_response.status_code == 201
    assert add_step_response.json()["total_steps"] == 2

    step_id = add_step_response.json()["steps"][0]["id"]
    complete_step_response = client.post(f"/modules/plans/{created['id']}/steps/{step_id}/complete")
    assert complete_step_response.status_code == 200
    assert complete_step_response.json()["progress_percent"] == 50

    complete_plan_response = client.post(f"/modules/plans/{created['id']}/complete")
    assert complete_plan_response.status_code == 200
    assert complete_plan_response.json()["lifecycle_status"] == "completed"

    archive_response = client.post(f"/modules/plans/{created['id']}/archive")
    assert archive_response.status_code == 200
    assert archive_response.json()["lifecycle_status"] == "archived"

    delete_response = client.delete(f"/modules/plans/{created['id']}")
    assert delete_response.status_code == 204


def test_plans_api_parse_text_and_confirm_nested_import(tmp_path) -> None:
    _ready(tmp_path)
    client = TestClient(app)

    parse_response = client.post(
        "/modules/plans/parse",
        json={
            "raw_text": """
            # Launch modular Orbit
            - Finish lifecycle spine
              - Normalize async statuses
              - Add shared chunk writer
            - Ship plan import
            """,
        },
    )
    assert parse_response.status_code == 200
    draft = parse_response.json()
    assert draft["title"]
    assert draft["nodes"]

    create_response = client.post(
        "/modules/plans",
        json={
            "title": draft["title"],
            "category": draft["category"],
            "raw_text": "raw pasted plan text",
            "nodes": draft["nodes"],
            "request_id": _request_id("parsed-plan"),
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["total_steps"] >= 3
    assert created["steps"][0]["children"]

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS count
                FROM life_items
                WHERE parent_life_item_id = %s AND item_type = 'plan_step'
                """,
                (created["id"],),
            )
            assert cur.fetchone()["count"] == created["total_steps"]

    remove_plan(created["id"])


def test_plan_parser_preserves_unindented_bullets_under_headings(monkeypatch) -> None:
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr("app.modules.plan_parser.generate_json", unavailable)

    draft = parse_plan_text(
        """
        AWS Certified Data Engineer Study Plan

        Domain 1: Data Ingestion & Transformation (34%)
        - AWS Glue — ETL jobs, Glue Studio, crawlers, Data Catalog
        - Amazon Kinesis — Kinesis Data Streams, Firehose, Data Analytics

        Domain 2: Data Store Management (26%)
        - Amazon S3 — storage classes, lifecycle policies, partitioning
        - Amazon Redshift — distribution styles, sort keys, Spectrum
        """
    )

    assert draft.title == "AWS Certified Data Engineer Study Plan"
    assert draft.nodes[0].title == "Domain 1: Data Ingestion & Transformation (34%)"
    assert [child.title for child in draft.nodes[0].children] == ["AWS Glue", "Amazon Kinesis"]
    assert draft.nodes[0].children[0].description == "ETL jobs, Glue Studio, crawlers, Data Catalog"
    assert draft.nodes[1].children[1].title == "Amazon Redshift"


def test_plan_parser_prefers_heuristic_when_llm_drops_nested_steps(monkeypatch) -> None:
    def sparse_parse(*_args, **_kwargs):
        return {
            "title": "Launch Plan",
            "category": "work",
            "nodes": [
                {"title": "Phase 1: Foundation", "description": None, "metadata": {}, "children": []},
                {"title": "Phase 2: Delivery", "description": None, "metadata": {}, "children": []},
            ],
        }

    monkeypatch.setattr("app.modules.plan_parser.generate_json", sparse_parse)

    draft = parse_plan_text(
        """
        Launch Plan

        Phase 1: Foundation
        - Add retry logic
        - Add file-size guardrails

        Phase 2: Delivery
        - Ship internal beta
        - Collect user feedback
        """
    )

    assert draft.nodes[0].title == "Phase 1: Foundation"
    assert [child.title for child in draft.nodes[0].children] == ["Add retry logic", "Add file-size guardrails"]
    assert [child.title for child in draft.nodes[1].children] == ["Ship internal beta", "Collect user feedback"]
