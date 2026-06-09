"""HTTP API for the Tasks module."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.lifecycle import LifeItemError
from app.modules.tasks import (
    TaskCreate,
    TaskItem,
    TaskPrioritySuggestionState,
    TaskPrioritySuggestionUpdate,
    TaskUpdate,
    complete_task,
    create_task,
    generate_task_priority_suggestion,
    get_task,
    get_task_priority_suggestion,
    list_tasks,
    remove_task,
    revert_task_rewrite,
    update_task_priority_suggestion,
    update_task,
)


router = APIRouter(prefix="/modules/tasks", tags=["tasks"])


@router.post("", response_model=TaskItem, status_code=status.HTTP_201_CREATED)
def create_task_endpoint(payload: TaskCreate) -> TaskItem:
    return create_task(payload)


@router.get("", response_model=list[TaskItem])
def list_tasks_endpoint(
    status_filter: Literal["active", "completed"] | None = Query("active", alias="status"),
    limit: int = Query(50, ge=1, le=100),
) -> list[TaskItem]:
    return list_tasks(status=status_filter, limit=limit)


@router.get("/priority-suggestion", response_model=TaskPrioritySuggestionState)
def get_task_priority_suggestion_endpoint() -> TaskPrioritySuggestionState:
    return get_task_priority_suggestion()


@router.post("/priority-suggestion", response_model=TaskPrioritySuggestionState)
def generate_task_priority_suggestion_endpoint() -> TaskPrioritySuggestionState:
    return generate_task_priority_suggestion()


@router.patch("/priority-suggestion/{run_id}", response_model=TaskPrioritySuggestionState)
def update_task_priority_suggestion_endpoint(
    run_id: UUID,
    payload: TaskPrioritySuggestionUpdate,
) -> TaskPrioritySuggestionState:
    try:
        return update_task_priority_suggestion(run_id, payload)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{task_id}", response_model=TaskItem)
def get_task_endpoint(task_id: UUID) -> TaskItem:
    try:
        return get_task(task_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{task_id}", response_model=TaskItem)
def update_task_endpoint(task_id: UUID, payload: TaskUpdate) -> TaskItem:
    try:
        return update_task(task_id, payload)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{task_id}/complete", response_model=TaskItem)
def complete_task_endpoint(task_id: UUID) -> TaskItem:
    try:
        return complete_task(task_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{task_id}/revert-rewrite", response_model=TaskItem)
def revert_task_rewrite_endpoint(task_id: UUID) -> TaskItem:
    try:
        return revert_task_rewrite(task_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task_endpoint(task_id: UUID) -> None:
    try:
        remove_task(task_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
