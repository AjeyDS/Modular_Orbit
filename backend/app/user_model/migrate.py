"""One-shot, idempotent migration: seed the initial woven doc from Story Buckets."""

from __future__ import annotations

from typing import Any

from psycopg import Connection

from app.user_model.facts import capture_fact
from app.user_model.story_buckets import list_story_bucket_items
from app.user_model.weave import current_woven_doc, weave_user_model


def _meaningful_content(display_name: str, content: str) -> str | None:
    """Return the bucket content if it carries real text beyond its header, else None."""
    stripped = (content or "").strip()
    if not stripped:
        return None
    header = f"# {display_name}".strip()
    if stripped == header:
        return None
    return stripped


def seed_woven_user_model(conn: Connection | None = None) -> dict[str, Any] | None:
    """Seed a version-1 woven doc from existing Story Buckets, once.

    Idempotent: if a woven doc already exists, returns None without re-seeding.
    Returns None when there is no meaningful bucket content to fold in.
    """
    if current_woven_doc(conn) is not None:
        return None

    seeded_any = False
    for bucket in list_story_bucket_items(conn):
        meaningful = _meaningful_content(bucket.display_name, bucket.content)
        if meaningful is None:
            continue
        capture_fact(
            source="import",
            text=f"{bucket.display_name}: {meaningful}",
            conn=conn,
        )
        seeded_any = True

    if not seeded_any:
        return None

    return weave_user_model(conn)
