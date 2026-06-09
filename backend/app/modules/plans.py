"""Plans module service."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from psycopg import Connection
from psycopg.types.json import Jsonb

from app.db import transaction
from app.lifecycle import (
    LifeItemError,
    create_life_item,
    delete_life_item,
    process_lifecycle_for_item,
    set_lifecycle_status,
)
from app.modules.plan_parser import ParsedPlanNode


class PlanStepCreate(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    parent_step_id: UUID | None = None
    position: int = 0


class PlanCreate(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    category: Literal["work", "learn", "personal"] = "personal"
    raw_text: str | None = None
    steps: list[PlanStepCreate] = Field(default_factory=list)
    nodes: list[ParsedPlanNode] = Field(default_factory=list)
    request_id: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)


class PlanStepUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    status: Literal["active", "completed", "archived"] | None = None
    position: int | None = None


class PlanStepItem(BaseModel):
    id: UUID
    parent_step_id: UUID | None
    position: int
    title: str
    description: str
    status: str
    completed_at: datetime | None
    children: list["PlanStepItem"] = Field(default_factory=list)


class PlanItem(BaseModel):
    id: UUID
    title: str
    description: str
    lifecycle_status: str
    connection_status: str
    chunk_status: str
    bucket_update_status: str
    progress_percent: int
    completed_steps: int
    total_steps: int
    completed_at: datetime | None
    steps: list[PlanStepItem]
    created_at: datetime
    updated_at: datetime


PlanStepItem.model_rebuild()


def create_plan(payload: PlanCreate, *, review: bool = True, review_root: Path | None = None) -> PlanItem:
    request_id = payload.request_id or f"plan-{uuid4().hex}"
    result = create_life_item(
        module_id="plans",
        item_type="plan",
        title=payload.title,
        description=payload.description,
        payload=_plan_payload(payload),
        source={
            "kind": "manual_plan",
            "category": payload.category,
            **payload.source,
        },
        request_id=request_id,
        side_table_data={
            "total_steps": 0,
            "completed_steps": 0,
            "progress_percent": 0,
        },
    )

    if result.created:
        with transaction() as conn:
            instance_id = result.item["module_instance_id"]
            if payload.nodes:
                _insert_node_steps(conn, result.item["id"], instance_id, payload.nodes)
            else:
                _insert_flat_steps(conn, result.item["id"], instance_id, payload.steps)
            _sync_plan_rollup(conn, result.item["id"])
            _upsert_plan_summary_chunk(conn, result.item["id"])

        if review:
            process_lifecycle_for_item(result.item["id"], root=review_root)

    return get_plan(result.item["id"])


def list_plans(
    *,
    status: Literal["active", "completed", "archived", "deleted"] | None = "active",
    limit: int = 50,
) -> list[PlanItem]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT li.id
                FROM life_items li
                JOIN plan_items pi ON pi.life_item_id = li.id
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE m.id = 'plans'
                    AND li.item_type = 'plan'
                    AND (%(status)s::text IS NULL OR li.lifecycle_status = %(status)s)
                ORDER BY pi.completed_at DESC NULLS LAST, li.created_at DESC
                LIMIT %(limit)s
                """,
                {"status": status, "limit": limit},
            )
            rows = cur.fetchall()

    return [get_plan(row["id"]) for row in rows]


def get_plan(plan_id: UUID | str) -> PlanItem:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT li.*, pi.progress_percent, pi.completed_steps,
                    pi.total_steps, pi.completed_at
                FROM life_items li
                JOIN plan_items pi ON pi.life_item_id = li.id
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE li.id = %s AND m.id = 'plans' AND li.item_type = 'plan'
                """,
                (plan_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise LifeItemError(f"Unknown Plan: {plan_id}")
            steps = _get_steps(cur, plan_id)
            return _row_to_plan(row, steps)


def add_plan_step(plan_id: UUID | str, payload: PlanStepCreate) -> PlanItem:
    plan = get_plan(plan_id)
    with transaction() as conn:
        parent = _get_life_item_row(conn, plan.id)
        _create_step_life_item(
            conn,
            plan_id=plan.id,
            module_instance_id=parent["module_instance_id"],
            title=payload.title,
            description=payload.description,
            parent_step_id=payload.parent_step_id,
            position=payload.position,
        )
        _sync_plan_rollup(conn, plan.id)
        _upsert_plan_summary_chunk(conn, plan.id)
    return get_plan(plan.id)


def _get_life_item_row(conn: Connection, life_item_id: UUID | str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM life_items WHERE id = %s", (life_item_id,))
        row = cur.fetchone()
        if row is None:
            raise LifeItemError(f"Unknown Life Item: {life_item_id}")
        return dict(row)


def update_plan_step(plan_id: UUID | str, step_id: UUID | str, payload: PlanStepUpdate) -> PlanItem:
    get_plan(plan_id)
    changed = payload.model_fields_set
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT li.title, li.description, li.lifecycle_status, psi.position, psi.completed_at
                FROM plan_step_items psi
                JOIN life_items li ON li.id = psi.life_item_id
                WHERE psi.life_item_id = %s AND psi.plan_life_item_id = %s
                """,
                (step_id, plan_id),
            )
            current = cur.fetchone()
            if current is None:
                raise LifeItemError(f"Unknown Plan Step: {step_id}")

            next_status = payload.status if "status" in changed and payload.status else current["lifecycle_status"]
            completed_at = current["completed_at"]
            if next_status == "completed" and completed_at is None:
                completed_at = datetime.now(timezone.utc)
            if next_status != "completed":
                completed_at = None

            cur.execute(
                """
                UPDATE life_items
                SET title = %s,
                    description = %s,
                    lifecycle_status = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (
                    payload.title if "title" in changed and payload.title is not None else current["title"],
                    payload.description if "description" in changed and payload.description is not None else current["description"],
                    next_status,
                    step_id,
                ),
            )
            cur.execute(
                """
                UPDATE plan_step_items
                SET position = %s,
                    completed_at = %s,
                    updated_at = now()
                WHERE life_item_id = %s
                """,
                (
                    payload.position if "position" in changed and payload.position is not None else current["position"],
                    completed_at,
                    step_id,
                ),
            )
            cur.execute(
                """
                UPDATE plan_steps
                SET title = %s,
                    description = %s,
                    status = %s,
                    position = %s,
                    completed_at = %s,
                    updated_at = now()
                WHERE id = %s AND life_item_id = %s
                """,
                (
                    payload.title if "title" in changed and payload.title is not None else current["title"],
                    payload.description if "description" in changed and payload.description is not None else current["description"],
                    next_status,
                    payload.position if "position" in changed and payload.position is not None else current["position"],
                    completed_at,
                    step_id,
                    plan_id,
                ),
            )
        _sync_plan_rollup(conn, plan_id)
        _upsert_plan_summary_chunk(conn, plan_id)
        _write_plan_progress_update(conn, plan_id, f"Updated plan step: {step_id}")

    return get_plan(plan_id)


def complete_plan_step(plan_id: UUID | str, step_id: UUID | str) -> PlanItem:
    return update_plan_step(plan_id, step_id, PlanStepUpdate(status="completed"))


def complete_plan(plan_id: UUID | str) -> PlanItem:
    get_plan(plan_id)
    completed_at = datetime.now(timezone.utc)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE life_items SET lifecycle_status = 'completed', updated_at = now() WHERE id = %s",
                (plan_id,),
            )
            cur.execute(
                """
                UPDATE life_items
                SET lifecycle_status = 'completed', updated_at = now()
                WHERE parent_life_item_id = %s AND lifecycle_status <> 'archived'
                """,
                (plan_id,),
            )
            cur.execute(
                """
                UPDATE plan_step_items
                SET completed_at = COALESCE(completed_at, %s),
                    updated_at = now()
                WHERE plan_life_item_id = %s
                """,
                (completed_at, plan_id),
            )
            cur.execute(
                """
                UPDATE plan_steps
                SET status = 'completed',
                    completed_at = COALESCE(completed_at, %s),
                    updated_at = now()
                WHERE life_item_id = %s AND status <> 'archived'
                """,
                (completed_at, plan_id),
            )
            cur.execute(
                """
                UPDATE plan_items
                SET completed_at = %s,
                    progress_percent = 100,
                    completed_steps = total_steps,
                    updated_at = now()
                WHERE life_item_id = %s
                """,
                (completed_at, plan_id),
            )
        _sync_plan_rollup(conn, plan_id)
        _upsert_plan_summary_chunk(conn, plan_id)
        _write_plan_progress_update(conn, plan_id, "Completed plan.")
    return get_plan(plan_id)


def archive_plan(plan_id: UUID | str) -> PlanItem:
    get_plan(plan_id)
    set_lifecycle_status(plan_id, "archived")
    return get_plan(plan_id)


def remove_plan(plan_id: UUID | str) -> None:
    plan = get_plan(plan_id)
    delete_life_item(plan.id)


def _insert_flat_steps(
    conn: Connection,
    plan_id: UUID | str,
    module_instance_id: UUID,
    steps: list[PlanStepCreate],
) -> None:
    for index, step in enumerate(steps):
        _create_step_life_item(
            conn,
            plan_id=plan_id,
            module_instance_id=module_instance_id,
            title=step.title,
            description=step.description,
            parent_step_id=step.parent_step_id,
            position=step.position or index,
        )


def _insert_node_steps(
    conn: Connection,
    plan_id: UUID | str,
    module_instance_id: UUID,
    nodes: list[ParsedPlanNode],
    *,
    parent_step_id: UUID | None = None,
) -> None:
    for index, node in enumerate(nodes):
        step_id = _create_step_life_item(
            conn,
            plan_id=plan_id,
            module_instance_id=module_instance_id,
            title=node.title,
            description=node.description or "",
            parent_step_id=parent_step_id,
            position=index,
            metadata=node.metadata,
        )
        if node.children:
            _insert_node_steps(
                conn,
                plan_id,
                module_instance_id,
                node.children,
                parent_step_id=step_id,
            )


def _create_step_life_item(
    conn: Connection,
    *,
    plan_id: UUID | str,
    module_instance_id: UUID,
    title: str,
    description: str = "",
    parent_step_id: UUID | str | None = None,
    position: int = 0,
    metadata: dict[str, Any] | None = None,
) -> UUID:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO life_items (
                parent_life_item_id, module_instance_id, item_type, title,
                description, lifecycle_status, payload, source, request_id,
                connection_status, chunk_status, bucket_update_status
            )
            VALUES (%s, %s, 'plan_step', %s, %s, 'active', %s, %s, %s,
                'pending', 'not_needed', 'pending')
            RETURNING id
            """,
            (
                plan_id,
                module_instance_id,
                title,
                description,
                Jsonb({"metadata": metadata or {}, "plan_life_item_id": str(plan_id)}),
                Jsonb({"kind": "plan_step", "plan_life_item_id": str(plan_id)}),
                f"plan-step-{plan_id}-{uuid4().hex}",
            ),
        )
        step_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO plan_step_items (
                life_item_id, plan_life_item_id, parent_step_life_item_id, position
            )
            VALUES (%s, %s, %s, %s)
            """,
            (step_id, plan_id, parent_step_id, position),
        )
        cur.execute(
            """
            INSERT INTO plan_steps (
                id, life_item_id, parent_step_id, position, title, description, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'active')
            ON CONFLICT (id) DO NOTHING
            """,
            (step_id, plan_id, parent_step_id, position, title, description),
        )
        return step_id


def _sync_plan_rollup(conn: Connection, plan_id: UUID | str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE li.lifecycle_status <> 'archived') AS total_steps,
                COUNT(*) FILTER (WHERE li.lifecycle_status = 'completed') AS completed_steps
            FROM plan_step_items psi
            JOIN life_items li ON li.id = psi.life_item_id
            WHERE psi.plan_life_item_id = %s
            """,
            (plan_id,),
        )
        row = cur.fetchone()
        total_steps = row["total_steps"] or 0
        completed_steps = row["completed_steps"] or 0
        progress = int((completed_steps / total_steps) * 100) if total_steps else 0
        cur.execute(
            """
            UPDATE plan_items
            SET total_steps = %s,
                completed_steps = %s,
                progress_percent = %s,
                updated_at = now()
            WHERE life_item_id = %s
            """,
            (total_steps, completed_steps, progress, plan_id),
        )
        cur.execute(
            """
            UPDATE life_items
            SET payload = jsonb_set(
                    jsonb_set(payload, '{progress_percent}', to_jsonb(%s::int)),
                    '{step_count}', to_jsonb(%s::int)
                ),
                updated_at = now()
            WHERE id = %s
            """,
            (progress, total_steps, plan_id),
        )


def _upsert_plan_summary_chunk(conn: Connection, plan_id: UUID | str) -> None:
    plan = _get_plan_for_summary(conn, plan_id)
    summary = _plan_summary(plan)
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM knowledge_chunks
            WHERE life_item_id = %s AND source_type = 'plan_summary'
            """,
            (plan_id,),
        )
        cur.execute(
            """
            INSERT INTO knowledge_chunks (life_item_id, content, source_type, metadata)
            VALUES (%s, %s, 'plan_summary', %s)
            """,
            (
                plan_id,
                summary,
                Jsonb(
                    {
                        "progress_percent": plan["progress_percent"],
                        "total_steps": plan["total_steps"],
                    }
                ),
            ),
        )


def _write_plan_progress_update(conn: Connection, plan_id: UUID | str, update_text: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bucket_updates (story_bucket_id, life_item_id, update_text, source_event)
            SELECT target_id::uuid, %s, %s, %s
            FROM item_connections
            WHERE source_life_item_id = %s AND target_type = 'story_bucket'
            ON CONFLICT DO NOTHING
            """,
            (plan_id, update_text, Jsonb({"source": "plan_progress"}), plan_id),
        )
        cur.execute(
            """
            UPDATE life_items
            SET bucket_update_status = CASE
                    WHEN EXISTS (
                        SELECT 1 FROM item_connections
                        WHERE source_life_item_id = %s AND target_type = 'story_bucket'
                    )
                    THEN 'complete'
                    ELSE bucket_update_status
                END,
                updated_at = now()
            WHERE id = %s
            """,
            (plan_id, plan_id),
        )


def _get_plan_for_summary(conn: Connection, plan_id: UUID | str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT li.title, li.description, pi.progress_percent, pi.total_steps,
                pi.completed_steps
            FROM life_items li
            JOIN plan_items pi ON pi.life_item_id = li.id
            WHERE li.id = %s
            """,
            (plan_id,),
        )
        plan = dict(cur.fetchone())
        plan["steps"] = _get_steps(cur, plan_id)
        return plan


def _plan_summary(plan: dict[str, Any]) -> str:
    step_lines = _summary_step_lines(plan["steps"])
    return "\n".join(
        [
            f"Plan: {plan['title']}",
            plan["description"],
            f"Progress: {plan['progress_percent']}% ({plan['completed_steps']}/{plan['total_steps']} steps)",
            *step_lines,
        ]
    ).strip()


def _summary_step_lines(steps: list[PlanStepItem], depth: int = 0) -> list[str]:
    lines: list[str] = []
    prefix = "  " * depth
    for step in steps:
        lines.append(f"{prefix}- [{step.status}] {step.title}")
        lines.extend(_summary_step_lines(step.children, depth + 1))
    return lines


def _get_steps(cur, plan_id: UUID | str) -> list[PlanStepItem]:
    cur.execute(
        """
        SELECT
            li.id,
            psi.parent_step_life_item_id AS parent_step_id,
            psi.position,
            li.title,
            li.description,
            li.lifecycle_status AS status,
            psi.completed_at
        FROM plan_step_items psi
        JOIN life_items li ON li.id = psi.life_item_id
        WHERE psi.plan_life_item_id = %s
        ORDER BY psi.position ASC, li.created_at ASC
        """,
        (plan_id,),
    )
    rows = cur.fetchall()
    by_parent: dict[str | None, list[PlanStepItem]] = {}
    by_id: dict[str, PlanStepItem] = {}
    for row in rows:
        item = PlanStepItem(
            id=row["id"],
            parent_step_id=row["parent_step_id"],
            position=row["position"],
            title=row["title"],
            description=row["description"],
            status=row["status"],
            completed_at=row["completed_at"],
            children=[],
        )
        by_id[str(item.id)] = item
        parent_key = str(row["parent_step_id"]) if row["parent_step_id"] else None
        by_parent.setdefault(parent_key, []).append(item)

    for item in by_id.values():
        item.children = by_parent.get(str(item.id), [])
    return by_parent.get(None, [])


def _row_to_plan(row: dict[str, Any], steps: list[PlanStepItem]) -> PlanItem:
    return PlanItem(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        lifecycle_status=row["lifecycle_status"],
        connection_status=row["connection_status"],
        chunk_status=row["chunk_status"],
        bucket_update_status=row["bucket_update_status"],
        progress_percent=row["progress_percent"],
        completed_steps=row["completed_steps"],
        total_steps=row["total_steps"],
        completed_at=row["completed_at"],
        steps=steps,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _plan_payload(payload: PlanCreate) -> dict[str, Any]:
    steps = payload.nodes or [
        ParsedPlanNode(title=step.title, description=step.description, children=[])
        for step in payload.steps
    ]
    return {
        "category": payload.category,
        "raw_text": payload.raw_text,
        "progress_percent": 0,
        "step_count": len(steps),
        "steps": [step.model_dump(mode="json") for step in steps],
    }
