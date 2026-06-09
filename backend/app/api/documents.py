"""HTTP API for the Documents module."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from app.lifecycle import LifeItemError
from app.modules.documents import (
    DocumentAnnotation,
    DocumentCreate,
    DocumentItem,
    DocumentNameConflictError,
    DocumentParseError,
    DocumentRename,
    create_document,
    create_document_from_upload,
    get_document,
    list_documents,
    update_document_annotation,
    rename_document,
)


router = APIRouter(prefix="/modules/documents", tags=["documents"])


@router.post("", response_model=DocumentItem, status_code=status.HTTP_201_CREATED)
def create_document_endpoint(payload: DocumentCreate) -> DocumentItem:
    try:
        return create_document(payload)
    except DocumentNameConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"conflicting_name": str(exc)},
        ) from exc


@router.post("/upload", response_model=DocumentItem, status_code=status.HTTP_201_CREATED)
async def upload_document_endpoint(file: UploadFile = File(...)) -> DocumentItem:
    filename = file.filename or "uploaded_document"
    data = await file.read()
    try:
        return create_document_from_upload(
            original_name=filename,
            data=data,
            mime_type=file.content_type,
        )
    except DocumentNameConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"conflicting_name": str(exc)},
        ) from exc
    except DocumentParseError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc


@router.get("", response_model=list[DocumentItem])
def list_documents_endpoint(
    status_filter: Literal["active"] | None = Query("active", alias="status"),
    limit: int = Query(50, ge=1, le=100),
) -> list[DocumentItem]:
    return list_documents(status=status_filter, limit=limit)


@router.get("/{document_id}", response_model=DocumentItem)
def get_document_endpoint(document_id: UUID) -> DocumentItem:
    try:
        return get_document(document_id)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{document_id}/unique-name", response_model=DocumentItem)
def rename_document_endpoint(document_id: UUID, payload: DocumentRename) -> DocumentItem:
    try:
        return rename_document(document_id, payload.unique_name)
    except DocumentNameConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"conflicting_name": str(exc)},
        ) from exc
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{document_id}/annotation", response_model=DocumentItem)
def update_document_annotation_endpoint(document_id: UUID, payload: DocumentAnnotation) -> DocumentItem:
    try:
        return update_document_annotation(document_id, payload)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
