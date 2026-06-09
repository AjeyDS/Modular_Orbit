"""Backfill embeddings for existing Knowledge Chunks."""

from __future__ import annotations

import argparse

from psycopg.types.json import Jsonb

from app.db import transaction
from app.rag.retrieval import embed_documents, vector_literal


def backfill_missing_embeddings(*, limit: int = 100) -> int:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, content
                FROM knowledge_chunks
                WHERE embedding IS NULL
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    if not rows:
        return 0

    embeddings = embed_documents([row["content"] for row in rows])
    updated = 0
    with transaction() as conn:
        with conn.cursor() as cur:
            for row, embedding in zip(rows, embeddings, strict=False):
                if not embedding:
                    continue
                cur.execute(
                    """
                    UPDATE knowledge_chunks
                    SET embedding = CAST(%s AS vector),
                        metadata = metadata || %s,
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        vector_literal(embedding),
                        Jsonb({"embedding_status": "complete"}),
                        row["id"],
                    ),
                )
                updated += cur.rowcount
    return updated


def embedding_status() -> dict[str, int]:
    """Return a small diagnostic summary for Knowledge Chunk embeddings."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_chunks,
                    COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS embedded_chunks,
                    COUNT(*) FILTER (WHERE embedding IS NULL) AS missing_embeddings
                FROM knowledge_chunks
                """
            )
            row = cur.fetchone()
    return {
        "total_chunks": int(row["total_chunks"] or 0),
        "embedded_chunks": int(row["embedded_chunks"] or 0),
        "missing_embeddings": int(row["missing_embeddings"] or 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill missing Knowledge Chunk embeddings.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if args.status:
        status = embedding_status()
        print(
            "Knowledge Chunk embeddings: "
            f"{status['embedded_chunks']}/{status['total_chunks']} embedded, "
            f"{status['missing_embeddings']} missing."
        )
        return
    updated = backfill_missing_embeddings(limit=args.limit)
    print(f"Backfilled {updated} chunk embeddings.")


if __name__ == "__main__":
    main()
