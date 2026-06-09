"""HTTP API for editable User Model Story Buckets."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.user_model import (
    StoryBucketItem,
    StoryBucketUpdate,
    create_goal,
    delete_goal,
    get_story_bucket_item,
    list_goals,
    list_story_bucket_items,
    promote_goal,
    update_goal,
    update_story_bucket_item,
)


class GoalItem(BaseModel):
    goal_id: str
    title: str
    body: str
    status: Literal["active", "tentative"]
    horizon: str
    target_date: date | None = None
    target_note: str | None = None


class GoalCreate(BaseModel):
    title: str = Field(min_length=1)
    body: str = ""
    horizon: str = "long_term"
    target_date: date | None = None
    target_note: str | None = None


class GoalUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    horizon: str | None = None
    target_date: date | None = None
    target_note: str | None = None


router = APIRouter(prefix="/user-model", tags=["user-model"])


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
        horizon=payload.horizon,
        target_date=payload.target_date,
        target_note=payload.target_note,
    )
    return _goal_item(goal)


@router.patch("/goals/{goal_id}", response_model=GoalItem)
def update_goal_endpoint(goal_id: str, payload: GoalUpdate) -> GoalItem:
    try:
        goal = update_goal(
            goal_id,
            title=payload.title,
            body=payload.body,
            horizon=payload.horizon,
            target_date=payload.target_date,
            target_note=payload.target_note,
        )
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
