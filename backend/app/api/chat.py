"""HTTP API for chat modes and Chat Actions."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from app.chat import (
    ChatMessageItem,
    ChatRequest,
    ChatResponse,
    ChatSessionItem,
    ConfirmCaptureProposalRequest,
    ConfirmCaptureProposalResponse,
    RenameChatSessionRequest,
    SessionNotFound,
    confirm_capture_proposal,
    delete_chat_session,
    list_chat_messages,
    list_chat_sessions,
    rename_chat_session,
    respond_to_chat,
    respond_to_chat_stream,
)


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/respond", response_model=ChatResponse)
def respond_to_chat_endpoint(payload: ChatRequest) -> ChatResponse:
    return respond_to_chat(payload)


@router.post("/respond/stream")
def respond_to_chat_stream_endpoint(payload: ChatRequest) -> StreamingResponse:
    def gen():
        for event in respond_to_chat_stream(payload):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/capture-proposals/confirm", response_model=ConfirmCaptureProposalResponse)
def confirm_capture_proposal_endpoint(
    payload: ConfirmCaptureProposalRequest,
) -> ConfirmCaptureProposalResponse:
    try:
        return confirm_capture_proposal(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/sessions", response_model=list[ChatSessionItem])
def list_chat_sessions_endpoint() -> list[ChatSessionItem]:
    return list_chat_sessions()


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageItem])
def list_chat_messages_endpoint(session_id: str) -> list[ChatMessageItem]:
    try:
        return list_chat_messages(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/sessions/{session_id}", response_model=ChatSessionItem)
def rename_chat_session_endpoint(
    session_id: str,
    payload: RenameChatSessionRequest,
) -> ChatSessionItem:
    try:
        return rename_chat_session(session_id, payload.title)
    except SessionNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat_session_endpoint(session_id: str) -> Response:
    try:
        delete_chat_session(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
