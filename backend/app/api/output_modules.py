"""HTTP API for output-heavy modules."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.lifecycle import LifeItemError
from app.modules.output import (
    AcceptGeneratedOutputResponse,
    GenerateOutputRequest,
    GeneratedOutputItem,
    GeneratedOutputStatus,
    OutputModuleId,
    accept_generated_output,
    generate_output,
    get_generated_output,
    list_generated_outputs,
    reject_generated_output,
    retry_generated_output,
)


router = APIRouter(prefix="/modules/{module_id}/outputs", tags=["output-modules"])


@router.post("/generate", response_model=GeneratedOutputItem, status_code=status.HTTP_201_CREATED)
def generate_output_endpoint(module_id: OutputModuleId, payload: GenerateOutputRequest) -> GeneratedOutputItem:
    return generate_output(module_id, payload)


@router.post("/{output_id}/retry", response_model=GeneratedOutputItem, status_code=status.HTTP_201_CREATED)
def retry_output_endpoint(module_id: OutputModuleId, output_id: UUID) -> GeneratedOutputItem:
    try:
        original = get_generated_output(output_id)
        if original.module_id != module_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Output belongs to another module")
        return retry_generated_output(output_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{output_id}/accept", response_model=AcceptGeneratedOutputResponse)
def accept_output_endpoint(module_id: OutputModuleId, output_id: UUID) -> AcceptGeneratedOutputResponse:
    try:
        existing = get_generated_output(output_id)
        if existing.module_id != module_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Output belongs to another module")
        accepted = accept_generated_output(output_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return accepted


@router.post("/{output_id}/reject", response_model=GeneratedOutputItem)
def reject_output_endpoint(module_id: OutputModuleId, output_id: UUID) -> GeneratedOutputItem:
    try:
        existing = get_generated_output(output_id)
        if existing.module_id != module_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Output belongs to another module")
        rejected = reject_generated_output(output_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return rejected


@router.get("", response_model=list[GeneratedOutputItem])
def list_outputs_endpoint(
    module_id: OutputModuleId,
    status_filter: GeneratedOutputStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=100),
) -> list[GeneratedOutputItem]:
    return list_generated_outputs(module_id, status=status_filter, limit=limit)
