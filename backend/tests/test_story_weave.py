from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import connect, ensure_schema
from app.lifecycle import weave_all_story_buckets, weave_story_bucket
from app.main import app
from app.modules import sync_module_registry
from app.user_model import ensure_story_buckets, list_story_buckets, mark_story_bucket_user_edited


def _ready(tmp_path) -> dict:
    ensure_schema()
    sync_module_registry()
    with connect() as conn:
        ensure_story_buckets(tmp_path, conn)
        bucket = next(bucket for bucket in list_story_buckets(conn) if bucket["stable_key"] == "interests_and_works")
        with conn.cursor() as cur:
            cur.execute("DELETE FROM bucket_updates WHERE story_bucket_id = %s", (bucket["id"],))
            cur.execute("DELETE FROM story_weave_runs WHERE story_bucket_id = %s", (bucket["id"],))
            cur.execute(
                """
                UPDATE story_buckets
                SET last_user_edit_at = NULL
                WHERE id = %s
                """,
                (bucket["id"],),
            )
        conn.commit()
    return bucket


def _insert_bucket_update(bucket_id, text: str, *, future: bool = False) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            if future:
                cur.execute(
                    """
                    INSERT INTO bucket_updates (story_bucket_id, update_text, created_at)
                    VALUES (%s, %s, now() + interval '1 day')
                    """,
                    (bucket_id, text),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO bucket_updates (story_bucket_id, update_text)
                    VALUES (%s, %s)
                    """,
                    (bucket_id, text),
                )
        conn.commit()


def _bucket_content(bucket_id) -> str:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM story_buckets WHERE id = %s", (bucket_id,))
            return cur.fetchone()["content"]


def test_pending_updates_merge_into_story_bucket_prose(tmp_path) -> None:
    bucket = _ready(tmp_path)
    _insert_bucket_update(bucket["id"], "Orbit: The person is building modular life-data software.")
    _insert_bucket_update(bucket["id"], "Career: The person is exploring data engineering work.")

    result = weave_story_bucket(bucket["id"])

    assert result.status == "complete"
    assert result.merged_count == 2
    text = _bucket_content(bucket["id"])
    assert "## Story Weave" in text
    assert "Orbit: The person is building modular life-data software." in text

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, weave_run_id FROM bucket_updates WHERE story_bucket_id = %s",
                (bucket["id"],),
            )
            rows = cur.fetchall()

    assert {row["status"] for row in rows} == {"merged"}
    assert all(row["weave_run_id"] == result.run_id for row in rows)


def test_updates_after_snapshot_cutoff_wait_for_next_run(tmp_path) -> None:
    bucket = _ready(tmp_path)
    _insert_bucket_update(bucket["id"], "Orbit: This update is ready.")
    _insert_bucket_update(bucket["id"], "Orbit: This future update waits.", future=True)

    result = weave_story_bucket(bucket["id"])

    assert result.merged_count == 1
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT update_text, status
                FROM bucket_updates
                WHERE story_bucket_id = %s
                ORDER BY created_at
                """,
                (bucket["id"],),
            )
            rows = cur.fetchall()

    assert rows[0]["status"] == "merged"
    assert rows[1]["status"] == "pending"


def test_evolving_thinking_is_preserved_without_explicit_correction(tmp_path) -> None:
    bucket = _ready(tmp_path)
    _insert_bucket_update(bucket["id"], "Job offer: The person is leaning yes.")
    _insert_bucket_update(bucket["id"], "Job offer: The person is leaning no after more thought.")

    result = weave_story_bucket(bucket["id"])

    assert result.merged_count == 2
    assert result.superseded_count == 0
    text = _bucket_content(bucket["id"])
    assert "leaning yes" in text
    assert "leaning no" in text


def test_explicit_correction_supersedes_older_same_subject_update(tmp_path) -> None:
    bucket = _ready(tmp_path)
    _insert_bucket_update(bucket["id"], "Job offer: The person is taking the offer.")
    _insert_bucket_update(bucket["id"], "Job offer: Actually, the person decided not to take the offer.")

    result = weave_story_bucket(bucket["id"])

    assert result.merged_count == 1
    assert result.superseded_count == 1
    text = _bucket_content(bucket["id"])
    assert "decided not to take the offer" in text
    assert "taking the offer." not in text

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM bucket_updates WHERE story_bucket_id = %s ORDER BY created_at",
                (bucket["id"],),
            )
            statuses = [row["status"] for row in cur.fetchall()]
    assert statuses == ["superseded", "merged"]


def test_user_locked_bucket_is_not_rewritten_by_default(tmp_path) -> None:
    bucket = _ready(tmp_path)
    _insert_bucket_update(bucket["id"], "Orbit: This should wait while user lock is active.")
    mark_story_bucket_user_edited(bucket["id"])
    before = _bucket_content(bucket["id"])

    result = weave_story_bucket(bucket["id"])

    assert result.status == "skipped_locked"
    assert result.merged_count == 0
    after = _bucket_content(bucket["id"])
    assert after == before

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM bucket_updates WHERE story_bucket_id = %s", (bucket["id"],))
            assert cur.fetchone()["status"] == "pending"


def test_force_weave_overrides_user_edit_lock(tmp_path) -> None:
    bucket = _ready(tmp_path)
    _insert_bucket_update(bucket["id"], "Orbit: Forced weave can integrate this.")
    mark_story_bucket_user_edited(bucket["id"])

    result = weave_story_bucket(bucket["id"], force=True)

    assert result.status == "complete"
    assert result.merged_count == 1
    text = _bucket_content(bucket["id"])
    assert "Forced weave can integrate this" in text


def test_weave_all_processes_buckets_with_pending_updates(tmp_path) -> None:
    _ready(tmp_path)
    with connect() as conn:
        buckets = list_story_buckets(conn)
    for bucket in buckets[:2]:
        _insert_bucket_update(bucket["id"], f"{bucket['display_name']}: Update {uuid4().hex}.")

    results = weave_all_story_buckets(force=True)

    assert len(results) >= 2
    assert all(result.status == "complete" for result in results)


def test_story_weave_api_runs_bucket_weave(tmp_path) -> None:
    bucket = _ready(tmp_path)
    _insert_bucket_update(bucket["id"], "Orbit API: Manual weave endpoint works.")
    client = TestClient(app)

    response = client.post(f"/story-weave/buckets/{bucket['id']}")

    assert response.status_code == 200
    assert response.json()["status"] == "complete"
    assert response.json()["merged_count"] == 1
