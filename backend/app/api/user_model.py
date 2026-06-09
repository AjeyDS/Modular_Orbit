"""HTTP API for editable User Model Story Buckets."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.user_model import (
    StoryBucketItem,
    StoryBucketUpdate,
    get_story_bucket_item,
    list_story_bucket_items,
    update_story_bucket_item,
)


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
