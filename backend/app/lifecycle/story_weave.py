"""Story Weave merges Bucket Updates into Story Bucket prose."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from app.db import transaction


USER_EDIT_LOCK_DAYS = 7
CORRECTION_MARKERS = ("actually", "i changed my mind", "i was wrong", "correction:")


class StoryWeaveError(RuntimeError):
    """Raised when Story Weave cannot complete."""


@dataclass(frozen=True)
class StoryWeaveResult:
    run_id: UUID
    story_bucket_id: UUID
    status: str
    snapshot_cutoff: datetime
    merged_count: int
    superseded_count: int
    ignored_count: int
    file_path: str


def weave_story_bucket(
    story_bucket_id: UUID | str,
    *,
    force: bool = False,
) -> StoryWeaveResult:
    """Merge pending Bucket Updates for one Story Bucket using a snapshot cutoff."""
    with transaction() as conn:
        bucket = _get_bucket(conn, story_bucket_id)
        cutoff = _db_now(conn)
        run_id = _create_run(conn, story_bucket_id, cutoff)

    try:
        with transaction() as conn:
            bucket = _get_bucket(conn, story_bucket_id)
            if _is_user_locked(bucket) and not force:
                _finish_run(conn, run_id, status="skipped_locked")
                return StoryWeaveResult(
                    run_id=run_id,
                    story_bucket_id=bucket["id"],
                    status="skipped_locked",
                    snapshot_cutoff=cutoff,
                    merged_count=0,
                    superseded_count=0,
                    ignored_count=0,
                    file_path=bucket["file_path"],
                )

            updates = _pending_updates(conn, story_bucket_id, cutoff)
            merge_updates, superseded_updates = _resolve_updates(updates)
            if merge_updates:
                _append_weave_section(conn, bucket["id"], run_id, cutoff, merge_updates)
            _mark_updates(conn, run_id, merge_updates, status="merged")
            _mark_updates(conn, run_id, superseded_updates, status="superseded")
            _finish_run(
                conn,
                run_id,
                status="complete",
                merged_count=len(merge_updates),
                superseded_count=len(superseded_updates),
            )

            return StoryWeaveResult(
                run_id=run_id,
                story_bucket_id=bucket["id"],
                status="complete",
                snapshot_cutoff=cutoff,
                merged_count=len(merge_updates),
                superseded_count=len(superseded_updates),
                ignored_count=0,
                file_path=bucket["file_path"],
            )
    except Exception as exc:
        with transaction() as conn:
            _mark_failed_updates(conn, story_bucket_id, cutoff)
            _finish_run(conn, run_id, status="failed", error=str(exc))
        raise StoryWeaveError(f"Story Weave failed for bucket {story_bucket_id}") from exc


def weave_all_story_buckets(*, force: bool = False) -> list[StoryWeaveResult]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT story_bucket_id
                FROM bucket_updates
                WHERE status = 'pending'
                ORDER BY story_bucket_id
                """
            )
            bucket_ids = [row["story_bucket_id"] for row in cur.fetchall()]

    return [weave_story_bucket(bucket_id, force=force) for bucket_id in bucket_ids]


def _get_bucket(conn, story_bucket_id: UUID | str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM story_buckets WHERE id = %s", (story_bucket_id,))
        row = cur.fetchone()
        if row is None:
            raise StoryWeaveError(f"Unknown Story Bucket: {story_bucket_id}")
        return dict(row)


def _db_now(conn) -> datetime:
    with conn.cursor() as cur:
        cur.execute("SELECT now() AS now")
        return cur.fetchone()["now"]


def _create_run(conn, story_bucket_id: UUID | str, cutoff: datetime) -> UUID:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO story_weave_runs (story_bucket_id, snapshot_cutoff)
            VALUES (%s, %s)
            RETURNING id
            """,
            (story_bucket_id, cutoff),
        )
        return cur.fetchone()["id"]


def _is_user_locked(bucket: dict[str, Any]) -> bool:
    last_user_edit_at = bucket["last_user_edit_at"]
    if last_user_edit_at is None:
        return False
    return last_user_edit_at >= datetime.now(timezone.utc) - timedelta(days=USER_EDIT_LOCK_DAYS)


def _pending_updates(conn, story_bucket_id: UUID | str, cutoff: datetime) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, update_text, life_item_id, created_at
            FROM bucket_updates
            WHERE story_bucket_id = %s
                AND status = 'pending'
                AND created_at <= %s
            ORDER BY created_at ASC, id ASC
            """,
            (story_bucket_id, cutoff),
        )
        return [dict(row) for row in cur.fetchall()]


def _resolve_updates(updates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    superseded_ids: set[UUID] = set()
    latest_by_subject: dict[str, dict[str, Any]] = {}

    for update in updates:
        subject = _subject(update["update_text"])
        if _is_correction(update["update_text"]) and subject in latest_by_subject:
            superseded_ids.add(latest_by_subject[subject]["id"])
        latest_by_subject[subject] = update

    merge_updates = [update for update in updates if update["id"] not in superseded_ids]
    superseded_updates = [update for update in updates if update["id"] in superseded_ids]
    return merge_updates, superseded_updates


def _append_weave_section(
    conn,
    story_bucket_id: UUID,
    run_id: UUID,
    cutoff: datetime,
    updates: list[dict[str, Any]],
) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT content FROM story_buckets WHERE id = %s", (story_bucket_id,))
        row = cur.fetchone()
        current = (row["content"] if row and row.get("content") else "") or ""

        section_lines = [
            "",
            f"<!-- story-weave-run: {run_id} cutoff: {cutoff.isoformat()} -->",
            f"## Story Weave {cutoff.date().isoformat()}",
            "",
        ]
        for update in updates:
            section_lines.append(f"- {update['update_text']}")
        section_lines.append("")
        next_content = current.rstrip() + "\n" + "\n".join(section_lines)

        cur.execute(
            "UPDATE story_buckets SET content = %s, updated_at = now() WHERE id = %s",
            (next_content, story_bucket_id),
        )


def _mark_updates(conn, run_id: UUID, updates: list[dict[str, Any]], *, status: str) -> None:
    if not updates:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bucket_updates
            SET status = %s,
                weave_run_id = %s,
                updated_at = now()
            WHERE id = ANY(%s)
            """,
            (status, run_id, [update["id"] for update in updates]),
        )


def _mark_failed_updates(conn, story_bucket_id: UUID | str, cutoff: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bucket_updates
            SET status = 'failed', updated_at = now()
            WHERE story_bucket_id = %s
                AND status = 'pending'
                AND created_at <= %s
            """,
            (story_bucket_id, cutoff),
        )


def _finish_run(
    conn,
    run_id: UUID,
    *,
    status: str,
    merged_count: int = 0,
    superseded_count: int = 0,
    ignored_count: int = 0,
    error: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE story_weave_runs
            SET status = %s,
                merged_count = %s,
                superseded_count = %s,
                ignored_count = %s,
                error = %s,
                completed_at = now()
            WHERE id = %s
            """,
            (status, merged_count, superseded_count, ignored_count, error, run_id),
        )


def _is_correction(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in CORRECTION_MARKERS)


def _subject(text: str) -> str:
    return text.split(":", 1)[0].strip().lower() if ":" in text else text.strip().lower()
