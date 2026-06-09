"""Connection Review lifecycle step.

This is a deterministic v0 implementation of the orchestrated workflow. The
model-facing call structure can replace the scoring function later without
changing the database contract or status semantics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import Connection
from app.db import transaction
from app.lifecycle.derived import write_bucket_updates
from app.user_model import list_goals


class ConnectionReviewError(RuntimeError):
    """Raised when Connection Review fails after marking the Life Item failed."""


@dataclass(frozen=True)
class ConnectionCandidate:
    target_type: str
    target_id: str
    target_label: str
    text: str


@dataclass(frozen=True)
class ScoredConnection:
    candidate: ConnectionCandidate
    strength: float
    connection_note: str


@dataclass(frozen=True)
class ConnectionReviewResult:
    life_item_id: UUID
    connections: tuple[ScoredConnection, ...]
    should_create_chunks: bool
    should_create_bucket_update: bool


CANDIDATE_BOUNDS = {
    "story_bucket": 5,
    "goal": 5,
    "life_item": 5,
    "module_instance": 3,
}
CONNECTION_THRESHOLD = 0.18
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "with",
}


def review_life_item(life_item_id: UUID | str, *, root: Path | None = None) -> ConnectionReviewResult:
    """Run Connection Review for one durable Life Item."""
    try:
        with transaction() as conn:
            item = _get_life_item_with_module(conn, life_item_id)
            item_text = _item_text(item)
            candidates = _route_candidates(conn, item, item_text, root=root)
            scored = tuple(
                scored
                for scored in (_score_candidate(item_text, candidate) for candidate in candidates)
                if scored.strength >= CONNECTION_THRESHOLD
            )

            _persist_connections(conn, item["id"], scored)

            should_create_chunks = _should_create_chunks(item, item_text)
            should_create_bucket_update = _should_create_bucket_update(item, scored)
            if should_create_bucket_update:
                write_bucket_updates(conn, item, scored)

            _update_review_statuses(
                conn,
                item["id"],
                connection_status="complete",
                chunk_status="pending" if should_create_chunks else "not_needed",
                bucket_update_status="complete" if should_create_bucket_update else "not_needed",
            )

            return ConnectionReviewResult(
                life_item_id=item["id"],
                connections=scored,
                should_create_chunks=should_create_chunks,
                should_create_bucket_update=should_create_bucket_update,
            )
    except Exception as exc:
        _mark_connection_review_failed(life_item_id)
        raise ConnectionReviewError(f"Connection Review failed for Life Item {life_item_id}") from exc


def run_pending_connection_reviews(limit: int = 10, *, root: Path | None = None) -> list[ConnectionReviewResult]:
    """Process pending reviews in FIFO order."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM life_items
                WHERE connection_status = 'pending'
                    AND lifecycle_status <> 'deleted'
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (limit,),
            )
            life_item_ids = [row["id"] for row in cur.fetchall()]

    return [review_life_item(life_item_id, root=root) for life_item_id in life_item_ids]


def reset_connection_review(life_item_id: UUID | str) -> dict[str, Any]:
    """Move a failed review back to pending for retry."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE life_items
                SET connection_status = 'pending', updated_at = now()
                WHERE id = %s AND connection_status = 'failed'
                RETURNING *
                """,
                (life_item_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ConnectionReviewError(f"Life Item is not failed or does not exist: {life_item_id}")
            return dict(row)


def _get_life_item_with_module(conn: Connection, life_item_id: UUID | str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                li.*,
                m.id AS module_id,
                m.name AS module_name,
                m.retrieval_policy
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


def _route_candidates(
    conn: Connection,
    item: dict[str, Any],
    item_text: str,
    *,
    root: Path | None,
) -> tuple[ConnectionCandidate, ...]:
    candidates = (
        _candidate_story_buckets(conn)
        + _candidate_goals(root)
        + _candidate_life_items(conn, item["id"])
        + _candidate_module_instances(conn, item["module_instance_id"])
    )
    grouped: dict[str, list[ConnectionCandidate]] = {
        "story_bucket": [],
        "goal": [],
        "life_item": [],
        "module_instance": [],
    }

    for candidate in candidates:
        group = "goal" if candidate.target_type in {"active_goal", "tentative_goal"} else candidate.target_type
        grouped[group].append(candidate)

    selected: list[ConnectionCandidate] = []
    for group, group_candidates in grouped.items():
        selected.extend(
            sorted(
                group_candidates,
                key=lambda candidate: _lexical_score(item_text, candidate.text),
                reverse=True,
            )[: CANDIDATE_BOUNDS[group]]
        )

    return tuple(selected)


def _candidate_story_buckets(conn: Connection) -> list[ConnectionCandidate]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, file_path, display_name, description
            FROM story_buckets
            WHERE status = 'active'
            ORDER BY display_name
            """
        )
        rows = cur.fetchall()

    candidates = []
    for row in rows:
        file_text = _read_text_if_exists(Path(row["file_path"]))
        candidates.append(
            ConnectionCandidate(
                target_type="story_bucket",
                target_id=str(row["id"]),
                target_label=row["display_name"],
                text=f"{row['display_name']} {row['description']} {file_text}",
            )
        )
    return candidates


def _candidate_goals(root: Path | None) -> list[ConnectionCandidate]:
    candidates = []
    for goal in list_goals():
        target_type = "active_goal" if goal.status == "active" else "tentative_goal"
        candidates.append(
            ConnectionCandidate(
                target_type=target_type,
                target_id=goal.goal_id,
                target_label=goal.title,
                text=f"{goal.title} {goal.body}",
            )
        )
    return candidates


def _candidate_life_items(conn: Connection, life_item_id: UUID) -> list[ConnectionCandidate]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, title, description, payload
            FROM life_items
            WHERE id <> %s
                AND lifecycle_status <> 'deleted'
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (life_item_id,),
        )
        rows = cur.fetchall()

    return [
        ConnectionCandidate(
            target_type="life_item",
            target_id=str(row["id"]),
            target_label=row["title"],
            text=f"{row['title']} {row['description']} {row['payload']}",
        )
        for row in rows
    ]


def _candidate_module_instances(conn: Connection, module_instance_id: UUID) -> list[ConnectionCandidate]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT mi.id, mi.display_name, m.name, m.description
            FROM module_instances mi
            JOIN modules m ON m.id = mi.module_id
            WHERE mi.id <> %s
                AND mi.enabled = TRUE
            ORDER BY mi.created_at DESC
            LIMIT 50
            """,
            (module_instance_id,),
        )
        rows = cur.fetchall()

    return [
        ConnectionCandidate(
            target_type="module_instance",
            target_id=str(row["id"]),
            target_label=row["display_name"],
            text=f"{row['display_name']} {row['name']} {row['description']}",
        )
        for row in rows
    ]


def _score_candidate(item_text: str, candidate: ConnectionCandidate) -> ScoredConnection:
    strength = _lexical_score(item_text, candidate.text)
    note = (
        f"Connects now because '{candidate.target_label}' shares topical language "
        "with this Life Item."
    )
    return ScoredConnection(candidate=candidate, strength=strength, connection_note=note)


def _persist_connections(
    conn: Connection,
    life_item_id: UUID,
    scored_connections: tuple[ScoredConnection, ...],
) -> None:
    with conn.cursor() as cur:
        for scored in scored_connections:
            candidate = scored.candidate
            cur.execute(
                """
                INSERT INTO item_connections (
                    source_life_item_id, target_type, target_id, target_label,
                    strength, connection_note
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_life_item_id, target_type, target_id)
                DO UPDATE SET
                    target_label = EXCLUDED.target_label,
                    strength = EXCLUDED.strength,
                    connection_note = EXCLUDED.connection_note,
                    review_source = 'connection_review',
                    created_at = now()
                """,
                (
                    life_item_id,
                    candidate.target_type,
                    candidate.target_id,
                    candidate.target_label,
                    scored.strength,
                    scored.connection_note,
                ),
            )


def _update_review_statuses(
    conn: Connection,
    life_item_id: UUID,
    *,
    connection_status: str,
    chunk_status: str,
    bucket_update_status: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE life_items
            SET connection_status = %s,
                chunk_status = %s,
                bucket_update_status = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (connection_status, chunk_status, bucket_update_status, life_item_id),
        )


def _mark_connection_review_failed(life_item_id: UUID | str) -> None:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE life_items
                SET connection_status = 'failed', updated_at = now()
                WHERE id = %s
                """,
                (life_item_id,),
            )


def _should_create_chunks(item: dict[str, Any], item_text: str) -> bool:
    retrieval_policy = item["retrieval_policy"]
    return bool(retrieval_policy.get("create_chunks", True) and len(_tokens(item_text)) >= 5)


def _should_create_bucket_update(
    item: dict[str, Any],
    scored_connections: tuple[ScoredConnection, ...],
) -> bool:
    retrieval_policy = item["retrieval_policy"]
    return bool(
        retrieval_policy.get("create_bucket_updates", True)
        and any(connection.candidate.target_type == "story_bucket" for connection in scored_connections)
    )


def _item_text(item: dict[str, Any]) -> str:
    return f"{item['title']} {item['description']} {item['payload']}"


def _lexical_score(left: str, right: str) -> float:
    left_tokens = set(_tokens(left))
    right_tokens = set(_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0

    overlap = left_tokens & right_tokens
    return round(len(overlap) / max(len(left_tokens), 1), 4)


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in STOPWORDS
    ]


def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")
