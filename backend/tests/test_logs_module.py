from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import connect, ensure_schema
from app.lifecycle import LifeItemError, delete_life_item, set_lifecycle_status
from app.main import app
from app.modules import sync_module_registry
from app.modules.logs import LogCreate, archive_log, create_log, list_logs, remove_log
from app.user_model import ensure_goals_seed, ensure_story_buckets


@pytest.fixture(autouse=True)
def logs_ready(tmp_path) -> None:
    ensure_schema()
    sync_module_registry()
    with connect() as conn:
        ensure_story_buckets(tmp_path, conn)
        conn.commit()
    ensure_goals_seed(tmp_path)


def _request_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def test_create_log_writes_life_item_and_runs_review(tmp_path) -> None:
    log = create_log(
        LogCreate(
            text="Career work identity and professional context changed today.",
            request_id=_request_id("log-create"),
        ),
        review_root=tmp_path,
    )

    assert log.title == "Career work identity and professional context changed today."
    assert log.lifecycle_status == "active"
    assert log.connection_status == "complete"
    assert log.chunk_status == "complete"

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id AS module_id
                FROM life_items li
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE li.id = %s
                """,
                (log.id,),
            )
            assert cur.fetchone()["module_id"] == "logs"

            cur.execute("SELECT COUNT(*) AS count FROM item_connections WHERE source_life_item_id = %s", (log.id,))
            assert cur.fetchone()["count"] >= 1

    remove_log(log.id)


def test_list_logs_uses_module_view_and_status_filter(tmp_path) -> None:
    active = create_log(
        LogCreate(text="Active log about Orbit goals.", request_id=_request_id("active-log")),
        review=False,
        review_root=tmp_path,
    )
    archived = create_log(
        LogCreate(text="Archived log about Orbit goals.", request_id=_request_id("archived-log")),
        review=False,
        review_root=tmp_path,
    )
    archive_log(archived.id)

    active_ids = {log.id for log in list_logs(status="active", limit=20)}
    archived_ids = {log.id for log in list_logs(status="archived", limit=20)}

    assert active.id in active_ids
    assert archived.id not in active_ids
    assert archived.id in archived_ids

    remove_log(active.id)
    remove_log(archived.id)


def test_logs_can_archive_and_delete_but_not_complete(tmp_path) -> None:
    log = create_log(
        LogCreate(text="Logs are observations, not completable work.", request_id=_request_id("log-status")),
        review=False,
        review_root=tmp_path,
    )

    archived = archive_log(log.id)
    assert archived.lifecycle_status == "archived"

    with pytest.raises(LifeItemError):
        set_lifecycle_status(log.id, "completed")

    remove_log(log.id)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM life_items WHERE id = %s", (log.id,))
            assert cur.fetchone()["count"] == 0


def test_logs_api_create_list_without_archive_delete_routes() -> None:
    client = TestClient(app)
    request_id = _request_id("api-log")

    create_response = client.post(
        "/modules/logs",
        json={
            "text": "Build Orbit API logs for modular capture.",
            "request_id": request_id,
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["text"] == "Build Orbit API logs for modular capture."
    assert created["lifecycle_status"] == "active"

    list_response = client.get("/modules/logs", params={"status": "active"})
    assert list_response.status_code == 200
    assert any(row["id"] == created["id"] for row in list_response.json())

    archive_response = client.post(f"/modules/logs/{created['id']}/archive")
    assert archive_response.status_code == 404

    delete_response = client.delete(f"/modules/logs/{created['id']}")
    assert delete_response.status_code == 404

    archived_list_response = client.get("/modules/logs", params={"status": "archived"})
    assert archived_list_response.status_code == 422

    remove_log(created["id"])
