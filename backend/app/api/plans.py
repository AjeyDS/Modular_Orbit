"""HTTP API for the Plans module."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.lifecycle import LifeItemError
from app.modules.plans import (
    PlanCreate,
    PlanItem,
    PlanStepCreate,
    PlanStepUpdate,
    add_plan_step,
    archive_plan,
    complete_plan,
    complete_plan_step,
    create_plan,
    get_plan,
    list_plans,
    remove_plan,
    update_plan_step,
)
from app.modules.plan_parser import (
    ParsePlanRequest,
    ParsedPlanDraft,
    PlanParseError,
    parse_plan_text,
)


router = APIRouter(prefix="/modules/plans", tags=["plans"])


@router.post("/parse", response_model=ParsedPlanDraft)
def parse_plan_endpoint(payload: ParsePlanRequest) -> ParsedPlanDraft:
    try:
        return parse_plan_text(payload.raw_text)
    except PlanParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "parse_failed",
                "message": str(exc),
                "raw_llm_output": exc.raw_llm_output,
                "validation_error": exc.validation_error,
            },
        ) from exc


@router.post("", response_model=PlanItem, status_code=status.HTTP_201_CREATED)
def create_plan_endpoint(payload: PlanCreate) -> PlanItem:
    return create_plan(payload)


@router.get("", response_model=list[PlanItem])
def list_plans_endpoint(
    status_filter: Literal["active", "completed", "archived", "deleted"] | None = Query("active", alias="status"),
    limit: int = Query(50, ge=1, le=100),
) -> list[PlanItem]:
    return list_plans(status=status_filter, limit=limit)


@router.get("/{plan_id}", response_model=PlanItem)
def get_plan_endpoint(plan_id: UUID) -> PlanItem:
    try:
        return get_plan(plan_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{plan_id}/steps", response_model=PlanItem, status_code=status.HTTP_201_CREATED)
def add_plan_step_endpoint(plan_id: UUID, payload: PlanStepCreate) -> PlanItem:
    try:
        return add_plan_step(plan_id, payload)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{plan_id}/steps/{step_id}", response_model=PlanItem)
def update_plan_step_endpoint(plan_id: UUID, step_id: UUID, payload: PlanStepUpdate) -> PlanItem:
    try:
        return update_plan_step(plan_id, step_id, payload)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{plan_id}/steps/{step_id}/complete", response_model=PlanItem)
def complete_plan_step_endpoint(plan_id: UUID, step_id: UUID) -> PlanItem:
    try:
        return complete_plan_step(plan_id, step_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{plan_id}/complete", response_model=PlanItem)
def complete_plan_endpoint(plan_id: UUID) -> PlanItem:
    try:
        return complete_plan(plan_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{plan_id}/archive", response_model=PlanItem)
def archive_plan_endpoint(plan_id: UUID) -> PlanItem:
    try:
        return archive_plan(plan_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan_endpoint(plan_id: UUID) -> None:
    try:
        remove_plan(plan_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
