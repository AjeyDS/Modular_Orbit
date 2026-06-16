"""Tasks module service.

Tasks prove extended storage: every Task is a Life Item, and exact task fields
live in the task_items Side Table.
"""

from __future__ import annotations

import calendar
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from app.db import transaction
from app.lifecycle import (
    LifeItemError,
    create_life_item,
    delete_life_item,
    process_lifecycle_for_item,
    set_lifecycle_status,
)
from app.llm import LLMUnavailable, generate_json
from app.rag import retrieve_chunks
from app.user_model import build_user_model_context, list_goals

DueWindow = Literal["this_week", "this_month", "someday", "exact"]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    due_window: DueWindow = "this_week"
    due_date: date | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    module_status: str | None = None
    request_id: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    due_window: DueWindow | None = None
    due_date: date | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    module_status: str | None = None


class TaskItem(BaseModel):
    id: UUID
    title: str
    description: str
    lifecycle_status: str
    connection_status: str
    chunk_status: str
    bucket_update_status: str
    due_window: DueWindow
    due_date: date | None
    priority: int | None
    module_status: str | None
    completed_at: datetime | None
    original_title: str | None = None
    original_description: str | None = None
    rewrite_status: str = "skipped"
    created_at: datetime
    updated_at: datetime


class TaskPrioritySuggestionEntry(BaseModel):
    task_id: UUID
    title: str
    reason: str


class TaskPrioritySuggestionState(BaseModel):
    id: UUID | None = None
    status: str = "empty"
    suggestion_text: str = ""
    ranked: list[TaskPrioritySuggestionEntry] = Field(default_factory=list)
    skippable: list[TaskPrioritySuggestionEntry] = Field(default_factory=list)
    sort_enabled: bool = False
    panel_visible: bool = False
    task_snapshot_hash: str = ""
    context_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskPrioritySuggestionUpdate(BaseModel):
    sort_enabled: bool | None = None
    panel_visible: bool | None = None


def create_task(payload: TaskCreate, *, review: bool = True, review_root: Path | None = None) -> TaskItem:
    request_id = payload.request_id or f"task-{uuid4().hex}"
    rewritten_title, rewritten_description, rewrite_status = _rewrite_task(payload.title, payload.description)
    item_payload = _task_payload(
        due_window=payload.due_window,
        due_date=payload.due_date,
        priority=payload.priority,
        module_status=payload.module_status,
        original_title=payload.title,
        original_description=payload.description,
        rewrite_status=rewrite_status,
    )

    result = create_life_item(
        module_id="tasks",
        item_type="task",
        title=rewritten_title,
        description=rewritten_description,
        payload=item_payload,
        source={
            "kind": "manual_task",
            **payload.source,
        },
        request_id=request_id,
        side_table_data={
            "due_window": payload.due_window,
            "due_date": payload.due_date,
            "priority": payload.priority,
            "module_status": payload.module_status,
        },
    )

    if review and result.created:
        process_lifecycle_for_item(result.item["id"], root=review_root)

    if result.created:
        invalidate_task_priority_suggestions()

    return get_task(result.item["id"])


def update_task(task_id: UUID | str, payload: TaskUpdate, *, review: bool = True) -> TaskItem:
    existing = get_task(task_id)
    changed_fields = payload.model_fields_set
    next_title = payload.title if "title" in changed_fields and payload.title is not None else existing.title
    next_description = payload.description if "description" in changed_fields and payload.description is not None else existing.description
    next_due_window = payload.due_window if "due_window" in changed_fields and payload.due_window is not None else existing.due_window
    next_due_date = payload.due_date if "due_date" in changed_fields else existing.due_date
    next_priority = payload.priority if "priority" in changed_fields else existing.priority
    next_module_status = payload.module_status if "module_status" in changed_fields else existing.module_status
    original_payload = _get_life_item_payload(task_id)

    item_payload = _task_payload(
        due_window=next_due_window,
        due_date=next_due_date,
        priority=next_priority,
        module_status=next_module_status,
        original_title=original_payload.get("original_title") or existing.original_title,
        original_description=original_payload.get("original_description") or existing.original_description,
        rewrite_status=original_payload.get("rewrite_status") or existing.rewrite_status,
    )
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
                    task_id,
                ),
            )
            cur.execute(
                """
                UPDATE task_items
                SET due_window = %s,
                    due_date = %s,
                    priority = %s,
                    module_status = %s,
                    updated_at = now()
                WHERE life_item_id = %s
                """,
                (next_due_window, next_due_date, next_priority, next_module_status, task_id),
            )

    if review:
        process_lifecycle_for_item(task_id)

    return get_task(task_id)


def complete_task(task_id: UUID | str) -> TaskItem:
    task = get_task(task_id)
    completed_at = datetime.now(timezone.utc)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE life_items
                SET lifecycle_status = 'completed',
                    updated_at = now()
                WHERE id = %s
                """,
                (task_id,),
            )
            cur.execute(
                """
                UPDATE task_items
                SET completed_at = %s,
                    module_status = COALESCE(module_status, 'done'),
                    updated_at = now()
                WHERE life_item_id = %s
                """,
                (completed_at, task_id),
            )
            cur.execute(
                """
                INSERT INTO bucket_updates (
                    story_bucket_id, life_item_id, update_text, source_event
                )
                SELECT target_id::uuid, %s, %s, %s
                FROM item_connections
                WHERE source_life_item_id = %s
                    AND target_type = 'story_bucket'
                ON CONFLICT DO NOTHING
                """,
                (
                    task_id,
                    f"Completed task: {task.title}",
                    Jsonb({"source": "task_completed", "completed_at": completed_at.isoformat()}),
                    task_id,
                ),
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
                (task_id, task_id),
            )
    return get_task(task_id)


def archive_task(task_id: UUID | str) -> TaskItem:
    get_task(task_id)
    set_lifecycle_status(task_id, "archived")
    return get_task(task_id)


def remove_task(task_id: UUID | str) -> None:
    task = get_task(task_id)
    delete_life_item(task.id)


def revert_task_rewrite(task_id: UUID | str) -> TaskItem:
    task = get_task(task_id)
    payload = _get_life_item_payload(task_id)
    original_title = payload.get("original_title") or task.original_title or task.title
    original_description = payload.get("original_description") or task.original_description or task.description
    return update_task(task_id, TaskUpdate(title=original_title, description=original_description), review=False)


def list_tasks(
    *,
    status: Literal["active", "completed", "archived", "deleted"] | None = "active",
    limit: int = 50,
) -> list[TaskItem]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT li.*, ti.due_window, ti.due_date, ti.priority, ti.module_status, ti.completed_at
                FROM life_items li
                JOIN task_items ti ON ti.life_item_id = li.id
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE m.id = 'tasks'
                    AND (%(status)s::text IS NULL OR li.lifecycle_status = %(status)s)
                ORDER BY
                    ti.completed_at DESC NULLS LAST,
                    CASE ti.due_window
                        WHEN 'this_week' THEN 0
                        WHEN 'exact' THEN 1
                        WHEN 'this_month' THEN 2
                        WHEN 'someday' THEN 3
                        ELSE 4
                    END,
                    ti.due_date ASC NULLS LAST,
                    li.created_at DESC
                LIMIT %(limit)s
                """,
                {"status": status, "limit": limit},
            )
            return [_row_to_task(row) for row in cur.fetchall()]


def get_task_priority_suggestion() -> TaskPrioritySuggestionState:
    """Return the latest active AI priority run, if one exists."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM task_priority_suggestion_runs
                WHERE status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
    if row is None:
        return _empty_priority_suggestion()
    return _row_to_priority_suggestion(row)


def generate_task_priority_suggestion() -> TaskPrioritySuggestionState:
    """Generate and persist an advisory AI priority order for active Tasks."""
    active_tasks = list_tasks(status="active", limit=100)
    if not active_tasks:
        return _empty_priority_suggestion("Add a few active tasks first, then I can help order them.")

    context_summary = _task_priority_context_summary()
    snapshot_hash = _task_snapshot_hash(active_tasks)
    ranked: list[TaskPrioritySuggestionEntry] = []
    skippable: list[TaskPrioritySuggestionEntry] = []
    suggestion_text = ""

    try:
        response = generate_json(
            _priority_prompt(active_tasks, context_summary),
            system=(
                "You are Orbit's Tasks focus advisor. Rank active tasks by what the person "
                "should focus on next using goals, story buckets, recent activity, and task details. "
                "Return only valid JSON with ranked and skippable arrays."
            ),
            temperature=0.2,
            max_output_tokens=1600,
        )
        ranked, skippable = _normalize_suggestion_entries(response, active_tasks)
        suggestion_text = str(response.get("summary") or "").strip()
    except (LLMUnavailable, Exception):
        ranked, skippable = [], []

    if not ranked:
        ranked, skippable = _fallback_priority_entries(active_tasks)
        suggestion_text = "Fallback priority order based on due date, stored priority, and recency."

    if not suggestion_text:
        suggestion_text = _suggestion_text(ranked, skippable)

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE task_priority_suggestion_runs
                SET status = 'invalidated',
                    invalidated_at = now(),
                    updated_at = now()
                WHERE status = 'active'
                """
            )
            cur.execute(
                """
                INSERT INTO task_priority_suggestion_runs (
                    suggestion_text, ranked, skippable, task_snapshot_hash, context_summary
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    suggestion_text,
                    Jsonb([entry.model_dump(mode="json") for entry in ranked]),
                    Jsonb([entry.model_dump(mode="json") for entry in skippable]),
                    snapshot_hash,
                    Jsonb(context_summary),
                ),
            )
            row = cur.fetchone()
    return _row_to_priority_suggestion(row)


def update_task_priority_suggestion(
    run_id: UUID | str,
    payload: TaskPrioritySuggestionUpdate,
) -> TaskPrioritySuggestionState:
    """Persist UI preferences for the active priority suggestion run."""
    if not payload.model_fields_set:
        return get_task_priority_suggestion()

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE task_priority_suggestion_runs
                SET sort_enabled = COALESCE(%s, sort_enabled),
                    panel_visible = COALESCE(%s, panel_visible),
                    updated_at = now()
                WHERE id = %s AND status = 'active'
                RETURNING *
                """,
                (payload.sort_enabled, payload.panel_visible, run_id),
            )
            row = cur.fetchone()
    if row is None:
        raise LifeItemError(f"Unknown active Task priority suggestion run: {run_id}")
    return _row_to_priority_suggestion(row)


def invalidate_task_priority_suggestions() -> None:
    """Invalidate saved advisory ordering when the active task set changes."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE task_priority_suggestion_runs
                SET status = 'invalidated',
                    invalidated_at = now(),
                    updated_at = now()
                WHERE status = 'active'
                """
            )


def get_task(task_id: UUID | str) -> TaskItem:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT li.*, ti.due_window, ti.due_date, ti.priority, ti.module_status, ti.completed_at
                FROM life_items li
                JOIN task_items ti ON ti.life_item_id = li.id
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE li.id = %s AND m.id = 'tasks'
                """,
                (task_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise LifeItemError(f"Unknown Task: {task_id}")
            return _row_to_task(row)


def _row_to_task(row: dict[str, Any]) -> TaskItem:
    payload = row.get("payload") or {}
    return TaskItem(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        lifecycle_status=row["lifecycle_status"],
        connection_status=row["connection_status"],
        chunk_status=row["chunk_status"],
        bucket_update_status=row["bucket_update_status"],
        due_window=row["due_window"],
        due_date=row["due_date"],
        priority=row["priority"],
        module_status=row["module_status"],
        completed_at=row["completed_at"],
        original_title=payload.get("original_title"),
        original_description=payload.get("original_description"),
        rewrite_status=payload.get("rewrite_status") or "skipped",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_priority_suggestion(row: dict[str, Any]) -> TaskPrioritySuggestionState:
    return TaskPrioritySuggestionState(
        id=row["id"],
        status=row["status"],
        suggestion_text=row["suggestion_text"],
        ranked=[TaskPrioritySuggestionEntry(**entry) for entry in row["ranked"]],
        skippable=[TaskPrioritySuggestionEntry(**entry) for entry in row["skippable"]],
        sort_enabled=row["sort_enabled"],
        panel_visible=row["panel_visible"],
        task_snapshot_hash=row["task_snapshot_hash"],
        context_summary=row["context_summary"] or {},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _empty_priority_suggestion(message: str = "") -> TaskPrioritySuggestionState:
    return TaskPrioritySuggestionState(suggestion_text=message)


def _task_priority_context_summary() -> dict[str, Any]:
    goals = [
        {"id": goal.goal_id, "title": goal.title, "body": goal.body[:500], "status": goal.status}
        for goal in list_goals()
        if goal.status == "active"
    ]
    recent_logs = _recent_life_items("logs", limit=5)
    recent_plans = _recent_life_items("plans", limit=5)
    chunks = [
        {
            "life_item_id": chunk.life_item_id,
            "title": chunk.title,
            "source_type": chunk.source_type,
            "content": chunk.content[:700],
            "score": chunk.score,
        }
        for chunk in retrieve_chunks("current goals blockers active tasks priorities", limit=5)
    ]
    return {
        "active_goals": goals,
        "user_model": build_user_model_context(budget=1800),
        "recent_logs": recent_logs,
        "recent_plans": recent_plans,
        "relevant_chunks": chunks,
    }


def _recent_life_items(module_id: str, *, limit: int) -> list[dict[str, Any]]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT li.id, li.title, li.description, li.payload, li.updated_at
                FROM life_items li
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE m.id = %s AND li.lifecycle_status = 'active'
                ORDER BY li.updated_at DESC
                LIMIT %s
                """,
                (module_id, limit),
            )
            return [
                {
                    "id": str(row["id"]),
                    "title": row["title"],
                    "description": row["description"],
                    "payload": row["payload"],
                    "updated_at": row["updated_at"].isoformat(),
                }
                for row in cur.fetchall()
            ]


def _priority_prompt(tasks: list[TaskItem], context_summary: dict[str, Any]) -> str:
    task_payload = [
        {
            "task_id": str(task.id),
            "title": task.title,
            "description": task.description,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "priority": task.priority,
            "module_status": task.module_status,
            "created_at": task.created_at.isoformat(),
        }
        for task in tasks
    ]
    return (
        "Rank the active tasks for today's focus. Return JSON shaped exactly like:\n"
        "{\n"
        '  "summary": "one short sentence about the ordering",\n'
        '  "ranked": [{"task_id": "uuid", "title": "task title", "reason": "why this is P1/P2/P3"}],\n'
        '  "skippable": [{"task_id": "uuid", "title": "task title", "reason": "why this can wait"}]\n'
        "}\n\n"
        "Rules:\n"
        "- ranked must contain at most 3 tasks.\n"
        "- skippable must contain at most 1 low-alignment task.\n"
        "- Use only task_id values present in active_tasks.\n"
        "- Reasons should be specific, calm, and under 120 characters.\n\n"
        f"active_tasks:\n{json.dumps(task_payload, indent=2)}\n\n"
        f"context_summary:\n{json.dumps(context_summary, indent=2, default=str)}\n"
    )


def _normalize_suggestion_entries(
    response: dict[str, Any],
    tasks: list[TaskItem],
) -> tuple[list[TaskPrioritySuggestionEntry], list[TaskPrioritySuggestionEntry]]:
    task_map = {str(task.id): task for task in tasks}
    used: set[str] = set()
    ranked = _entries_from_response(response.get("ranked"), task_map, used, limit=3)
    skippable = _entries_from_response(response.get("skippable"), task_map, used, limit=1)
    return ranked, skippable


def _entries_from_response(
    raw_entries: Any,
    task_map: dict[str, TaskItem],
    used: set[str],
    *,
    limit: int,
) -> list[TaskPrioritySuggestionEntry]:
    if not isinstance(raw_entries, list):
        return []
    entries: list[TaskPrioritySuggestionEntry] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        task_id = str(raw.get("task_id") or "").strip()
        if task_id not in task_map or task_id in used:
            continue
        task = task_map[task_id]
        reason = " ".join(str(raw.get("reason") or "").split())[:220]
        entries.append(
            TaskPrioritySuggestionEntry(
                task_id=task.id,
                title=task.title,
                reason=reason or "This task appears most aligned with your current focus.",
            )
        )
        used.add(task_id)
        if len(entries) >= limit:
            break
    return entries


def _fallback_priority_entries(
    tasks: list[TaskItem],
) -> tuple[list[TaskPrioritySuggestionEntry], list[TaskPrioritySuggestionEntry]]:
    ranked_tasks = sorted(tasks, key=_fallback_task_sort_key)
    ranked = [
        TaskPrioritySuggestionEntry(
            task_id=task.id,
            title=task.title,
            reason=_fallback_reason(task),
        )
        for task in ranked_tasks[:3]
    ]
    remaining = ranked_tasks[3:]
    skippable = []
    if remaining:
        skip_task = remaining[-1]
        skippable.append(
            TaskPrioritySuggestionEntry(
                task_id=skip_task.id,
                title=skip_task.title,
                reason="Lower urgency than the ranked tasks based on due date and priority.",
            )
        )
    return ranked, skippable


def _fallback_task_sort_key(task: TaskItem) -> tuple[int, int, str]:
    today = date.today()
    effective_due_date = _effective_due_date(task)
    if effective_due_date is None:
        due_bucket = 40
    elif effective_due_date < today:
        due_bucket = 0
    elif effective_due_date == today:
        due_bucket = 5
    elif (effective_due_date - today).days <= 3:
        due_bucket = 10
    elif (effective_due_date - today).days <= 7:
        due_bucket = 20
    else:
        due_bucket = 30
    priority_bucket = task.priority if task.priority is not None else 9
    return (due_bucket, priority_bucket, -task.created_at.timestamp())


def _fallback_reason(task: TaskItem) -> str:
    today = date.today()
    effective_due_date = _effective_due_date(task)
    if effective_due_date and effective_due_date < today:
        return "Overdue, so it should be cleared before it creates more drag."
    if effective_due_date == today:
        return "Due today, making it the cleanest immediate focus."
    if effective_due_date and (effective_due_date - today).days <= 3:
        return "Due soon, so moving it forward now protects the week."
    if task.priority is not None:
        return f"Stored priority P{task.priority} puts it ahead of less urgent open tasks."
    return "Recent active task with enough signal to be worth considering next."


def _task_snapshot_hash(tasks: list[TaskItem]) -> str:
    payload = [
        {
            "id": str(task.id),
            "title": task.title,
            "description": task.description,
            "due_window": task.due_window,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "priority": task.priority,
            "module_status": task.module_status,
            "updated_at": task.updated_at.isoformat(),
        }
        for task in tasks
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _suggestion_text(
    ranked: list[TaskPrioritySuggestionEntry],
    skippable: list[TaskPrioritySuggestionEntry],
) -> str:
    lines = [f"P{index}: {entry.title} — {entry.reason}" for index, entry in enumerate(ranked, start=1)]
    lines.extend(f"Low alignment: {entry.title} — {entry.reason}" for entry in skippable)
    return "\n".join(lines)


def _task_payload(
    *,
    due_window: DueWindow,
    due_date: date | None,
    priority: int | None,
    module_status: str | None,
    original_title: str | None = None,
    original_description: str | None = None,
    rewrite_status: str | None = None,
) -> dict[str, Any]:
    return {
        "due_window": due_window,
        "due_date": due_date.isoformat() if due_date else None,
        "priority": priority,
        "module_status": module_status,
        "original_title": original_title,
        "original_description": original_description,
        "rewrite_status": rewrite_status or "skipped",
    }


def _effective_due_date(task: TaskItem) -> date | None:
    today = date.today()
    if task.due_window == "someday":
        return None
    if task.due_window == "this_week":
        return today + _week_delta(today)
    if task.due_window == "this_month":
        return date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    return task.due_date


def _week_delta(today: date):
    from datetime import timedelta

    return timedelta(days=6 - today.weekday())


def _rewrite_task(title: str, description: str) -> tuple[str, str, str]:
    context = _task_priority_context_summary()
    try:
        response = generate_json(
            _rewrite_prompt(title, description, context),
            system=(
                "You reorganize a freshly captured task using the person's goals and story buckets. "
                "Produce a short, clean imperative title and an organized body. Return only JSON: "
                '{"title": str, "description": str}.'
            ),
            temperature=0.2,
            max_output_tokens=400,
        )
        new_title = " ".join(str(response.get("title") or "").split())[:120]
        new_description = str(response.get("description") or "").strip()
        if new_title:
            return new_title, new_description or description, "complete"
    except (LLMUnavailable, Exception):
        pass
    return title, description, "skipped"


def _rewrite_prompt(title: str, description: str, context_summary: dict[str, Any]) -> str:
    return (
        "Rewrite this captured task for a task list.\n"
        "Rules:\n"
        "- Keep the user's intent intact.\n"
        "- Title should be short, imperative, and specific.\n"
        "- Description should organize details without adding facts.\n\n"
        f"task:\n{json.dumps({'title': title, 'description': description}, indent=2)}\n\n"
        f"context_summary:\n{json.dumps(context_summary, indent=2, default=str)}\n"
    )


def _get_life_item_payload(task_id: UUID | str) -> dict[str, Any]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM life_items WHERE id = %s", (task_id,))
            row = cur.fetchone()
    if row is None:
        raise LifeItemError(f"Unknown Task: {task_id}")
    return row["payload"] or {}
