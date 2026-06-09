"""HTTP API for the Routine module."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.lifecycle import LifeItemError
from app.modules.routine import (
    RoutineCompletionRequest,
    RoutineCreate,
    RoutineItem,
    RoutineState,
    RoutineUpdate,
    archive_routine_item,
    complete_routine_item,
    create_routine_item,
    list_routine_state,
    uncomplete_routine_item,
    update_routine_item,
)


router = APIRouter(prefix="/modules/routine", tags=["routine"])


@router.get("", response_model=RoutineState)
def list_routine_endpoint(
    target_date: date | None = Query(None, alias="date"),
    limit: int = Query(100, ge=1, le=200),
) -> RoutineState:
    return list_routine_state(target_date=target_date, limit=limit)


@router.post("", response_model=RoutineItem, status_code=status.HTTP_201_CREATED)
def create_routine_endpoint(payload: RoutineCreate) -> RoutineItem:
    return create_routine_item(payload)


@router.patch("/{routine_id}", response_model=RoutineItem)
def update_routine_endpoint(routine_id: UUID, payload: RoutineUpdate) -> RoutineItem:
    try:
        return update_routine_item(routine_id, payload)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{routine_id}/complete", response_model=RoutineItem)
def complete_routine_endpoint(routine_id: UUID, payload: RoutineCompletionRequest) -> RoutineItem:
    try:
        return complete_routine_item(routine_id, payload.date)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{routine_id}/complete", response_model=RoutineItem)
def uncomplete_routine_endpoint(
    routine_id: UUID,
    target_date: date = Query(..., alias="date"),
) -> RoutineItem:
    try:
        return uncomplete_routine_item(routine_id, target_date)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{routine_id}/archive", response_model=RoutineItem)
def archive_routine_endpoint(routine_id: UUID) -> RoutineItem:
    try:
        return archive_routine_item(routine_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
