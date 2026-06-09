"""Stable Story Bucket identity with markdown content persisted in Postgres."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from psycopg import Connection
from pydantic import BaseModel, Field

from app.db import connect
from app.user_model.paths import user_model_root


@dataclass(frozen=True)
class StoryBucketSeed:
    stable_key: str
    file_name: str
    display_name: str
    description: str
    is_splittable: bool
    initial_body: str


class StoryBucketItem(BaseModel):
    id: UUID
    stable_key: str
    file_path: str
    display_name: str
    description: str
    is_splittable: bool
    status: str
    content: str
    last_user_edit_at: datetime | None
    updated_at: datetime


class StoryBucketUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    content: str = Field(min_length=1)


DEFAULT_STORY_BUCKETS: tuple[StoryBucketSeed, ...] = (
    StoryBucketSeed(
        stable_key="who_am_i",
        file_name="who_am_i.md",
        display_name="Who Am I",
        description="Stable identity, constraints, values, and durable self-knowledge.",
        is_splittable=False,
        initial_body="# Who Am I\n\n",
    ),
    StoryBucketSeed(
        stable_key="interests_and_works",
        file_name="interests_and_works.md",
        display_name="Interests And Works",
        description="Projects, interests, learning threads, and work themes.",
        is_splittable=True,
        initial_body="# Interests And Works\n\n",
    ),
    StoryBucketSeed(
        stable_key="career",
        file_name="career.md",
        display_name="Career",
        description="Work identity, career stage, role direction, and professional context.",
        is_splittable=True,
        initial_body="# Career\n\n",
    ),
    StoryBucketSeed(
        stable_key="health",
        file_name="health.md",
        display_name="Health",
        description="Energy, wellbeing, health habits, and constraints that affect daily life.",
        is_splittable=True,
        initial_body="# Health\n\n",
    ),
    StoryBucketSeed(
        stable_key="relationships",
        file_name="relationships.md",
        display_name="Relationships",
        description="People, communities, and relationship context that shape the person's life.",
        is_splittable=True,
        initial_body="# Relationships\n\n",
    ),
    StoryBucketSeed(
        stable_key="habits",
        file_name="habits.md",
        display_name="Habits",
        description="Work style, routines, thinking patterns, and recurring personal rhythms.",
        is_splittable=True,
        initial_body="# Habits\n\n",
    ),
    StoryBucketSeed(
        stable_key="aspirations",
        file_name="aspirations.md",
        display_name="Aspirations",
        description="Near-term direction, longer-term pulls, ambitions, and desired trajectory.",
        is_splittable=True,
        initial_body="# Aspirations\n\n",
    ),
)


def ensure_story_buckets(root: Path | None = None, conn: Connection | None = None) -> None:
    """Seed default Story Buckets in Postgres. Content lives in the `content` column.

    For backwards compatibility: if a row exists with empty content but the legacy
    `file_path` on disk has content, lift that content into the row (one-time migration).
    """
    model_root = user_model_root(root)

    if conn is None:
        with connect() as owned_conn:
            ensure_story_buckets(model_root, owned_conn)
            owned_conn.commit()
        return

    seed_by_key = {seed.stable_key: seed for seed in DEFAULT_STORY_BUCKETS}

    with conn.cursor() as cur:
        for seed in DEFAULT_STORY_BUCKETS:
            file_path = model_root / seed.file_name
            cur.execute(
                """
                INSERT INTO story_buckets (
                    stable_key, file_path, display_name, description, is_splittable
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (stable_key) DO UPDATE SET
                    file_path = EXCLUDED.file_path,
                    display_name = EXCLUDED.display_name,
                    description = EXCLUDED.description,
                    is_splittable = EXCLUDED.is_splittable,
                    updated_at = now()
                """,
                (
                    seed.stable_key,
                    str(file_path),
                    seed.display_name,
                    seed.description,
                    seed.is_splittable,
                ),
            )

        # Hydrate content: prefer legacy on-disk markdown; fall back to seed body.
        # Considered "needs hydration" when current content is empty OR identical
        # to a known seed body (i.e. never actually filled with the user's real text).
        cur.execute(
            "SELECT id, stable_key, file_path, content FROM story_buckets"
        )
        for row in cur.fetchall():
            current = (row["content"] or "").strip()
            seed = seed_by_key.get(row["stable_key"])
            seed_body_stripped = seed.initial_body.strip() if seed else ""
            looks_empty = current == "" or current == seed_body_stripped
            if not looks_empty:
                continue

            disk_path = Path(row["file_path"])
            new_content: str | None = None
            if disk_path.exists():
                disk_text = disk_path.read_text(encoding="utf-8")
                if disk_text.strip() and disk_text.strip() != seed_body_stripped:
                    new_content = disk_text

            if new_content is None and current == "" and seed is not None:
                new_content = seed.initial_body

            if new_content is None:
                continue

            cur.execute(
                "UPDATE story_buckets SET content = %s, updated_at = now() WHERE id = %s",
                (new_content, row["id"]),
            )

        cur.execute(
            "UPDATE story_buckets SET status = 'archived', updated_at = now() "
            "WHERE stable_key = 'goals' AND status = 'active'"
        )


def list_story_buckets(conn: Connection | None = None) -> list[dict]:
    """Return active Story Buckets ordered for the settings UI."""
    if conn is None:
        with connect() as owned_conn:
            return list_story_buckets(owned_conn)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, stable_key, file_path, display_name, description,
                is_splittable, status, content, last_user_edit_at, updated_at
            FROM story_buckets
            WHERE status = 'active'
            ORDER BY
                CASE stable_key
                    WHEN 'who_am_i' THEN 1
                    WHEN 'interests_and_works' THEN 2
                    ELSE 10
                END,
                display_name
            """
        )
        return [dict(row) for row in cur.fetchall()]


def list_story_bucket_items(conn: Connection | None = None) -> list[StoryBucketItem]:
    """Return active Story Buckets with their current markdown content."""
    if conn is None:
        with connect() as owned_conn:
            return list_story_bucket_items(owned_conn)

    return [_row_to_item(bucket) for bucket in list_story_buckets(conn)]


def get_story_bucket_item(bucket_id: UUID | str, conn: Connection | None = None) -> StoryBucketItem:
    """Return one Story Bucket with current markdown content."""
    if conn is None:
        with connect() as owned_conn:
            return get_story_bucket_item(bucket_id, owned_conn)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, stable_key, file_path, display_name, description,
                is_splittable, status, content, last_user_edit_at, updated_at
            FROM story_buckets
            WHERE id = %s AND status = 'active'
            """,
            (bucket_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Unknown Story Bucket: {bucket_id}")
        return _row_to_item(dict(row))


def update_story_bucket_item(
    bucket_id: UUID | str,
    payload: StoryBucketUpdate,
    *,
    conn: Connection | None = None,
) -> StoryBucketItem:
    """Update Story Bucket metadata/content and activate User Edit Lock."""
    if conn is None:
        with connect() as owned_conn:
            bucket = update_story_bucket_item(bucket_id, payload, conn=owned_conn)
            owned_conn.commit()
            return bucket

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM story_buckets WHERE id = %s AND status = 'active'", (bucket_id,))
        if cur.fetchone() is None:
            raise ValueError(f"Unknown Story Bucket: {bucket_id}")

        next_content = payload.content.rstrip() + "\n"

        cur.execute(
            """
            UPDATE story_buckets
            SET display_name = COALESCE(%s, display_name),
                description = COALESCE(%s, description),
                content = %s,
                last_user_edit_at = now(),
                updated_at = now()
            WHERE id = %s
            RETURNING id, stable_key, file_path, display_name, description,
                is_splittable, status, content, last_user_edit_at, updated_at
            """,
            (payload.display_name, payload.description, next_content, bucket_id),
        )
        return _row_to_item(dict(cur.fetchone()))


def create_story_bucket(
    *,
    stable_key: str,
    display_name: str,
    file_name: str,
    description: str = "",
    is_splittable: bool = True,
    root: Path | None = None,
    conn: Connection | None = None,
) -> dict:
    """Create a reviewed Story Bucket with stable DB identity."""
    model_root = user_model_root(root)
    file_path = model_root / file_name

    if conn is None:
        with connect() as owned_conn:
            bucket = create_story_bucket(
                stable_key=stable_key,
                display_name=display_name,
                file_name=file_name,
                description=description,
                is_splittable=is_splittable,
                root=model_root,
                conn=owned_conn,
            )
            owned_conn.commit()
            return bucket

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO story_buckets (
                stable_key, file_path, display_name, description, is_splittable, content
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (stable_key) DO UPDATE SET
                file_path = EXCLUDED.file_path,
                display_name = EXCLUDED.display_name,
                description = EXCLUDED.description,
                is_splittable = EXCLUDED.is_splittable,
                status = 'active',
                updated_at = now()
            RETURNING *
            """,
            (stable_key, str(file_path), display_name, description, is_splittable, f"# {display_name}\n\n"),
        )
        return dict(cur.fetchone())


def _row_to_item(bucket: dict) -> StoryBucketItem:
    return StoryBucketItem(
        id=bucket["id"],
        stable_key=bucket["stable_key"],
        file_path=bucket["file_path"],
        display_name=bucket["display_name"],
        description=bucket["description"],
        is_splittable=bucket["is_splittable"],
        status=bucket["status"],
        content=bucket.get("content") or "",
        last_user_edit_at=bucket["last_user_edit_at"],
        updated_at=bucket["updated_at"],
    )


def mark_story_bucket_user_edited(bucket_id: UUID | str, *, conn: Connection | None = None) -> dict:
    """Record that the person edited a Story Bucket, activating User Edit Lock."""
    if conn is None:
        with connect() as owned_conn:
            bucket = mark_story_bucket_user_edited(bucket_id, conn=owned_conn)
            owned_conn.commit()
            return bucket

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE story_buckets
            SET last_user_edit_at = now(), updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (bucket_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Unknown Story Bucket: {bucket_id}")
        return dict(row)


def rename_story_bucket(
    bucket_id: UUID | str,
    *,
    display_name: str | None = None,
    file_name: str | None = None,
    conn: Connection | None = None,
) -> dict:
    """Rename a bucket display name and/or its identifying file path label.

    Note: `file_path` is now a stable string label, not an actual on-disk file.
    """
    if conn is None:
        with connect() as owned_conn:
            bucket = rename_story_bucket(
                bucket_id,
                display_name=display_name,
                file_name=file_name,
                conn=owned_conn,
            )
            owned_conn.commit()
            return bucket

    with conn.cursor() as cur:
        cur.execute("SELECT * FROM story_buckets WHERE id = %s", (bucket_id,))
        current = cur.fetchone()
        if current is None:
            raise ValueError(f"Unknown Story Bucket: {bucket_id}")

        next_file_path = Path(current["file_path"])
        if file_name is not None:
            next_file_path = next_file_path.parent / file_name

        cur.execute(
            """
            UPDATE story_buckets
            SET display_name = COALESCE(%s, display_name),
                file_path = %s,
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (display_name, str(next_file_path), bucket_id),
        )
        return dict(cur.fetchone())
