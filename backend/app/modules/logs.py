"""Logs module service.

Logs are generalized Life Items. They preserve lightweight observations and
let Connection Review decide whether they matter to the User Model.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.db import transaction
from app.lifecycle import (
    LifeItemError,
    create_life_item,
    delete_life_item,
    process_lifecycle_for_item,
    set_lifecycle_status,
)


class LogCreate(BaseModel):
    text: str = Field(min_length=1)
    title: str | None = None
    occurred_at: datetime | None = None
    request_id: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)


class LogItem(BaseModel):
    id: UUID
    title: str
    text: str
    lifecycle_status: str
    connection_status: str
    chunk_status: str
    bucket_update_status: str
    occurred_at: datetime
    created_at: datetime
    updated_at: datetime


def create_log(payload: LogCreate, *, review: bool = True, review_root: Path | None = None) -> LogItem:
    occurred_at = payload.occurred_at or datetime.now(timezone.utc)
    request_id = payload.request_id or f"log-{uuid4().hex}"
    title = payload.title or _derive_title(payload.text)

    result = create_life_item(
        module_id="logs",
        item_type="log",
        title=title,
        description=payload.text,
        payload={
            "text": payload.text,
            "occurred_at": occurred_at.isoformat(),
        },
        source={
            "kind": "manual_log",
            **payload.source,
        },
        request_id=request_id,
    )

    if review and result.created:
        process_lifecycle_for_item(result.item["id"], root=review_root)

    return _get_log(result.item["id"])


def list_logs(*, status: str | None = "active", limit: int = 50) -> list[LogItem]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT li.*
                FROM life_items li
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE m.id = 'logs'
                    AND (%(status)s::text IS NULL OR li.lifecycle_status = %(status)s)
                ORDER BY li.created_at DESC
                LIMIT %(limit)s
                """,
                {"status": status, "limit": limit},
            )
            return [_row_to_log(row) for row in cur.fetchall()]


def archive_log(log_id: UUID | str) -> LogItem:
    _get_log(log_id)
    item = set_lifecycle_status(log_id, "archived")
    return _row_to_log(item)


def remove_log(log_id: UUID | str) -> None:
    item = _get_log(log_id)
    delete_life_item(item.id)


def _get_log(log_id: UUID | str) -> LogItem:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT li.*
                FROM life_items li
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE li.id = %s AND m.id = 'logs'
                """,
                (log_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise LifeItemError(f"Unknown Log: {log_id}")
            return _row_to_log(row)


def _row_to_log(row: dict[str, Any]) -> LogItem:
    payload = row["payload"] or {}
    occurred_at = payload.get("occurred_at")
    return LogItem(
        id=row["id"],
        title=row["title"],
        text=payload.get("text") or row["description"],
        lifecycle_status=row["lifecycle_status"],
        connection_status=row["connection_status"],
        chunk_status=row["chunk_status"],
        bucket_update_status=row["bucket_update_status"],
        occurred_at=datetime.fromisoformat(occurred_at) if occurred_at else row["created_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _derive_title(text: str) -> str:
    title = " ".join(text.strip().split())
    if len(title) <= 80:
        return title
    return f"{title[:77].rstrip()}..."
