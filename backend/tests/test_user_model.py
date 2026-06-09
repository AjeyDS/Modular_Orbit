from __future__ import annotations

from uuid import uuid4

import pytest

from app.db import connect, ensure_schema
from app.lifecycle import create_life_item, delete_life_item
from app.modules import sync_module_registry
from app.user_model import (
    create_story_bucket,
    ensure_goals_seed,
    ensure_story_buckets,
    get_story_bucket_item,
    list_story_bucket_items,
    list_story_buckets,
    list_goals,
    promote_goal,
    rename_story_bucket,
    update_story_bucket_item,
    StoryBucketUpdate,
)
from app.user_model.paths import user_model_root


@pytest.fixture(autouse=True)
def registry_ready() -> None:
    ensure_schema()
    sync_module_registry()


def test_seed_story_buckets_create_stable_rows_with_content(tmp_path) -> None:
    with connect() as conn:
        ensure_story_buckets(tmp_path, conn)
        buckets = list_story_buckets(conn)

        stable_keys = [bucket["stable_key"] for bucket in buckets]
        assert stable_keys[:3] == ["who_am_i", "goals", "interests_and_works"]

        goals_bucket = next(bucket for bucket in buckets if bucket["stable_key"] == "goals")
        assert goals_bucket["display_name"] == "Goals"
        assert goals_bucket["content"].startswith("# Goals")
        conn.rollback()


def test_rename_story_bucket_does_not_break_connection_target(tmp_path) -> None:
    life_item = create_life_item(
        module_id="logs",
        item_type="log",
        title="Connection survives bucket rename",
        request_id=f"bucket-rename-{uuid4().hex}",
    )

    with connect() as conn:
        ensure_story_buckets(tmp_path, conn)
        bucket = next(bucket for bucket in list_story_buckets(conn) if bucket["stable_key"] == "interests_and_works")

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO item_connections (
                    source_life_item_id, target_type, target_id, target_label, strength
                )
                VALUES (%s, 'story_bucket', %s, %s, 0.8)
                """,
                (life_item.item["id"], str(bucket["id"]), bucket["display_name"]),
            )

        renamed = rename_story_bucket(
            bucket["id"],
            display_name="Projects And Works",
            file_name="projects_and_works.md",
            conn=conn,
        )

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT target_id
                FROM item_connections
                WHERE source_life_item_id = %s AND target_type = 'story_bucket'
                """,
                (life_item.item["id"],),
            )
            connection = cur.fetchone()

        assert renamed["id"] == bucket["id"]
        assert renamed["display_name"] == "Projects And Works"
        assert connection["target_id"] == str(bucket["id"])
        conn.rollback()

    delete_life_item(life_item.item["id"])


def test_create_reviewed_story_bucket_has_stable_identity(tmp_path) -> None:
    with connect() as conn:
        bucket = create_story_bucket(
            stable_key="career",
            display_name="Career",
            file_name="career.md",
            description="Reviewed split for career-related story.",
            root=tmp_path,
            conn=conn,
        )

        assert bucket["stable_key"] == "career"
        assert bucket["display_name"] == "Career"
        assert bucket["content"].startswith("# Career")
        conn.rollback()


def test_story_bucket_items_include_content_and_user_edits_mark_lock(tmp_path) -> None:
    with connect() as conn:
        ensure_story_buckets(tmp_path, conn)
        bucket = next(bucket for bucket in list_story_bucket_items(conn) if bucket.stable_key == "career")

        updated = update_story_bucket_item(
            bucket.id,
            StoryBucketUpdate(
                display_name="Career Story",
                description="Edited career context.",
                content="# Career Story\n\nI am shaping a data career.",
            ),
            conn=conn,
        )
        reread = get_story_bucket_item(bucket.id, conn)

        assert updated.display_name == "Career Story"
        assert updated.description == "Edited career context."
        assert updated.last_user_edit_at is not None
        assert reread.content == "# Career Story\n\nI am shaping a data career.\n"
        conn.rollback()


def test_user_model_api_lists_and_updates_story_bucket() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with connect() as conn:
        ensure_story_buckets(conn=conn)
        bucket = next(bucket for bucket in list_story_buckets(conn) if bucket["stable_key"] == "health")
        conn.commit()

    client = TestClient(app)
    list_response = client.get("/user-model/buckets")
    assert list_response.status_code == 200
    assert any(item["stable_key"] == "health" for item in list_response.json())

    update_response = client.patch(
        f"/user-model/buckets/{bucket['id']}",
        json={
            "display_name": "Health",
            "description": "Current energy and wellbeing notes.",
            "content": "# Health\n\nSleep and exercise are currently important.",
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["content"].endswith("currently important.\n")
    assert updated["last_user_edit_at"] is not None


def test_list_goals_lifts_existing_markdown_into_db(tmp_path) -> None:
    # Write a legacy goals.md first, THEN seed — ensures the one-time lift fires.
    (user_model_root(tmp_path)).mkdir(parents=True, exist_ok=True)
    (user_model_root(tmp_path) / "goals.md").write_text(
        """
# Goals

## Tentative

<!-- goal: learn-rust -->
### Learn Rust for systems work

Explore whether Rust fits future infrastructure work.

## Active

<!-- goal: build-orbit -->
### Build Orbit

Make Orbit useful as a personal advisor.
""".strip()
        + "\n",
        encoding="utf-8",
    )

    ensure_goals_seed(tmp_path)
    goals = list_goals()

    by_id = {goal.goal_id: goal for goal in goals}
    assert by_id["build-orbit"].status == "active"
    assert by_id["build-orbit"].title == "Build Orbit"
    assert by_id["learn-rust"].status == "tentative"


def test_promote_goal_preserves_goal_id(tmp_path) -> None:
    (user_model_root(tmp_path)).mkdir(parents=True, exist_ok=True)
    (user_model_root(tmp_path) / "goals.md").write_text(
        """
# Goals

## Active

<!-- goal: build-orbit -->
### Build Orbit

Make Orbit useful.

## Tentative

<!-- goal: learn-rust -->
### Learn Rust

Explore Rust later.
""".strip()
        + "\n",
        encoding="utf-8",
    )

    ensure_goals_seed(tmp_path)
    promoted = promote_goal("learn-rust")
    goals = {goal.goal_id: goal for goal in list_goals()}

    assert promoted.goal_id == "learn-rust"
    assert promoted.status == "active"
    assert goals["learn-rust"].status == "active"
    assert goals["learn-rust"].title == "Learn Rust"
