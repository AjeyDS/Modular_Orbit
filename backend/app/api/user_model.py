"""HTTP API for editable User Model Story Buckets."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.user_model import (
    StoryBucketItem,
    StoryBucketUpdate,
    capture_fact,
    create_goal,
    current_woven_doc,
    delete_goal,
    get_story_bucket_item,
    list_goals,
    list_recent_facts,
    list_story_bucket_items,
    promote_goal,
    schedule_weave_if_needed,
    update_goal,
    update_story_bucket_item,
    weave_user_model,
)


GoalHorizon = Literal["short_term", "long_term"]


class GoalItem(BaseModel):
    goal_id: str
    title: str
    body: str
    status: Literal["active", "tentative"]
    horizon: GoalHorizon
    target_date: date | None = None
    target_note: str | None = None


GoalStatus = Literal["active", "tentative"]


class GoalCreate(BaseModel):
    title: str = Field(min_length=1)
    body: str = ""
    status: GoalStatus = "tentative"
    horizon: GoalHorizon = "long_term"
    target_date: date | None = None
    target_note: str | None = None


class GoalUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    status: GoalStatus | None = None
    horizon: GoalHorizon | None = None
    target_date: date | None = None
    target_note: str | None = None


class WovenDocResponse(BaseModel):
    version: int
    content: str
    fact_count_at_weave: int
    woven_at: datetime


class FactResponse(BaseModel):
    id: UUID
    source: str
    text: str
    salience: str
    woven: bool
    created_at: datetime


class NoteCreate(BaseModel):
    text: str = Field(min_length=1)


router = APIRouter(prefix="/user-model", tags=["user-model"])


@router.get("/doc", response_model=WovenDocResponse)
def get_woven_doc_endpoint() -> Response | WovenDocResponse:
    doc = current_woven_doc()
    if doc is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return WovenDocResponse(**doc)


@router.post("/reweave", response_model=WovenDocResponse)
def reweave_endpoint() -> Response | WovenDocResponse:
    doc = weave_user_model()
    if doc is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return WovenDocResponse(**doc)


@router.get("/facts", response_model=list[FactResponse])
def list_facts_endpoint(limit: int = Query(20, ge=1, le=100)) -> list[FactResponse]:
    return [FactResponse(**fact) for fact in list_recent_facts(limit)]


@router.post("/notes", response_model=FactResponse, status_code=status.HTTP_201_CREATED)
def create_note_endpoint(payload: NoteCreate, background_tasks: BackgroundTasks) -> FactResponse:
    fact = capture_fact(source="manual", text=payload.text, salience="high")
    schedule_weave_if_needed(background_tasks)
    return FactResponse(**fact)


@router.get("/buckets", response_model=list[StoryBucketItem])
def list_buckets_endpoint() -> list[StoryBucketItem]:
    return list_story_bucket_items()


@router.get("/buckets/{bucket_id}", response_model=StoryBucketItem)
def get_bucket_endpoint(bucket_id: UUID) -> StoryBucketItem:
    try:
        return get_story_bucket_item(bucket_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/buckets/{bucket_id}", response_model=StoryBucketItem)
def update_bucket_endpoint(bucket_id: UUID, payload: StoryBucketUpdate) -> StoryBucketItem:
    try:
        return update_story_bucket_item(bucket_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _goal_item(entry) -> GoalItem:
    return GoalItem(
        goal_id=entry.goal_id,
        title=entry.title,
        body=entry.body,
        status=entry.status,
        horizon=entry.horizon,
        target_date=entry.target_date,
        target_note=entry.target_note,
    )


@router.get("/goals", response_model=list[GoalItem])
def list_goals_endpoint() -> list[GoalItem]:
    return [_goal_item(goal) for goal in list_goals()]


@router.post("/goals", response_model=GoalItem, status_code=status.HTTP_201_CREATED)
def create_goal_endpoint(payload: GoalCreate) -> GoalItem:
    goal = create_goal(
        title=payload.title,
        body=payload.body,
        status=payload.status,
        horizon=payload.horizon,
        target_date=payload.target_date,
        target_note=payload.target_note,
    )
    return _goal_item(goal)


@router.patch("/goals/{goal_id}", response_model=GoalItem)
def update_goal_endpoint(goal_id: str, payload: GoalUpdate) -> GoalItem:
    try:
        kwargs: dict = {}
        if payload.title is not None:
            kwargs["title"] = payload.title
        if payload.body is not None:
            kwargs["body"] = payload.body
        if payload.status is not None:
            kwargs["status"] = payload.status
        if payload.horizon is not None:
            kwargs["horizon"] = payload.horizon
        if "target_date" in payload.model_fields_set:
            kwargs["target_date"] = payload.target_date
        if "target_note" in payload.model_fields_set:
            kwargs["target_note"] = payload.target_note
        goal = update_goal(goal_id, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _goal_item(goal)


@router.post("/goals/{goal_id}/promote", response_model=GoalItem)
def promote_goal_endpoint(goal_id: str) -> GoalItem:
    try:
        goal = promote_goal(goal_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _goal_item(goal)


@router.delete("/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal_endpoint(goal_id: str) -> Response:
    try:
        delete_goal(goal_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
