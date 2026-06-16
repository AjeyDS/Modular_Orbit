"""Shared Life Item service used by all modules."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.db import transaction

logger = logging.getLogger(__name__)


class LifeItemError(ValueError):
    """Raised when a Life Item operation violates the module contract."""


@dataclass(frozen=True)
class LifeItemResult:
    item: dict[str, Any]
    created: bool


def _capture_life_item_fact(item: dict[str, Any], verb: str) -> None:
    """Best-effort: append a life-item event to the user fact stream.

    Runs after the life-item write has committed; a failure here must never
    fail the user-facing operation, so all exceptions are swallowed.
    """
    title = (item.get("title") or "").strip()
    if not title:
        return
    kind = item.get("item_type") or "item"
    try:
        # Local import avoids a module-load cycle (user_model imports app.db, not lifecycle).
        from app.user_model import capture_fact
        capture_fact(
            source="life_item",
            text=f"{verb} {kind}: {title}",
            ref={"life_item_id": str(item["id"]), "kind": kind},
        )
    except Exception:
        logger.warning("Failed to capture life-item fact for %s", item.get("id"), exc_info=True)


def get_or_create_default_module_instance(conn: Connection, module_id: str) -> UUID:
    """Return the default Module Instance for a developer-created module."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT mi.id
            FROM module_instances mi
            WHERE mi.module_id = %s
            ORDER BY mi.created_at ASC
            LIMIT 1
            """,
            (module_id,),
        )
        row = cur.fetchone()
        if row is not None:
            return row["id"]

        module = _get_module(conn, module_id)
        cur.execute(
            """
            INSERT INTO module_instances (module_id, display_name, settings)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (module_id, module["name"], Jsonb(module["default_settings"])),
        )
        instance_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO module_settings (module_instance_id, settings)
            VALUES (%s, %s)
            """,
            (instance_id, Jsonb(module["default_settings"])),
        )
        return instance_id


def create_life_item(
    *,
    module_id: str,
    item_type: str,
    title: str,
    request_id: str,
    description: str = "",
    payload: Mapping[str, Any] | None = None,
    source: Mapping[str, Any] | None = None,
    lifecycle_status: str = "active",
    module_instance_id: UUID | str | None = None,
    parent_life_item_id: UUID | str | None = None,
    side_table_data: Mapping[str, Any] | None = None,
) -> LifeItemResult:
    """Create a generalized or extended Life Item in one transaction.

    Repeating the same request_id is idempotent and returns the existing item
    without mutating it.
    """
    with transaction() as conn:
        module = _get_module(conn, module_id)
        _validate_lifecycle_status(module, lifecycle_status)
        instance_id = module_instance_id or get_or_create_default_module_instance(conn, module_id)
        _validate_module_instance(conn, instance_id, module_id)

        retrieval_policy = module["retrieval_policy"]
        chunk_status = _initial_chunk_status(retrieval_policy)
        bucket_update_status = "pending" if retrieval_policy.get("create_bucket_updates", True) else "not_needed"

        with conn.cursor() as cur:
            cur.execute(
                """
                WITH inserted AS (
                    INSERT INTO life_items (
                        parent_life_item_id, module_instance_id, item_type, title, description,
                        lifecycle_status, payload, source, request_id,
                        connection_status, chunk_status, bucket_update_status
                    )
                    VALUES (
                        %(parent_life_item_id)s, %(module_instance_id)s, %(item_type)s, %(title)s,
                        %(description)s, %(lifecycle_status)s, %(payload)s,
                        %(source)s, %(request_id)s, 'pending',
                        %(chunk_status)s, %(bucket_update_status)s
                    )
                    ON CONFLICT (request_id) DO NOTHING
                    RETURNING *, TRUE AS created
                )
                SELECT * FROM inserted
                UNION ALL
                SELECT life_items.*, FALSE AS created
                FROM life_items
                WHERE request_id = %(request_id)s
                LIMIT 1
                """,
                {
                    "module_instance_id": instance_id,
                    "parent_life_item_id": parent_life_item_id,
                    "item_type": item_type,
                    "title": title,
                    "description": description,
                    "lifecycle_status": lifecycle_status,
                    "payload": Jsonb(dict(payload or {})),
                    "source": Jsonb(dict(source or {})),
                    "request_id": request_id,
                    "chunk_status": chunk_status,
                    "bucket_update_status": bucket_update_status,
                },
            )
            row = cur.fetchone()

        if row is None:
            raise LifeItemError(f"Could not create or find Life Item for request_id={request_id}")

        created = bool(row["created"])
        item = dict(row)
        item.pop("created", None)

        if created and module["storage_strategy"] == "extended":
            _insert_side_table_row(conn, module, item["id"], side_table_data or {})

    if created:
        _capture_life_item_fact(item, "Added")

    return LifeItemResult(item=item, created=created)


def update_life_item(
    life_item_id: UUID | str,
    *,
    title: str | None = None,
    description: str | None = None,
    payload: Mapping[str, Any] | None = None,
    meaningful_edit: bool = True,
) -> dict[str, Any]:
    """Update editable Life Item fields and re-queue derived lifecycle work."""
    assignments = []
    params: dict[str, Any] = {"life_item_id": life_item_id}

    if title is not None:
        assignments.append("title = %(title)s")
        params["title"] = title
    if description is not None:
        assignments.append("description = %(description)s")
        params["description"] = description
    if payload is not None:
        assignments.append("payload = %(payload)s")
        params["payload"] = Jsonb(dict(payload))

    if not assignments:
        return get_life_item(life_item_id)

    if meaningful_edit:
        assignments.extend(
            [
                "connection_status = 'pending'",
                "bucket_update_status = CASE WHEN bucket_update_status = 'not_needed' THEN 'not_needed' ELSE 'pending' END",
                "chunk_status = CASE WHEN chunk_status = 'not_needed' THEN 'not_needed' ELSE 'pending' END",
            ]
        )

    assignments.append("updated_at = now()")

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE life_items
                SET {", ".join(assignments)}
                WHERE id = %(life_item_id)s
                RETURNING *
                """,
                params,
            )
            row = cur.fetchone()
            if row is None:
                raise LifeItemError(f"Unknown Life Item: {life_item_id}")
            updated = dict(row)

    if meaningful_edit:
        _capture_life_item_fact(updated, "Updated")
    return updated


def set_lifecycle_status(life_item_id: UUID | str, lifecycle_status: str) -> dict[str, Any]:
    """Set a Life Item's normalized lifecycle status."""
    with transaction() as conn:
        module = _get_life_item_module(conn, life_item_id)
        _validate_lifecycle_status(module, lifecycle_status)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE life_items
                SET lifecycle_status = %s,
                    deleted_at = CASE WHEN %s = 'deleted' THEN now() ELSE deleted_at END,
                    updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (lifecycle_status, lifecycle_status, life_item_id),
            )
            row = cur.fetchone()
            if row is None:
                raise LifeItemError(f"Unknown Life Item: {life_item_id}")
            return dict(row)


def delete_life_item(life_item_id: UUID | str) -> None:
    """Hard-delete a Life Item and rely on database cascades for derived rows."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM life_items WHERE id = %s RETURNING id, title, item_type",
                (life_item_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise LifeItemError(f"Unknown Life Item: {life_item_id}")
            removed = dict(row)

    _capture_life_item_fact(removed, "Removed")


def get_life_item(life_item_id: UUID | str) -> dict[str, Any]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM life_items WHERE id = %s", (life_item_id,))
            row = cur.fetchone()
            if row is None:
                raise LifeItemError(f"Unknown Life Item: {life_item_id}")
            return dict(row)


def _get_module(conn: Connection, module_id: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM modules WHERE id = %s", (module_id,))
        row = cur.fetchone()
        if row is None:
            raise LifeItemError(f"Unknown module: {module_id}")
        return dict(row)


def _get_life_item_module(conn: Connection, life_item_id: UUID | str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.*
            FROM life_items li
            JOIN module_instances mi ON mi.id = li.module_instance_id
            JOIN modules m ON m.id = mi.module_id
            WHERE li.id = %s
            """,
            (life_item_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise LifeItemError(f"Unknown Life Item: {life_item_id}")
        return dict(row)


def _validate_module_instance(conn: Connection, module_instance_id: UUID | str, module_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM module_instances WHERE id = %s AND module_id = %s",
            (module_instance_id, module_id),
        )
        if cur.fetchone() is None:
            raise LifeItemError(f"Module Instance {module_instance_id} does not belong to {module_id}")


def _validate_lifecycle_status(module: Mapping[str, Any], lifecycle_status: str) -> None:
    if lifecycle_status not in module["valid_lifecycle_statuses"]:
        raise LifeItemError(
            f"Lifecycle status {lifecycle_status!r} is not valid for module {module['id']!r}"
        )


def _initial_chunk_status(retrieval_policy: Mapping[str, Any]) -> str:
    if not retrieval_policy.get("create_chunks", True):
        return "not_needed"
    return retrieval_policy.get("default_chunk_status", "pending")


def _insert_side_table_row(
    conn: Connection,
    module: Mapping[str, Any],
    life_item_id: UUID,
    side_table_data: Mapping[str, Any],
) -> None:
    with conn.cursor() as cur:
        if module["side_table"] == "task_items":
            cur.execute(
                """
                INSERT INTO task_items (life_item_id, due_window, due_date, priority, module_status)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    life_item_id,
                    side_table_data.get("due_window", "this_week"),
                    side_table_data.get("due_date"),
                    side_table_data.get("priority"),
                    side_table_data.get("module_status"),
                ),
            )
            return

        if module["side_table"] == "document_items":
            cur.execute(
                """
                INSERT INTO document_items (
                    life_item_id, unique_name, original_name, mime_type,
                    byte_size, content_sha256, category_tag, connection_summary, tag_status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    life_item_id,
                    side_table_data["unique_name"],
                    side_table_data["original_name"],
                    side_table_data.get("mime_type", "text/plain"),
                    side_table_data.get("byte_size", 0),
                    side_table_data["content_sha256"],
                    side_table_data.get("category_tag", ""),
                    side_table_data.get("connection_summary", ""),
                    side_table_data.get("tag_status", "pending"),
                ),
            )
            return

        if module["side_table"] == "routine_items":
            cur.execute(
                """
                INSERT INTO routine_items (life_item_id, position)
                VALUES (%s, %s)
                """,
                (
                    life_item_id,
                    side_table_data.get("position", 0),
                ),
            )
            return

        if module["side_table"] == "plan_items":
            cur.execute(
                """
                INSERT INTO plan_items (
                    life_item_id, progress_percent, completed_steps, total_steps
                )
                VALUES (%s, %s, %s, %s)
                """,
                (
                    life_item_id,
                    side_table_data.get("progress_percent", 0),
                    side_table_data.get("completed_steps", 0),
                    side_table_data.get("total_steps", 0),
                ),
            )
            return

    raise LifeItemError(f"Unsupported Side Table: {module['side_table']}")
