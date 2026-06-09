"""Item Chat scoped to one Life Item plus one-hop Connections."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.db import transaction
from app.lifecycle import LifeItemError
from app.llm import LLMUnavailable, generate_text
from app.user_model import list_goals


class ConnectedContext(BaseModel):
    target_type: str
    target_id: str
    target_label: str
    connection_note: str
    strength: float
    content: str = ""


class DerivedChunkContext(BaseModel):
    id: UUID
    content: str
    metadata: dict[str, Any]


class ItemChatContext(BaseModel):
    life_item_id: UUID
    module_id: str
    module_name: str
    title: str
    description: str
    payload: dict[str, Any]
    lifecycle_status: str
    connection_status: str
    connections: list[ConnectedContext]
    derived_chunks: list[DerivedChunkContext]


class ItemChatRequest(BaseModel):
    message: str = Field(min_length=1)


class ItemChatAction(BaseModel):
    label: str
    target_mode: str
    reason: str


class ItemChatResponse(BaseModel):
    answer: str
    context: ItemChatContext
    needs_context_chat: bool = False
    suggested_action: ItemChatAction | None = None


BROAD_CONTEXT_MARKERS = (
    "all my",
    "across",
    "everything",
    "original plan",
    "whole picture",
    "entire",
    "compare with every",
    "other tasks",
    "all tasks",
    "all plans",
)


def chat_with_item(
    life_item_id: UUID | str,
    request: ItemChatRequest,
    *,
    root: Path | None = None,
) -> ItemChatResponse:
    """Answer one Item Chat turn from a bounded one-hop context packet."""
    context = build_item_chat_context(life_item_id, root=root)
    needs_context_chat = _needs_context_chat(request.message)

    if needs_context_chat:
        return ItemChatResponse(
            answer=(
                "This question likely needs broader context than this item's one-hop graph. "
                "Open it in Context Chat so Orbit can search beyond this single Life Item."
            ),
            context=context,
            needs_context_chat=True,
            suggested_action=ItemChatAction(
                label="Open in Context Chat",
                target_mode="context_chat",
                reason="The question asks for multi-hop or broad workspace context.",
            ),
        )

    return ItemChatResponse(
        answer=_generate_scoped_answer(request.message, context),
        context=context,
    )


def build_item_chat_context(life_item_id: UUID | str, *, root: Path | None = None) -> ItemChatContext:
    """Reload the current Life Item and one-hop connected context."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    li.*,
                    m.id AS module_id,
                    m.name AS module_name,
                    m.item_chat_enabled
                FROM life_items li
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE li.id = %s
                """,
                (life_item_id,),
            )
            item = cur.fetchone()
            if item is None:
                raise LifeItemError(f"Unknown Life Item: {life_item_id}")
            if not item["item_chat_enabled"]:
                raise LifeItemError(f"Item Chat is disabled for module: {item['module_id']}")

            connections = _get_item_connections(cur, life_item_id)
            chunks = _get_derived_chunks(cur, life_item_id)

    return ItemChatContext(
        life_item_id=item["id"],
        module_id=item["module_id"],
        module_name=item["module_name"],
        title=item["title"],
        description=item["description"],
        payload=item["payload"] or {},
        lifecycle_status=item["lifecycle_status"],
        connection_status=item["connection_status"],
        connections=[
            _hydrate_connection(connection, root=root)
            for connection in connections
        ],
        derived_chunks=chunks,
    )


def _get_item_connections(cur, life_item_id: UUID | str) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT target_type, target_id, target_label, connection_note, strength
        FROM item_connections
        WHERE source_life_item_id = %s
        ORDER BY strength DESC, created_at DESC
        """,
        (life_item_id,),
    )
    return [dict(row) for row in cur.fetchall()]


def _get_derived_chunks(cur, life_item_id: UUID | str) -> list[DerivedChunkContext]:
    cur.execute(
        """
        SELECT id, content, metadata
        FROM knowledge_chunks
        WHERE life_item_id = %s
        ORDER BY created_at DESC
        LIMIT 10
        """,
        (life_item_id,),
    )
    return [
        DerivedChunkContext(
            id=row["id"],
            content=row["content"],
            metadata=row["metadata"] or {},
        )
        for row in cur.fetchall()
    ]


def _hydrate_connection(connection: dict[str, Any], *, root: Path | None) -> ConnectedContext:
    target_type = connection["target_type"]
    content = ""

    if target_type == "story_bucket":
        content = _get_connected_bucket_text(connection["target_id"])
    elif target_type in {"active_goal", "tentative_goal"}:
        content = _get_connected_goal(connection["target_id"], root=root)
    elif target_type == "life_item":
        content = _get_connected_item(connection["target_id"])
    elif target_type == "document":
        content = f"Connected document: {connection['target_label']}"

    return ConnectedContext(
        target_type=target_type,
        target_id=connection["target_id"],
        target_label=connection["target_label"],
        connection_note=connection["connection_note"],
        strength=connection["strength"],
        content=content,
    )


def _get_connected_bucket_text(bucket_id: str) -> str:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT file_path FROM story_buckets WHERE id = %s", (bucket_id,))
            row = cur.fetchone()
            if row is None:
                return ""
            path = Path(row["file_path"])
            return path.read_text(encoding="utf-8") if path.exists() else ""


def _get_connected_goal(goal_id: str, *, root: Path | None) -> str:
    for goal in list_goals():
        if goal.goal_id == goal_id:
            return f"{goal.title}\n\n{goal.body}".strip()
    return ""


def _get_connected_item(life_item_id: str) -> str:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT title, description, payload
                FROM life_items
                WHERE id = %s
                """,
                (life_item_id,),
            )
            row = cur.fetchone()
            if row is None:
                return ""
            return f"{row['title']}\n\n{row['description']}\n\n{row['payload']}".strip()


def _needs_context_chat(message: str) -> bool:
    normalized = " ".join(message.lower().split())
    return any(marker in normalized for marker in BROAD_CONTEXT_MARKERS)


def _compose_scoped_answer(message: str, context: ItemChatContext) -> str:
    pieces = [
        f"This is scoped to {context.module_name} item '{context.title}'.",
    ]
    if context.description:
        pieces.append(f"Item context: {context.description}")

    if context.connection_status != "complete":
        pieces.append(
            f"Connection Review is {context.connection_status}, so connected context may still be incomplete."
        )
    elif context.connections:
        labels = ", ".join(connection.target_label for connection in context.connections[:3])
        pieces.append(f"One-hop connections in scope: {labels}.")
    else:
        pieces.append("There are no one-hop Connections yet.")

    if context.derived_chunks:
        pieces.append(f"Derived chunks available: {len(context.derived_chunks)}.")

    pieces.append(f"Your question was: {message}")
    return " ".join(pieces)


def _generate_scoped_answer(message: str, context: ItemChatContext) -> str:
    system = (
        "You are Orbit's Item Chat. Answer only from the anchored Life Item, its "
        "one-hop Connections, connected Story Buckets or Goals, and derived chunks. "
        "If Connection Review is pending, say connected context may be incomplete. "
        "Do not silently expand to whole-workspace context."
    )
    prompt = f"""
User question:
{message}

Anchored Life Item:
- Module: {context.module_name} ({context.module_id})
- Title: {context.title}
- Description: {context.description}
- Lifecycle status: {context.lifecycle_status}
- Connection status: {context.connection_status}
- Payload: {context.payload}

One-hop Connections:
{_render_connections(context.connections)}

Derived Knowledge Chunks:
{_render_chunks(context.derived_chunks)}

Write a concise, useful answer scoped to this item.
""".strip()
    try:
        return generate_text(prompt, system=system, temperature=0.45, max_output_tokens=1000)
    except (LLMUnavailable, Exception):
        return _compose_scoped_answer(message, context)


def _render_connections(connections: list[ConnectedContext]) -> str:
    if not connections:
        return "None"
    return "\n".join(
        f"- {connection.target_type} {connection.target_label} ({connection.strength}): "
        f"{connection.connection_note}\n{connection.content[:900]}"
        for connection in connections[:8]
    )


def _render_chunks(chunks: list[DerivedChunkContext]) -> str:
    if not chunks:
        return "None"
    return "\n".join(f"- {chunk.content[:900]}" for chunk in chunks[:6])
