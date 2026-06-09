"""Explicit database bootstrap for local Modular Orbit development."""

from __future__ import annotations

from app.db.schema import ensure_schema
from app.modules.registry import sync_module_registry
from app.user_model import ensure_goals_seed, ensure_story_buckets


def bootstrap_database() -> None:
    """Create schema primitives and sync developer-authored modules."""
    ensure_schema()
    sync_module_registry()
    ensure_story_buckets()
    ensure_goals_seed()


if __name__ == "__main__":
    bootstrap_database()
