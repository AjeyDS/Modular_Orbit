"""Filesystem paths for editable User Model markdown."""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings


def user_model_root(root: Path | None = None) -> Path:
    """Return the User Model root, resolving relative paths from backend cwd."""
    return (root or settings.user_model_dir).expanduser().resolve()
