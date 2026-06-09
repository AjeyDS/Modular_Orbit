from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import connect, ensure_schema
from app.lifecycle import LifeItemError
from app.main import app
from app.modules import sync_module_registry
from app.modules.routine import (
    RoutineCreate,
    archive_routine_item,
    complete_routine_item,
    create_routine_item,
    list_routine_state,
    uncomplete_routine_item,
    update_routine_item,
    RoutineUpdate,
)
from app.user_model import ensure_goals_seed, ensure_story_buckets


@pytest.fixture(autouse=True)
def routine_ready(tmp_path) -> None:
    ensure_schema()
    sync_module_registry()
    with connect() as conn:
        ensure_story_buckets(tmp_path, conn)
        conn.commit()
    ensure_goals_seed(tmp_path)


def _request_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def test_create_routine_item_writes_life_item_and_side_table() -> None:
    item = create_routine_item(
        RoutineCreate(
            title="Drink water",
            description="Hydration habit.",
            position=3,
            request_id=_request_id("routine-create"),
        ),
        review=False,
    )

    assert item.title == "Drink water"
    assert item.lifecycle_status == "active"
    assert item.position == 3
    assert item.today_completed is False
    assert item.streak_count == 0

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id AS module_id, ri.position
                FROM life_items li
                JOIN routine_items ri ON ri.life_item_id = li.id
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE li.id = %s
                """,
                (item.id,),
            )
            row = cur.fetchone()

    assert row["module_id"] == "routine"
    assert row["position"] == 3


def test_complete_and_uncomplete_are_idempotent() -> None:
    item = create_routine_item(
        RoutineCreate(title="Stretch", request_id=_request_id("routine-complete")),
        review=False,
    )
    today = date(2026, 6, 9)

    first = complete_routine_item(item.id, today)
    second = complete_routine_item(item.id, today)

    assert first.today_completed is True
    assert second.today_completed is True
    assert second.streak_count == 1

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM routine_completions WHERE routine_life_item_id = %s", (item.id,))
            assert cur.fetchone()["count"] == 1

    unchecked = uncomplete_routine_item(item.id, today)
    unchecked_again = uncomplete_routine_item(item.id, today)

    assert unchecked.today_completed is False
    assert unchecked_again.today_completed is False
    assert unchecked_again.streak_count == 0


def test_streak_counts_today_yesterday_and_missed_days() -> None:
    item = create_routine_item(
        RoutineCreate(title="Read", request_id=_request_id("routine-streak")),
        review=False,
    )
    day = date(2026, 6, 9)

    complete_routine_item(item.id, day - timedelta(days=4))
    complete_routine_item(item.id, day - timedelta(days=2))
    complete_routine_item(item.id, day - timedelta(days=1))

    state = list_routine_state(target_date=day)
    streak_item = next(entry for entry in state.items if entry.id == item.id)
    assert streak_item.today_completed is False
    assert streak_item.streak_count == 2

    complete_routine_item(item.id, day)
    state = list_routine_state(target_date=day)
    streak_item = next(entry for entry in state.items if entry.id == item.id)
    assert streak_item.today_completed is True
    assert streak_item.streak_count == 3

    missed_state = list_routine_state(target_date=day + timedelta(days=2))
    missed_item = next(entry for entry in missed_state.items if entry.id == item.id)
    assert missed_item.streak_count == 0


def test_update_and_archive_routine_item() -> None:
    item = create_routine_item(
        RoutineCreate(title="Old habit", position=1, request_id=_request_id("routine-update")),
        review=False,
    )

    updated = update_routine_item(
        item.id,
        RoutineUpdate(title="New habit", description="Better wording.", position=8),
        review=False,
    )
    assert updated.title == "New habit"
    assert updated.description == "Better wording."
    assert updated.position == 8

    archived = archive_routine_item(item.id)
    assert archived.lifecycle_status == "archived"
    assert item.id not in {entry.id for entry in list_routine_state().items}

    with pytest.raises(LifeItemError):
        complete_routine_item(item.id, date(2026, 6, 9))


def test_routine_api_endpoints() -> None:
    client = TestClient(app)
    day = "2026-06-09"

    create_response = client.post(
        "/modules/routine",
        json={"title": "Meditate", "description": "Five minutes.", "position": 2, "request_id": _request_id("api-routine")},
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["title"] == "Meditate"
    assert created["position"] == 2

    update_response = client.patch(f"/modules/routine/{created['id']}", json={"title": "Meditate quietly", "position": 4})
    assert update_response.status_code == 200
    assert update_response.json()["title"] == "Meditate quietly"
    assert update_response.json()["position"] == 4

    complete_response = client.post(f"/modules/routine/{created['id']}/complete", json={"date": day})
    assert complete_response.status_code == 200
    assert complete_response.json()["today_completed"] is True
    assert complete_response.json()["streak_count"] == 1

    state_response = client.get("/modules/routine", params={"date": day})
    assert state_response.status_code == 200
    state = state_response.json()
    assert state["date"] == day
    assert state["total_count"] == 1
    assert state["completed_count"] == 1

    uncomplete_response = client.delete(f"/modules/routine/{created['id']}/complete", params={"date": day})
    assert uncomplete_response.status_code == 200
    assert uncomplete_response.json()["today_completed"] is False

    archive_response = client.post(f"/modules/routine/{created['id']}/archive")
    assert archive_response.status_code == 200
    assert archive_response.json()["lifecycle_status"] == "archived"

    missing_response = client.post(f"/modules/routine/{uuid4()}/complete", json={"date": day})
    assert missing_response.status_code == 404
