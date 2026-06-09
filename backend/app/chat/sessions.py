"""Chat session and message persistence (history surface)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from app.chat.actions import CaptureProposalPreview, ChatMode
from app.db import transaction


TITLE_MAX = 60
TITLE_LENGTH_CAP = 200


class ChatSessionItem(BaseModel):
    id: str
    title: str | None
    message_count: int
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ChatMessageItem(BaseModel):
    id: UUID
    session_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    mode: ChatMode | None
    suggestions: list[CaptureProposalPreview] | None
    created_at: datetime


class RenameChatSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_LENGTH_CAP)


def list_chat_sessions() -> list[ChatSessionItem]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    s.id,
                    s.title,
                    s.created_at,
                    s.updated_at,
                    s.last_message_at,
                    COALESCE(counts.message_count, 0) AS message_count
                FROM chat_sessions s
                LEFT JOIN (
                    SELECT session_id, COUNT(*) AS message_count
                    FROM chat_messages
                    GROUP BY session_id
                ) counts ON counts.session_id = s.id
                WHERE s.last_message_at IS NOT NULL
                ORDER BY s.last_message_at DESC NULLS LAST
                """
            )
            rows = cur.fetchall()
    return [_row_to_session(row) for row in rows]


def list_chat_messages(session_id: str) -> list[ChatMessageItem]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM chat_sessions WHERE id = %s", (session_id,))
            if cur.fetchone() is None:
                raise SessionNotFound(session_id)
            cur.execute(
                """
                SELECT id, session_id, role, content, mode, suggestions, created_at
                FROM chat_messages
                WHERE session_id = %s
                ORDER BY created_at ASC, id ASC
                """,
                (session_id,),
            )
            rows = cur.fetchall()
    return [_row_to_message(row) for row in rows]


def rename_chat_session(session_id: str, title: str) -> ChatSessionItem:
    cleaned = title.strip()
    if not cleaned:
        raise ValueError("Title cannot be empty")
    cleaned = cleaned[:TITLE_LENGTH_CAP]
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE chat_sessions
                SET title = %s,
                    updated_at = now()
                WHERE id = %s
                RETURNING id
                """,
                (cleaned, session_id),
            )
            if cur.fetchone() is None:
                raise SessionNotFound(session_id)
            cur.execute(
                """
                SELECT
                    s.id,
                    s.title,
                    s.created_at,
                    s.updated_at,
                    s.last_message_at,
                    COALESCE(counts.message_count, 0) AS message_count
                FROM chat_sessions s
                LEFT JOIN (
                    SELECT session_id, COUNT(*) AS message_count
                    FROM chat_messages
                    GROUP BY session_id
                ) counts ON counts.session_id = s.id
                WHERE s.id = %s
                """,
                (session_id,),
            )
            row = cur.fetchone()
    return _row_to_session(row)


def delete_chat_session(session_id: str) -> None:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM chat_sessions WHERE id = %s RETURNING id",
                (session_id,),
            )
            if cur.fetchone() is None:
                raise SessionNotFound(session_id)


def truncate_for_title(message: str, *, limit: int = TITLE_MAX) -> str:
    cleaned = " ".join(message.strip().split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}…"


def upsert_session_for_message(
    conn: Connection,
    session_id: str,
    *,
    initial_title: str | None,
) -> None:
    """Ensure the chat_sessions row exists, set title on insert, bump last_message_at."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chat_sessions (id, title, last_message_at, updated_at)
            VALUES (%s, %s, now(), now())
            ON CONFLICT (id) DO UPDATE
            SET last_message_at = excluded.last_message_at,
                updated_at = excluded.updated_at,
                title = COALESCE(chat_sessions.title, excluded.title)
            """,
            (session_id, initial_title),
        )


def insert_chat_message(
    conn: Connection,
    *,
    session_id: str,
    role: Literal["user", "assistant", "system"],
    content: str,
    mode: ChatMode | None = None,
    suggestions: list[dict[str, Any]] | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chat_messages (session_id, role, content, mode, suggestions)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                session_id,
                role,
                content,
                mode,
                Jsonb(suggestions) if suggestions is not None else None,
            ),
        )
        cur.execute(
            """
            UPDATE chat_sessions
            SET last_message_at = now(),
                updated_at = now()
            WHERE id = %s
            """,
            (session_id,),
        )


class SessionNotFound(Exception):
    def __init__(self, session_id: str) -> None:
        super().__init__(f"Unknown chat session: {session_id}")
        self.session_id = session_id


def _row_to_session(row: dict[str, Any]) -> ChatSessionItem:
    return ChatSessionItem(
        id=row["id"],
        title=row["title"],
        message_count=row["message_count"],
        last_message_at=row["last_message_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_message(row: dict[str, Any]) -> ChatMessageItem:
    suggestions_raw = row["suggestions"]
    suggestions: list[CaptureProposalPreview] | None
    if suggestions_raw is None:
        suggestions = None
    else:
        suggestions = [CaptureProposalPreview.model_validate(item) for item in suggestions_raw]
    return ChatMessageItem(
        id=row["id"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        mode=row["mode"],
        suggestions=suggestions,
        created_at=row["created_at"],
    )
