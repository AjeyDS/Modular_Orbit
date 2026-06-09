from __future__ import annotations

from uuid import uuid4

import pytest

from app.db import connect, ensure_schema
from app.lifecycle import (
    ConnectionReviewError,
    create_life_item,
    delete_life_item,
    reset_connection_review,
    review_life_item,
    run_pending_connection_reviews,
)
from app.modules import sync_module_registry
from app.user_model import ensure_goals_seed, ensure_story_buckets
from app.user_model.goals import goals_path


@pytest.fixture(autouse=True)
def registry_ready(tmp_path) -> None:
    ensure_schema()
    sync_module_registry()
    with connect() as conn:
        ensure_story_buckets(tmp_path, conn)
        conn.commit()
    ensure_goals_seed(tmp_path)


def _request_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def test_review_life_item_creates_connections_and_statuses(tmp_path) -> None:
    goals_path(tmp_path).write_text(
        "\n".join(
            [
                "# Goals",
                "",
                "## Active",
                "",
                "<!-- goal: professional-context -->",
                "### Professional context",
                "Career work identity and professional goals.",
                "",
                "## Tentative",
                "",
            ]
        ),
        encoding="utf-8",
    )
    ensure_goals_seed(tmp_path)
    item = create_life_item(
        module_id="logs",
        item_type="log",
        title="Career work identity update",
        description="Professional context and career goals.",
        payload={"text": "Career work identity and professional goals."},
        request_id=_request_id("review-log"),
    )

    result = review_life_item(item.item["id"], root=tmp_path)

    assert result.life_item_id == item.item["id"]
    assert result.connections
    assert result.should_create_chunks is True

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT connection_status, chunk_status, bucket_update_status
                FROM life_items
                WHERE id = %s
                """,
                (item.item["id"],),
            )
            status = cur.fetchone()
            assert status["connection_status"] == "complete"
            assert status["chunk_status"] == "pending"

            cur.execute(
                """
                SELECT target_type, target_id, target_label, strength, connection_note
                FROM item_connections
                WHERE source_life_item_id = %s
                ORDER BY strength DESC
                """,
                (item.item["id"],),
            )
            connections = cur.fetchall()
            assert any(row["target_type"] == "story_bucket" for row in connections)
            assert any(row["target_type"] == "active_goal" and row["target_id"] == "professional-context" for row in connections)
            assert all(row["connection_note"] for row in connections)

            cur.execute("SELECT COUNT(*) AS count FROM bucket_updates WHERE life_item_id = %s", (item.item["id"],))
            update_count = cur.fetchone()["count"]
            assert update_count >= 1

    delete_life_item(item.item["id"])


def test_review_is_idempotent_for_connections_and_pending_bucket_updates(tmp_path) -> None:
    item = create_life_item(
        module_id="logs",
        item_type="log",
        title="Build Orbit personal advisor",
        description="Create a modular system for organizing life data and goals.",
        request_id=_request_id("review-idempotent"),
    )

    review_life_item(item.item["id"], root=tmp_path)
    review_life_item(item.item["id"], root=tmp_path)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT target_type, target_id, COUNT(*) AS count
                FROM item_connections
                WHERE source_life_item_id = %s
                GROUP BY target_type, target_id
                HAVING COUNT(*) > 1
                """,
                (item.item["id"],),
            )
            assert cur.fetchall() == []

            cur.execute(
                """
                SELECT story_bucket_id, COUNT(*) AS count
                FROM bucket_updates
                WHERE life_item_id = %s AND status = 'pending'
                GROUP BY story_bucket_id
                HAVING COUNT(*) > 1
                """,
                (item.item["id"],),
            )
            assert cur.fetchall() == []

    delete_life_item(item.item["id"])


def test_candidate_bounds_are_enforced(tmp_path) -> None:
    goals_text = ["# Goals", "", "## Active", ""]
    for index in range(8):
        goals_text.extend(
            [
                f"<!-- goal: orbit-goal-{index} -->",
                f"### Orbit goal {index}",
                "Orbit modular personal advisor goals and decisions.",
                "",
            ]
        )
    goals_text.extend(["## Tentative", ""])
    goals_path(tmp_path).write_text("\n".join(goals_text), encoding="utf-8")
    ensure_goals_seed(tmp_path)

    item = create_life_item(
        module_id="logs",
        item_type="log",
        title="Orbit modular personal advisor goals",
        description="Orbit goals decisions modular advisor.",
        request_id=_request_id("bounds"),
    )

    result = review_life_item(item.item["id"], root=tmp_path)

    goal_connections = [
        connection for connection in result.connections if connection.candidate.target_type == "active_goal"
    ]
    assert len(goal_connections) <= 5

    delete_life_item(item.item["id"])


def test_run_pending_connection_reviews_respects_limit(tmp_path) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE life_items SET connection_status = 'complete' WHERE connection_status = 'pending'")
        conn.commit()

    first = create_life_item(
        module_id="logs",
        item_type="log",
        title="Build Orbit advisor one",
        request_id=_request_id("pending-one"),
    )
    second = create_life_item(
        module_id="logs",
        item_type="log",
        title="Build Orbit advisor two",
        request_id=_request_id("pending-two"),
    )

    results = run_pending_connection_reviews(limit=1, root=tmp_path)

    assert len(results) == 1

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT connection_status, COUNT(*) AS count
                FROM life_items
                WHERE id = ANY(%s)
                GROUP BY connection_status
                """,
                ([first.item["id"], second.item["id"]],),
            )
            statuses = {row["connection_status"]: row["count"] for row in cur.fetchall()}

    assert statuses["complete"] == 1
    assert statuses["pending"] == 1

    delete_life_item(first.item["id"])
    delete_life_item(second.item["id"])


def test_failed_review_marks_status_and_can_reset(tmp_path, monkeypatch) -> None:
    item = create_life_item(
        module_id="logs",
        item_type="log",
        title="Force review failure",
        request_id=_request_id("failed-review"),
    )

    def fail_route(*args, **kwargs):
        raise RuntimeError("forced failure")

    monkeypatch.setattr("app.lifecycle.connection_review._route_candidates", fail_route)

    with pytest.raises(ConnectionReviewError):
        review_life_item(item.item["id"], root=tmp_path)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT connection_status FROM life_items WHERE id = %s", (item.item["id"],))
            assert cur.fetchone()["connection_status"] == "failed"

    reset = reset_connection_review(item.item["id"])
    assert reset["connection_status"] == "pending"

    delete_life_item(item.item["id"])
