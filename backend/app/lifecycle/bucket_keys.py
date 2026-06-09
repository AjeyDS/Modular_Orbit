"""Shared story-bucket stable key normalization."""

from __future__ import annotations

from typing import Any

KNOWN_BUCKET_KEYS = {
    "who_am_i",
    "goals",
    "interests_and_works",
    "career",
    "health",
    "relationships",
    "habits",
    "aspirations",
}

ALLOWED_KEYS_LINE = (
    "Allowed bucket_key values — use EXACTLY one of these stable keys, lowercase, "
    "never a display name or invented key: " + ", ".join(sorted(KNOWN_BUCKET_KEYS)) + "."
)


def normalize_bucket_key(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    key = raw.strip().lower().replace(" ", "_").replace("-", "_")
    while "__" in key:
        key = key.replace("__", "_")
    return key if key in KNOWN_BUCKET_KEYS else None
