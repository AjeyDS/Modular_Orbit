"""HTTP API for the Logs module."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, status

from app.modules.logs import LogCreate, LogItem, create_log, list_logs


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
