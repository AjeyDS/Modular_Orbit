"""HTTP API for the Logs module."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.lifecycle import LifeItemError
from app.modules.logs import LogCreate, LogItem, archive_log, create_log, list_logs, remove_log


router = APIRouter(prefix="/modules/logs", tags=["logs"])


@router.post("", response_model=LogItem, status_code=status.HTTP_201_CREATED)
def create_log_endpoint(payload: LogCreate) -> LogItem:
    return create_log(payload)


@router.get("", response_model=list[LogItem])
def list_logs_endpoint(
    status_filter: Literal["active"] | None = Query("active", alias="status"),
    limit: int = Query(50, ge=1, le=100),
) -> list[LogItem]:
    return list_logs(status=status_filter, limit=limit)


@router.post("/{log_id}/archive", response_model=LogItem)
def archive_log_endpoint(log_id: UUID) -> LogItem:
    try:
        return archive_log(log_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_log_endpoint(log_id: UUID) -> Response:
    try:
        remove_log(log_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
