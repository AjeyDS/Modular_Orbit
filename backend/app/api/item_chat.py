"""HTTP API for Item Chat."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.chat import ItemChatRequest, ItemChatResponse, chat_with_item
from app.lifecycle import LifeItemError


router = APIRouter(prefix="/item-chat", tags=["item-chat"])


@router.post("/{life_item_id}", response_model=ItemChatResponse)
def item_chat_endpoint(life_item_id: UUID, payload: ItemChatRequest) -> ItemChatResponse:
    try:
        return chat_with_item(life_item_id, payload)
    except LifeItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
