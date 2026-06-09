"""Routine module service.

Routine items are recurring Life Items. Daily completion ticks are exact
history in routine_completions and do not create their own Life Items.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from app.db import transaction
from app.lifecycle import (
    LifeItemError,
    create_life_item,
    process_lifecycle_for_item,
    set_lifecycle_status,
)


class RoutineCreate(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    position: int = 0
    request_id: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)


class RoutineUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    position: int | None = None


class RoutineCompletionRequest(BaseModel):
    date: date


class RoutineItem(BaseModel):
    id: UUID
    title: str
    description: str
    lifecycle_status: str
    connection_status: str
    chunk_status: str
    bucket_update_status: str
    position: int
    today_completed: bool
    streak_count: int
    created_at: datetime
    updated_at: datetime


class RoutineState(BaseModel):
    date: date
    total_count: int
    completed_count: int
    items: list[RoutineItem]


def list_routine_state(*, target_date: date | None = None, limit: int = 100) -> RoutineState:
    day = target_date or date.today()
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    li.*,
                    ri.position,
                    EXISTS (
                        SELECT 1
                        FROM routine_completions rc
                        WHERE rc.routine_life_item_id = li.id
                            AND rc.completed_on = %(target_date)s
                    ) AS today_completed
                FROM life_items li
                JOIN routine_items ri ON ri.life_item_id = li.id
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE m.id = 'routine'
                    AND li.lifecycle_status = 'active'
                ORDER BY ri.position ASC, li.created_at ASC
                LIMIT %(limit)s
                """,
                {"target_date": day, "limit": limit},
            )
            rows = cur.fetchall()
            completion_dates = _completion_dates_by_item(cur, [row["id"] for row in rows], day)

    items = [_row_to_routine_item(row, completion_dates.get(row["id"], set()), day) for row in rows]
    return RoutineState(
        date=day,
        total_count=len(items),
        completed_count=sum(1 for item in items if item.today_completed),
        items=items,
    )


def create_routine_item(
    payload: RoutineCreate,
    *,
    review: bool = True,
    review_root: Path | None = None,
) -> RoutineItem:
    request_id = payload.request_id or f"routine-{uuid4().hex}"
    item_payload = _routine_payload(position=payload.position)
    result = create_life_item(
        module_id="routine",
        item_type="routine_item",
        title=payload.title,
        description=payload.description,
        payload=item_payload,
        source={
            "kind": "manual_routine",
            **payload.source,
        },
        request_id=request_id,
        side_table_data={"position": payload.position},
    )

    if review and result.created:
        process_lifecycle_for_item(result.item["id"], root=review_root)

    return get_routine_item(result.item["id"])


def get_routine_item(routine_id: UUID | str, *, target_date: date | None = None) -> RoutineItem:
    day = target_date or date.today()
    with transaction() as conn:
        with conn.cursor() as cur:
            row = _get_routine_row(cur, routine_id, day)
            completion_dates = _completion_dates_by_item(cur, [row["id"]], day)
    return _row_to_routine_item(row, completion_dates.get(row["id"], set()), day)


def update_routine_item(
    routine_id: UUID | str,
    payload: RoutineUpdate,
    *,
    review: bool = True,
) -> RoutineItem:
    existing = get_routine_item(routine_id)
    changed_fields = payload.model_fields_set
    next_title = payload.title if "title" in changed_fields and payload.title is not None else existing.title
    next_description = (
        payload.description
        if "description" in changed_fields and payload.description is not None
        else existing.description
    )
    next_position = payload.position if "position" in changed_fields and payload.position is not None else existing.position
    item_payload = _routine_payload(position=next_position)

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE life_items
                SET title = %s,
                    description = %s,
                    payload = %s,
                    connection_status = CASE WHEN %s THEN 'pending' ELSE connection_status END,
                    bucket_update_status = CASE
                        WHEN %s AND bucket_update_status <> 'not_needed' THEN 'pending'
                        ELSE bucket_update_status
                    END,
                    chunk_status = CASE
                        WHEN %s AND chunk_status <> 'not_needed' THEN 'pending'
                        ELSE chunk_status
                    END,
                    updated_at = now()
                WHERE id = %s
                """,
                (
                    next_title,
                    next_description,
                    Jsonb(item_payload),
                    review,
                    review,
                    review,
                    routine_id,
                ),
            )
            cur.execute(
                """
                UPDATE routine_items
                SET position = %s,
                    updated_at = now()
                WHERE life_item_id = %s
                """,
                (next_position, routine_id),
            )

    if review:
        process_lifecycle_for_item(routine_id)

    return get_routine_item(routine_id)


def complete_routine_item(routine_id: UUID | str, target_date: date) -> RoutineItem:
    _ensure_active_routine_item(routine_id, target_date=target_date)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO routine_completions (routine_life_item_id, completed_on)
                VALUES (%s, %s)
                ON CONFLICT (routine_life_item_id, completed_on) DO NOTHING
                """,
                (routine_id, target_date),
            )
    return get_routine_item(routine_id, target_date=target_date)


def uncomplete_routine_item(routine_id: UUID | str, target_date: date) -> RoutineItem:
    _ensure_active_routine_item(routine_id, target_date=target_date)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM routine_completions
                WHERE routine_life_item_id = %s
                    AND completed_on = %s
                """,
                (routine_id, target_date),
            )
    return get_routine_item(routine_id, target_date=target_date)


def archive_routine_item(routine_id: UUID | str, *, target_date: date | None = None) -> RoutineItem:
    get_routine_item(routine_id, target_date=target_date)
    set_lifecycle_status(routine_id, "archived")
    return get_routine_item(routine_id, target_date=target_date)


def _get_routine_row(cur: Any, routine_id: UUID | str, target_date: date) -> dict[str, Any]:
    cur.execute(
        """
        SELECT
            li.*,
            ri.position,
            EXISTS (
                SELECT 1
                FROM routine_completions rc
                WHERE rc.routine_life_item_id = li.id
                    AND rc.completed_on = %s
            ) AS today_completed
        FROM life_items li
        JOIN routine_items ri ON ri.life_item_id = li.id
        JOIN module_instances mi ON mi.id = li.module_instance_id
        JOIN modules m ON m.id = mi.module_id
        WHERE m.id = 'routine'
            AND li.id = %s
        """,
        (target_date, routine_id),
    )
    row = cur.fetchone()
    if row is None:
        raise LifeItemError(f"Unknown routine item: {routine_id}")
    return row


def _ensure_active_routine_item(routine_id: UUID | str, *, target_date: date) -> None:
    item = get_routine_item(routine_id, target_date=target_date)
    if item.lifecycle_status != "active":
        raise LifeItemError(f"Routine item is not active: {routine_id}")


def _completion_dates_by_item(cur: Any, item_ids: list[UUID], target_date: date) -> dict[UUID, set[date]]:
    if not item_ids:
        return {}
    cur.execute(
        """
        SELECT routine_life_item_id, completed_on
        FROM routine_completions
        WHERE routine_life_item_id = ANY(%s)
            AND completed_on <= %s
        ORDER BY completed_on DESC
        """,
        (item_ids, target_date),
    )
    by_item: dict[UUID, set[date]] = {item_id: set() for item_id in item_ids}
    for row in cur.fetchall():
        by_item.setdefault(row["routine_life_item_id"], set()).add(row["completed_on"])
    return by_item


def _row_to_routine_item(row: dict[str, Any], completion_dates: set[date], target_date: date) -> RoutineItem:
    return RoutineItem(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        lifecycle_status=row["lifecycle_status"],
        connection_status=row["connection_status"],
        chunk_status=row["chunk_status"],
        bucket_update_status=row["bucket_update_status"],
        position=row["position"],
        today_completed=bool(row["today_completed"]),
        streak_count=_streak_count(completion_dates, target_date),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _streak_count(completion_dates: set[date], target_date: date) -> int:
    if target_date in completion_dates:
        cursor = target_date
    elif target_date - timedelta(days=1) in completion_dates:
        cursor = target_date - timedelta(days=1)
    else:
        return 0

    count = 0
    while cursor in completion_dates:
        count += 1
        cursor -= timedelta(days=1)
    return count


def _routine_payload(*, position: int) -> dict[str, Any]:
    return {"position": position}
