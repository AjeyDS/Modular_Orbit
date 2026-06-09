from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from app.db import connect, ensure_schema
from app.main import app
from app.modules import sync_module_registry
from app.modules.output import (
    GenerateOutputRequest,
    accept_generated_output,
    generate_output,
    get_generated_output,
    list_generated_outputs,
    reject_generated_output,
    retry_generated_output,
)
from app.user_model import ensure_goals_seed, ensure_story_buckets


def _ready(tmp_path) -> None:
    ensure_schema()
    sync_module_registry()
    with connect() as conn:
        ensure_story_buckets(tmp_path, conn)
        conn.commit()
    ensure_goals_seed(tmp_path)


def test_generate_strategy_stays_draft_until_accepted(tmp_path) -> None:
    _ready(tmp_path)

    output = generate_output(
        "strategies",
        GenerateOutputRequest(
            prompt="Balance Orbit implementation with job search",
            context={"time_horizon": "this week"},
        ),
    )

    assert output.module_id == "strategies"
    assert output.status == "draft"
    assert output.created_life_item_id is None
    assert "Strategy for this week" in output.output_text

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS count FROM life_items WHERE source->>'generated_output_id' = %s",
                (str(output.id),),
            )
            assert cur.fetchone()["count"] == 0


def test_retry_creates_new_draft_without_accepting_original(tmp_path) -> None:
    _ready(tmp_path)
    original = generate_output(
        "recommendations",
        GenerateOutputRequest(prompt="Choose what to work on next"),
    )

    retry = retry_generated_output(original.id)

    assert retry.id != original.id
    assert retry.retry_of == original.id
    assert retry.status == "draft"
    assert "Revision: retry" in retry.output_text
    assert original.status == "draft"


def test_accept_generated_strategy_creates_life_item_and_chunk_once(tmp_path) -> None:
    _ready(tmp_path)
    output = generate_output(
        "strategies",
        GenerateOutputRequest(prompt="Spend time across Tasks, Plans, and Documents"),
    )

    first = accept_generated_output(output.id)
    second = accept_generated_output(output.id)

    assert first.life_item_id == second.life_item_id
    assert first.output.status == "accepted"

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id AS module_id, li.title, li.lifecycle_status
                FROM life_items li
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE li.id = %s
                """,
                (first.life_item_id,),
            )
            row = cur.fetchone()
            assert row["module_id"] == "strategies"
            assert row["lifecycle_status"] == "active"
            assert row["title"].startswith("Strategy:")

            cur.execute(
                """
                SELECT COUNT(*) AS count
                FROM knowledge_chunks
                WHERE life_item_id = %s AND source_type = 'accepted_output'
                """,
                (first.life_item_id,),
            )
            assert cur.fetchone()["count"] == 1


def test_reject_generated_output_does_not_create_life_item(tmp_path) -> None:
    _ready(tmp_path)
    output = generate_output(
        "recommendations",
        GenerateOutputRequest(prompt="Recommend a next action"),
    )

    rejected = reject_generated_output(output.id)

    assert rejected.status == "rejected"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS count FROM life_items WHERE source->>'generated_output_id' = %s",
                (str(output.id),),
            )
            assert cur.fetchone()["count"] == 0


def test_list_generated_outputs_by_status(tmp_path) -> None:
    _ready(tmp_path)
    draft = generate_output(
        "recommendations",
        GenerateOutputRequest(prompt="Draft recommendation"),
    )
    accepted = generate_output(
        "recommendations",
        GenerateOutputRequest(prompt="Accepted recommendation"),
    )
    accept_generated_output(accepted.id)

    draft_ids = {item.id for item in list_generated_outputs("recommendations", status="draft")}
    accepted_ids = {item.id for item in list_generated_outputs("recommendations", status="accepted")}

    assert draft.id in draft_ids
    assert accepted.id not in draft_ids
    assert accepted.id in accepted_ids


def test_output_modules_api_generate_retry_accept_reject(tmp_path) -> None:
    _ready(tmp_path)
    client = TestClient(app)

    generate_response = client.post(
        "/modules/strategies/outputs/generate",
        json={
            "prompt": "Allocate time between implementation and review",
            "context": {"time_horizon": "tomorrow"},
        },
    )
    assert generate_response.status_code == 201
    generated = generate_response.json()
    assert generated["status"] == "draft"

    retry_response = client.post(f"/modules/strategies/outputs/{generated['id']}/retry")
    assert retry_response.status_code == 201
    retry = retry_response.json()
    assert retry["retry_of"] == generated["id"]

    accept_response = client.post(f"/modules/strategies/outputs/{retry['id']}/accept")
    assert accept_response.status_code == 200
    body = accept_response.json()
    assert body["output"]["status"] == "accepted"
    assert UUID(body["life_item_id"])

    recommendation_response = client.post(
        "/modules/recommendations/outputs/generate",
        json={"prompt": "Recommend the next Orbit phase"},
    )
    recommendation = recommendation_response.json()
    reject_response = client.post(f"/modules/recommendations/outputs/{recommendation['id']}/reject")
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"


def test_output_module_api_mismatch_does_not_mutate_output(tmp_path) -> None:
    _ready(tmp_path)
    client = TestClient(app)

    output = generate_output(
        "recommendations",
        GenerateOutputRequest(prompt="Recommend a focused next action"),
    )

    retry_response = client.post(f"/modules/strategies/outputs/{output.id}/retry")
    accept_response = client.post(f"/modules/strategies/outputs/{output.id}/accept")
    reject_response = client.post(f"/modules/strategies/outputs/{output.id}/reject")

    assert retry_response.status_code == 404
    assert accept_response.status_code == 404
    assert reject_response.status_code == 404

    unchanged = get_generated_output(output.id)
    assert unchanged.status == "draft"
    assert unchanged.created_life_item_id is None

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS count
                FROM generated_outputs
                WHERE retry_of = %s
                """,
                (output.id,),
            )
            assert cur.fetchone()["count"] == 0

            cur.execute(
                "SELECT COUNT(*) AS count FROM life_items WHERE source->>'generated_output_id' = %s",
                (str(output.id),),
            )
            assert cur.fetchone()["count"] == 0
