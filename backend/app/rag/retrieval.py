"""Embedding and retrieval utilities for Knowledge Chunks."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.db import transaction
from app.llm import LLMUnavailable, embed_content


@dataclass
class RetrievedChunk:
    id: str
    life_item_id: str
    title: str
    content: str
    source_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
    distance: float = 1.0
    score: float = 0.0
    retrieval_mode: str = "text"


def embed_documents(chunks: list[str]) -> list[list[float] | None]:
    """Embed document chunks, returning None for all chunks if embeddings fail."""
    if not chunks:
        return []
    try:
        embeddings = embed_content(chunks, task_type="retrieval_document")
    except (LLMUnavailable, Exception):
        return [None for _ in chunks]
    if not isinstance(embeddings, list):
        return [None for _ in chunks]

    normalized: list[list[float] | None] = []
    for embedding in embeddings:
        if isinstance(embedding, list) and embedding:
            normalized.append([float(value) for value in embedding])
        else:
            normalized.append(None)

    while len(normalized) < len(chunks):
        normalized.append(None)
    return normalized[: len(chunks)]


def retrieve_chunks(query: str, *, limit: int = 4) -> list[RetrievedChunk]:
    """Retrieve Knowledge Chunks with vector search, falling back to text search."""
    if not query.strip():
        return []
    try:
        query_embedding = embed_content(query, task_type="retrieval_query")
        if not isinstance(query_embedding, list) or not query_embedding:
            raise LLMUnavailable("Empty query embedding")
        rows = _search_vector([float(value) for value in query_embedding], limit=limit)
        if rows:
            return [_row_to_chunk(row, retrieval_mode="vector") for row in rows]
    except (LLMUnavailable, Exception):
        pass
    return [_row_to_chunk(row, retrieval_mode="text") for row in _search_text(query, limit=limit)]


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in values) + "]"


def _search_vector(query_embedding: list[float], *, limit: int) -> list[dict[str, Any]]:
    embedding = vector_literal(query_embedding)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH raw_matches AS (
                    SELECT
                        kc.id,
                        kc.life_item_id,
                        kc.content,
                        kc.source_type,
                        kc.metadata,
                        kc.created_at,
                        li.title,
                        kc.embedding <=> CAST(%s AS vector) AS distance
                    FROM knowledge_chunks kc
                    JOIN life_items li ON li.id = kc.life_item_id
                    WHERE kc.embedding IS NOT NULL
                        AND li.lifecycle_status <> 'deleted'
                    ORDER BY kc.embedding <=> CAST(%s AS vector)
                    LIMIT %s
                )
                SELECT
                    *,
                    (
                        GREATEST(1.0 - distance, 0.0)
                        + (EXP(-GREATEST(EXTRACT(EPOCH FROM (now() - created_at)), 0) / 2592000.0) * 0.08)
                    ) AS score
                FROM raw_matches
                ORDER BY score DESC
                LIMIT %s
                """,
                (embedding, embedding, max(limit * 4, limit), limit),
            )
            return list(cur.fetchall())


def _search_text(query: str, *, limit: int) -> list[dict[str, Any]]:
    normalized = " ".join(query.split()).strip()
    tokens = _tokens(normalized)
    with transaction() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    WITH ranked AS (
                        SELECT
                            kc.id,
                            kc.life_item_id,
                            kc.content,
                            kc.source_type,
                            kc.metadata,
                            kc.created_at,
                            li.title,
                            ts_rank_cd(
                                to_tsvector(
                                    'simple',
                                    li.title || ' ' || kc.source_type || ' ' || kc.metadata::text || ' ' || kc.content
                                ),
                                websearch_to_tsquery('simple', %s)
                            ) AS text_rank
                        FROM knowledge_chunks kc
                        JOIN life_items li ON li.id = kc.life_item_id
                        WHERE li.lifecycle_status <> 'deleted'
                            AND to_tsvector(
                                'simple',
                                li.title || ' ' || kc.source_type || ' ' || kc.metadata::text || ' ' || kc.content
                            ) @@ websearch_to_tsquery('simple', %s)
                        ORDER BY text_rank DESC, kc.created_at DESC
                        LIMIT %s
                    )
                    SELECT *, GREATEST(text_rank, 0.01) AS score, 1.0 - GREATEST(text_rank, 0.0) AS distance
                    FROM ranked
                    ORDER BY score DESC
                    LIMIT %s
                    """,
                    (normalized, normalized, max(limit * 4, limit), limit),
                )
                rows = list(cur.fetchall())
                if rows:
                    return rows
            except Exception:
                conn.rollback()

            cur.execute(
                """
                SELECT
                    kc.id,
                    kc.life_item_id,
                    kc.content,
                    kc.source_type,
                    kc.metadata,
                    kc.created_at,
                    li.title,
                    1.0 AS distance,
                    0.0 AS score
                FROM knowledge_chunks kc
                JOIN life_items li ON li.id = kc.life_item_id
                WHERE li.lifecycle_status <> 'deleted'
                ORDER BY kc.created_at DESC
                LIMIT %s
                """,
                (max(limit * 10, 40),),
            )
            rows = list(cur.fetchall())

    ranked = sorted(
        rows,
        key=lambda row: (
            _overlap(tokens, f"{row['title']} {row['source_type']} {row['metadata']} {row['content']}"),
            row["created_at"],
        ),
        reverse=True,
    )
    return ranked[:limit]


def _row_to_chunk(row: dict[str, Any], *, retrieval_mode: str) -> RetrievedChunk:
    return RetrievedChunk(
        id=str(row["id"]),
        life_item_id=str(row["life_item_id"]),
        title=row["title"],
        content=row["content"],
        source_type=row["source_type"],
        metadata=row["metadata"] or {},
        distance=float(row.get("distance", 1.0)),
        score=float(row.get("score", 0.0)),
        retrieval_mode=retrieval_mode,
    )


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]+", text.lower()) if len(token) > 2}


def _overlap(left: set[str], text: str) -> int:
    if not left:
        return 0
    return len(left & _tokens(text))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    size = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(size))
    norm_a = math.sqrt(sum(a[i] * a[i] for i in range(size)))
    norm_b = math.sqrt(sum(b[i] * b[i] for i in range(size)))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
