"""Curious Companion: conversational, persona-driven user-model harvesting."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.db import transaction
from app.lifecycle import create_life_item
from app.llm import LLMUnavailable, generate_json
from app.modules.curious import _mark_session_lifecycle_not_needed
from app.user_model import list_goals

_FILLER = {
    "ok", "okay", "k", "thanks", "thank you", "thx", "yes", "no", "sure",
    "yep", "nope", "cool", "great", "lol", "haha",
}

PERSONA_PRESETS: dict[str, str] = {
    "warm": "You are warm, encouraging, and gentle. Celebrate small wins briefly.",
    "coach": "You are a focused coach. You encourage but also gently push for clarity and follow-through.",
    "gentle": "You are calm and low-pressure. Never nag; give the person plenty of space.",
    "direct": "You are concise and direct. No fluff; respect the person's time.",
}

_COMPANION_BASE = (
    "You are Orbit's companion: a personal presence getting to know one person over time. "
    "Keep every turn short — a sentence or two. Never produce lists, essays, or code. "
    "Either ask one targeted question, or warmly acknowledge what the person just shared. "
    "Do not interrogate. Use what you know to make the person feel understood."
)


def build_persona_prompt(*, preset: str, override: str) -> str:
    style = PERSONA_PRESETS.get(preset, PERSONA_PRESETS["warm"])
    parts = [_COMPANION_BASE, style]
    if override.strip():
        parts.append(f"Additional instructions from the person: {override.strip()}")
    return " ".join(parts)


def get_or_create_companion_session() -> dict[str, Any]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT li.*
                FROM life_items li
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE m.id = 'curious'
                    AND li.item_type = 'curious_session'
                    AND li.payload ->> 'session_type' = 'companion'
                ORDER BY li.created_at ASC
                LIMIT 1
                """
            )
            existing = cur.fetchone()
            if existing is not None:
                return dict(existing)

    result = create_life_item(
        module_id="curious",
        item_type="curious_session",
        title="Companion Session",
        description="Ongoing Curious companion conversation session.",
        payload={
            "session_type": "companion",
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
        source={"kind": "companion_session"},
        request_id="companion-session",
    )
    _mark_session_lifecycle_not_needed(result.item["id"])
    return result.item


def is_meaningful_reply(text: str) -> bool:
    cleaned = text.strip().lower().rstrip("!.")
    if not cleaned:
        return False
    try:
        data = generate_json(
            f'Reply:\n"{text}"\n\nReturn JSON: {{"meaningful": bool}}. '
            "meaningful=true only if the reply states a fact, update, feeling, or "
            "preference worth remembering about the person; false for greetings/acks/filler.",
            system="You judge whether a chat reply carries durable signal about the person. Return only JSON.",
            temperature=0.0,
            max_output_tokens=80,
        )
        return bool(data.get("meaningful", False))
    except (LLMUnavailable, Exception):
        if cleaned in _FILLER:
            return False
        return len(cleaned.split()) >= 3


def record_user_turn(session_id: UUID | str, text: str) -> None:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO companion_messages (session_id, role, content)
                VALUES (%s, 'user', %s)
                RETURNING id
                """,
                (session_id, text),
            )
            message_id = cur.fetchone()["id"]

    if not is_meaningful_reply(text):
        return

    result = create_life_item(
        module_id="curious",
        item_type="curious_capture",
        title=_derive_title(text),
        description=text,
        payload={"text": text, "session_id": str(session_id)},
        source={"kind": "companion_capture", "session_id": str(session_id)},
        request_id=f"companion-capture-{message_id}",
    )
    capture_id = result.item["id"]
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO knowledge_chunks (life_item_id, content, source_type, metadata)
                VALUES (%s, %s, 'companion_capture', %s)
                """,
                (
                    capture_id,
                    text,
                    Jsonb({"session_id": str(session_id), "message_id": str(message_id)}),
                ),
            )
            cur.execute(
                """
                UPDATE life_items
                SET connection_status = 'complete',
                    chunk_status = 'complete',
                    bucket_update_status = 'pending',
                    updated_at = now()
                WHERE id = %s
                """,
                (capture_id,),
            )


def build_companion_context() -> str:
    sections: list[str] = []

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT stable_key, display_name, description, content
                FROM story_buckets
                WHERE status = 'active'
                ORDER BY display_name
                """
            )
            bucket_rows = cur.fetchall()
            cur.execute(
                """
                SELECT title
                FROM life_items
                WHERE item_type IN ('task', 'plan')
                    AND lifecycle_status = 'active'
                ORDER BY created_at DESC
                LIMIT 10
                """
            )
            task_rows = cur.fetchall()
            cur.execute(
                """
                SELECT DISTINCT payload ->> 'target_bucket_key' AS bucket_key
                FROM life_items
                WHERE item_type IN ('curious_answer', 'curious_capture')
                    AND lifecycle_status <> 'deleted'
                    AND payload ->> 'target_bucket_key' IS NOT NULL
                """
            )
            asked_keys = {row["bucket_key"] for row in cur.fetchall() if row["bucket_key"]}

    if bucket_rows:
        lines = []
        for row in bucket_rows:
            content = (row.get("content") or "")[:400].strip()
            lines.append(f"- {row['display_name']}: {row['description']}\n{content}")
        sections.append("Story Buckets:\n" + "\n".join(lines))

    goals = list_goals()
    if goals:
        sections.append(
            "Goals:\n"
            + "\n".join(
                f"- {goal.status}: {goal.title}\n{(goal.body or '')[:200]}"
                for goal in goals[:10]
            )
        )

    if task_rows:
        sections.append(
            "Active tasks/plans:\n"
            + "\n".join(f"- {row['title']}" for row in task_rows)
        )

    if asked_keys:
        sections.append("Already-asked bucket coverage: " + ", ".join(sorted(asked_keys)))

    context = "\n\n".join(sections)
    return context[:2000]


def _derive_title(text: str) -> str:
    title = " ".join(text.strip().split())
    if len(title) <= 80:
        return title
    return f"{title[:77].rstrip()}..."
