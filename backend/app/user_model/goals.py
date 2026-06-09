"""Goals stored in Postgres. Public contract: GoalEntry + list_goals + promote_goal."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from app.db import connect, transaction
from app.user_model.paths import user_model_root


GoalStatus = Literal["active", "tentative"]

# Legacy markdown parsing — used once at seed time to lift existing goals.md into the DB.
_LEGACY_GOAL_MARKER_RE = re.compile(r"<!--\s*goal:\s*([a-z][a-z0-9_-]*)\s*-->")
_LEGACY_SECTION_RE = re.compile(r"^##\s+(Active|Tentative)\s*$", re.IGNORECASE | re.MULTILINE)
_LEGACY_TITLE_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class GoalEntry:
    goal_id: str
    title: str
    body: str
    status: GoalStatus
    horizon: str = "long_term"
    target_date: date | None = None
    target_note: str | None = None


def goals_path(root: Path | None = None) -> Path:
    """Path to the legacy on-disk goals.md.

    The runtime no longer reads this file after the one-time seed; it remains
    only as a migration source for `ensure_goals_seed()` and as a convenience
    for tests that want to stage seed content.
    """
    return user_model_root(root) / "goals.md"


def ensure_goals_seed(root: Path | None = None) -> None:
    """Seed the goals table from legacy goals.md once; no-op afterward.

    Idempotent: skips when the table already has rows, regardless of file presence.
    """
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM goals")
            if cur.fetchone()["n"] > 0:
                return

            path = user_model_root(root) / "goals.md"
            if not path.exists():
                return

            text = path.read_text(encoding="utf-8")
            sections = _split_goal_sections_legacy(text)
            for status, section_text in sections.items():
                for index, (goal_id, title, body) in enumerate(_parse_section_legacy(section_text)):
                    cur.execute(
                        """
                        INSERT INTO goals (goal_id, title, body, status, position)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (goal_id) DO NOTHING
                        """,
                        (goal_id, title, body, status, index),
                    )


def list_goals() -> list[GoalEntry]:
    """Return all goals ordered by status then position."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT goal_id, title, body, status, horizon, target_date, target_note
                FROM goals
                ORDER BY
                    CASE status WHEN 'active' THEN 0 ELSE 1 END,
                    position,
                    goal_id
                """
            )
            return [
                GoalEntry(
                    goal_id=row["goal_id"],
                    title=row["title"],
                    body=row["body"] or "",
                    status=row["status"],
                    horizon=row["horizon"],
                    target_date=row["target_date"],
                    target_note=row["target_note"],
                )
                for row in cur.fetchall()
            ]


def _slugify_goal(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug[:60].strip("-") or "goal"


def create_goal(
    title: str,
    body: str = "",
    status: GoalStatus = "tentative",
    horizon: str = "long_term",
    target_date: date | None = None,
    target_note: str | None = None,
) -> GoalEntry:
    base = _slugify_goal(title)
    with transaction() as conn:
        with conn.cursor() as cur:
            goal_id = base
            n = 2
            while True:
                cur.execute("SELECT 1 FROM goals WHERE goal_id = %s", (goal_id,))
                if cur.fetchone() is None:
                    break
                goal_id = f"{base}-{n}"
                n += 1
            cur.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM goals WHERE status = %s",
                (status,),
            )
            position = cur.fetchone()["p"]
            cur.execute(
                """
                INSERT INTO goals (
                    goal_id, title, body, status, position, horizon, target_date, target_note
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING goal_id, title, body, status, horizon, target_date, target_note
                """,
                (goal_id, title, body, status, position, horizon, target_date, target_note),
            )
            row = cur.fetchone()
    return GoalEntry(
        goal_id=row["goal_id"],
        title=row["title"],
        body=row["body"] or "",
        status=row["status"],
        horizon=row["horizon"],
        target_date=row["target_date"],
        target_note=row["target_note"],
    )


def promote_goal(goal_id: str) -> GoalEntry:
    """Move a Tentative Goal into Active while preserving its goal ID."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goals
                SET status = 'active', updated_at = now()
                WHERE goal_id = %s
                RETURNING goal_id, title, body, status, horizon, target_date, target_note
                """,
                (goal_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Unknown goal: {goal_id}")
            return GoalEntry(
                goal_id=row["goal_id"],
                title=row["title"],
                body=row["body"] or "",
                status=row["status"],
                horizon=row["horizon"],
                target_date=row["target_date"],
                target_note=row["target_note"],
            )


def _split_goal_sections_legacy(text: str) -> dict[GoalStatus, str]:
    matches = list(_LEGACY_SECTION_RE.finditer(text))
    sections: dict[GoalStatus, str] = {"active": "", "tentative": ""}
    for index, match in enumerate(matches):
        raw_name = match.group(1).lower()
        status: GoalStatus = "active" if raw_name == "active" else "tentative"
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[status] = text[start:end]
    return sections


def _parse_section_legacy(section_text: str) -> list[tuple[str, str, str]]:
    """Yield (goal_id, title, body) tuples parsed from a legacy section block."""
    blocks = _LEGACY_GOAL_MARKER_RE.split(section_text)
    out: list[tuple[str, str, str]] = []
    for index in range(1, len(blocks), 2):
        goal_id = blocks[index]
        block = blocks[index + 1].strip()
        title_match = _LEGACY_TITLE_RE.search(block)
        title = title_match.group(1).strip() if title_match else goal_id.replace("-", " ").title()
        body = _LEGACY_TITLE_RE.sub("", block, count=1).strip()
        out.append((goal_id, title, body))
    return out
