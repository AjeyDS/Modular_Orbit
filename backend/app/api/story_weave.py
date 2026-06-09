"""HTTP API for manual Story Weave runs."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.lifecycle.story_weave import StoryWeaveError, StoryWeaveResult, weave_all_story_buckets, weave_story_bucket


class StoryWeaveRunResponse(BaseModel):
    results: list[StoryWeaveResult]


router = APIRouter(prefix="/story-weave", tags=["story-weave"])


@router.post("/buckets/{story_bucket_id}", response_model=StoryWeaveResult)
def weave_bucket_endpoint(
    story_bucket_id: UUID,
    force: bool = Query(False),
) -> StoryWeaveResult:
    try:
        return weave_story_bucket(story_bucket_id, force=force)
    except StoryWeaveError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/run", response_model=StoryWeaveRunResponse)
def weave_all_endpoint(force: bool = Query(False)) -> StoryWeaveRunResponse:
    return StoryWeaveRunResponse(results=weave_all_story_buckets(force=force))
