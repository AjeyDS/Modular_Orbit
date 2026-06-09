"""Curious Companion: conversational, persona-driven user-model harvesting."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.lifecycle import create_life_item
from app.llm import LLMUnavailable, generate_json
from app.modules.curious import _mark_session_lifecycle_not_needed

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
    from app.db import transaction

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
