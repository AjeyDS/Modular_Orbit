"""Shared derived-data lifecycle helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.db import transaction
from app.rag import embed_documents
from app.rag.retrieval import vector_literal


def write_bucket_updates(
    conn: Connection,
    item: Mapping[str, Any],
    scored_connections: Sequence[Any],
    *,
    source: str = "connection_review",
    update_text: str | None = None,
    source_event: Mapping[str, Any] | None = None,
) -> int:
    """Write one pending Bucket Update per connected Story Bucket."""
    count = 0
    text = (update_text or f"{item['title']}: {item.get('description', '')}").strip()
    with conn.cursor() as cur:
        for scored in scored_connections:
            candidate = scored.candidate
            if candidate.target_type != "story_bucket":
                continue
            event = {
                "source": source,
                "connection_strength": scored.strength,
                **dict(source_event or {}),
            }
            cur.execute(
                """
                INSERT INTO bucket_updates (
                    story_bucket_id, life_item_id, update_text, source_event
                )
                SELECT %s, %s, %s, %s
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM bucket_updates
                    WHERE story_bucket_id = %s
                        AND life_item_id = %s
                        AND status = 'pending'
                        AND source_event ->> 'source' = %s
                )
                """,
                (
                    candidate.target_id,
                    item["id"],
                    text,
                    Jsonb(event),
                    candidate.target_id,
                    item["id"],
                    source,
                ),
            )
            count += cur.rowcount
    return count


def apply_retrieval_policy(life_item_id: UUID | str) -> str:
    """Create or verify Knowledge Chunks for a Life Item and update chunk_status."""
    with transaction() as conn:
        item = _get_item_with_module(conn, life_item_id)
        policy = item["retrieval_policy"] or {}
        if not policy.get("create_chunks", True) or policy.get("mode") == "none":
            _set_chunk_status(conn, life_item_id, "not_needed")
            return "not_needed"

        if _has_existing_chunks(conn, life_item_id):
            _set_chunk_status(conn, life_item_id, "complete")
            return "complete"

        content = _retrieval_text(item, policy)
        if not content:
            _set_chunk_status(conn, life_item_id, "not_needed")
            return "not_needed"

        try:
            chunks = _chunk_text(content)
            embeddings = embed_documents(chunks)
            with conn.cursor() as cur:
                for index, chunk in enumerate(chunks):
                    embedding = embeddings[index] if index < len(embeddings) else None
                    metadata = {
                        "chunk_index": index,
                        "total_chunks": len(chunks),
                        "module_id": item["module_id"],
                        "retrieval_mode": policy.get("mode", "summary"),
                        "embedding_status": "complete" if embedding else "not_available",
                    }
                    if embedding:
                        cur.execute(
                            """
                            INSERT INTO knowledge_chunks (
                                life_item_id, content, embedding, source_type, metadata
                            )
                            VALUES (%s, %s, CAST(%s AS vector), 'life_item_summary', %s)
                            """,
                            (life_item_id, chunk, vector_literal(embedding), Jsonb(metadata)),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO knowledge_chunks (life_item_id, content, source_type, metadata)
                            VALUES (%s, %s, 'life_item_summary', %s)
                            """,
                            (life_item_id, chunk, Jsonb(metadata)),
                        )
            _set_chunk_status(conn, life_item_id, "complete")
            return "complete"
        except Exception:
            _set_chunk_status(conn, life_item_id, "failed")
            return "failed"


def process_lifecycle_for_item(life_item_id: UUID | str, *, root=None) -> None:
    """Run v0 inline lifecycle processing after a durable Life Item write."""
    from app.lifecycle.connection_review import ConnectionReviewError, review_life_item

    try:
        review_life_item(life_item_id, root=root)
    except ConnectionReviewError:
        return
    apply_retrieval_policy(life_item_id)


def _get_item_with_module(conn: Connection, life_item_id: UUID | str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT li.*, m.id AS module_id, m.retrieval_policy
            FROM life_items li
            JOIN module_instances mi ON mi.id = li.module_instance_id
            JOIN modules m ON m.id = mi.module_id
            WHERE li.id = %s
            """,
            (life_item_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Unknown Life Item: {life_item_id}")
        return dict(row)


def _has_existing_chunks(conn: Connection, life_item_id: UUID | str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM knowledge_chunks WHERE life_item_id = %s LIMIT 1", (life_item_id,))
        return cur.fetchone() is not None


def _set_chunk_status(conn: Connection, life_item_id: UUID | str, status: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE life_items SET chunk_status = %s, updated_at = now() WHERE id = %s",
            (status, life_item_id),
        )


def _retrieval_text(item: Mapping[str, Any], policy: Mapping[str, Any]) -> str:
    values = []
    for source in policy.get("chunk_source") or ("title", "description", "payload"):
        value = _resolve_source(item, source)
        if value not in (None, "", [], {}):
            values.append(str(value))
    return "\n".join(values).strip()


def _resolve_source(item: Mapping[str, Any], source: str) -> Any:
    if source == "title":
        return item.get("title")
    if source == "description":
        return item.get("description")
    if source == "payload":
        return item.get("payload")
    if source.startswith("payload."):
        value: Any = item.get("payload") or {}
        for part in source.removeprefix("payload.").split("."):
            if not isinstance(value, Mapping):
                return None
            value = value.get(part)
        return value
    return None


def _chunk_text(content: str, *, max_chars: int = 1400) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in content.split("\n\n") if paragraph.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs or [content.strip()]:
        if len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}".strip()
        else:
            if current:
                chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return chunks[:20]
