"""Curious Companion: conversational, persona-driven user-model harvesting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from app.db import transaction
from app.lifecycle import create_life_item
from app.chat.actions import KNOWN_BUCKET_KEYS
from app.llm import LLMUnavailable, generate_json, generate_text
from app.modules.curious import (
    CuriousWeaveResult,
    _mark_session_lifecycle_not_needed,
    get_curious_page_state,
    weave_pending_curious_updates,
)
from app.user_model import list_goals


class CompanionMessage(BaseModel):
    id: UUID
    role: str
    content: str
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class CompanionTimelineEntry(BaseModel):
    id: UUID
    text: str
    captured_at: datetime


class CompanionReply(BaseModel):
    kind: str
    message: str
    quick_replies: list[dict[str, Any]] = Field(default_factory=list)
    target_bucket_key: str | None = None


class CompanionState(BaseModel):
    messages: list[CompanionMessage]
    timeline: list[CompanionTimelineEntry]
    pending_checkin: CompanionMessage | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class CompanionMessageResponse(BaseModel):
    reply: CompanionReply

_FILLER = {
    "ok", "okay", "k", "thanks", "thank you", "thx", "yes", "no", "sure",
    "yep", "nope", "cool", "great", "lol", "haha",
}

_END_MARKERS = (
    "bye",
    "goodbye",
    "talk to you later",
    "talk later",
    "that's all",
    "thats all",
    "gotta go",
    "see you",
)


def _is_end_intent(text: str) -> bool:
    cleaned = text.strip().lower().rstrip("!.")
    return cleaned in _END_MARKERS or cleaned.startswith(
        ("bye", "talk to you later", "talk later")
    )

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
                    AND li.payload ->> 'session_state' = 'open'
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
            "session_state": "open",
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
        source={"kind": "companion_session"},
        request_id=f"companion-session-{uuid4().hex}",
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


def record_user_turn(
    session_id: UUID | str, text: str, *, capture: bool = True
) -> None:
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

    if not capture or not is_meaningful_reply(text):
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


def _companion_settings() -> dict[str, Any]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT mi.settings, m.default_settings
                FROM module_instances mi
                JOIN modules m ON m.id = mi.module_id
                WHERE m.id = 'curious'
                ORDER BY mi.created_at ASC
                LIMIT 1
                """
            )
            row = cur.fetchone()
    if row is None:
        return {}
    defaults = dict(row["default_settings"] or {})
    instance = dict(row["settings"] or {})
    return {**defaults, **instance}


def generate_companion_question() -> dict[str, Any]:
    settings = _companion_settings()
    persona = build_persona_prompt(
        preset=str(settings.get("companion_persona_preset", "warm")),
        override=str(settings.get("companion_persona_override", "")),
    )
    context = build_companion_context()
    try:
        data = generate_json(
            f"Context:\n{context}\n\n"
            'Return JSON: {"opening_message":"...", "target_bucket_key":"...", '
            '"quick_replies":[{"id":"...","label":"..."}], "rationale":"..."}',
            system=persona,
            temperature=0.3,
            max_output_tokens=400,
        )
        bucket_key = data.get("target_bucket_key")
        if bucket_key not in KNOWN_BUCKET_KEYS:
            raise ValueError("invalid bucket key")
        opening = str(data.get("opening_message") or "").strip()
        if not opening:
            raise ValueError("empty opening message")
        quick_replies = data.get("quick_replies") or []
        if not isinstance(quick_replies, list):
            quick_replies = []
        return {
            "opening_message": opening,
            "target_bucket_key": bucket_key,
            "quick_replies": quick_replies,
            "rationale": str(data.get("rationale") or ""),
        }
    except (LLMUnavailable, Exception):
        return _foundational_question_fallback()


def respond_to_user_turn(text: str) -> dict[str, Any]:
    session = get_or_create_companion_session()
    if _is_end_intent(text):
        record_user_turn(session["id"], text, capture=False)
        settings = _companion_settings()
        persona = build_persona_prompt(
            preset=str(settings.get("companion_persona_preset", "warm")),
            override=str(settings.get("companion_persona_override", "")),
        )
        try:
            signoff = generate_text(
                "The person is ending the conversation. Reply with one brief warm sign-off.",
                system=persona,
                temperature=0.4,
                max_output_tokens=80,
            )
        except (LLMUnavailable, Exception):
            signoff = "Talk soon — take care."
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO companion_messages (session_id, role, content, meta)
                    VALUES (%s, 'assistant', %s, %s)
                    """,
                    (session["id"], signoff, Jsonb({"kind": "signoff"})),
                )
        end_companion_session()
        return {"kind": "ended", "message": signoff}

    outstanding = _has_outstanding_question(session["id"])
    record_user_turn(session["id"], text)

    if is_meaningful_reply(text):
        return _companion_acknowledge(session["id"], text)
    if outstanding:
        return _companion_acknowledge(session["id"], text)
    return _companion_ask(session["id"])


def _has_outstanding_question(session_id: UUID | str) -> bool:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, meta, created_at
                FROM companion_messages
                WHERE session_id = %s AND role = 'assistant'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id,),
            )
            last_assistant = cur.fetchone()
            if last_assistant is None:
                return False
            kind = (last_assistant.get("meta") or {}).get("kind")
            if kind not in {"question", "checkin"}:
                return False
            cur.execute(
                """
                SELECT COUNT(*) AS c
                FROM companion_messages
                WHERE session_id = %s
                    AND role = 'user'
                    AND created_at > %s
                """,
                (session_id, last_assistant["created_at"]),
            )
            return cur.fetchone()["c"] == 0


def _companion_acknowledge(session_id: UUID | str, text: str) -> dict[str, Any]:
    settings = _companion_settings()
    persona = build_persona_prompt(
        preset=str(settings.get("companion_persona_preset", "warm")),
        override=str(settings.get("companion_persona_override", "")),
    )
    try:
        message = generate_text(
            f"The person just said:\n{text}\n\nReply with one brief warm acknowledgment.",
            system=persona,
            temperature=0.4,
            max_output_tokens=120,
        )
    except (LLMUnavailable, Exception):
        message = "Got it — thanks for sharing that."

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO companion_messages (session_id, role, content, meta)
                VALUES (%s, 'assistant', %s, %s)
                """,
                (session_id, message, Jsonb({"kind": "acknowledge"})),
            )
    return {"kind": "acknowledge", "message": message}


def _companion_ask(session_id: UUID | str) -> dict[str, Any]:
    question = generate_companion_question()
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO companion_messages (session_id, role, content, meta)
                VALUES (%s, 'assistant', %s, %s)
                """,
                (
                    session_id,
                    question["opening_message"],
                    Jsonb({
                        "kind": "question",
                        "target_bucket_key": question["target_bucket_key"],
                        "quick_replies": question.get("quick_replies") or [],
                    }),
                ),
            )
    return {
        "kind": "question",
        "message": question["opening_message"],
        "quick_replies": question.get("quick_replies") or [],
        "target_bucket_key": question["target_bucket_key"],
    }


def prepare_due_checkin() -> dict[str, Any] | None:
    settings = _companion_settings()
    if not settings.get("companion_enabled", True):
        return None
    checkins_per_day = int(settings.get("companion_checkins_per_day") or 0)
    if checkins_per_day <= 0:
        return None

    interval = timedelta(hours=24 / checkins_per_day)
    session = get_or_create_companion_session()
    session_id = session["id"]

    with transaction() as conn:
        with conn.cursor() as cur:
            now = _db_now(conn)
            cur.execute(
                """
                SELECT id, content, meta, created_at
                FROM companion_messages
                WHERE session_id = %s
                    AND role = 'assistant'
                    AND meta ->> 'kind' = 'checkin'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id,),
            )
            latest_checkin = cur.fetchone()
            if latest_checkin is not None:
                cur.execute(
                    """
                    SELECT COUNT(*) AS c
                    FROM companion_messages
                    WHERE session_id = %s
                        AND role = 'user'
                        AND created_at > %s
                    """,
                    (session_id, latest_checkin["created_at"]),
                )
                if cur.fetchone()["c"] == 0:
                    return None
                if now - latest_checkin["created_at"] < interval:
                    return None

    question = generate_companion_question()
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO companion_messages (session_id, role, content, meta)
                VALUES (%s, 'assistant', %s, %s)
                RETURNING id
                """,
                (
                    session_id,
                    question["opening_message"],
                    Jsonb({
                        "kind": "checkin",
                        "target_bucket_key": question["target_bucket_key"],
                        "quick_replies": question.get("quick_replies") or [],
                    }),
                ),
            )
            message_id = cur.fetchone()["id"]

    return {
        "kind": "checkin",
        "message": question["opening_message"],
        "target_bucket_key": question["target_bucket_key"],
        "quick_replies": question.get("quick_replies") or [],
        "message_id": str(message_id),
    }


def _db_now(conn) -> datetime:
    with conn.cursor() as cur:
        cur.execute("SELECT now() AS now")
        return cur.fetchone()["now"]


def synthesize_companion_session(session_id: UUID | str) -> None:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content
                FROM companion_messages
                WHERE session_id = %s
                ORDER BY created_at
                """,
                (session_id,),
            )
            messages = cur.fetchall()
            cur.execute(
                """
                SELECT id
                FROM life_items
                WHERE item_type = 'curious_capture'
                    AND payload ->> 'session_id' = %s
                    AND lifecycle_status <> 'deleted'
                ORDER BY created_at
                """,
                (str(session_id),),
            )
            capture_rows = cur.fetchall()

    if not messages:
        return

    transcript = "\n".join(f"{row['role']}: {row['content']}" for row in messages)
    try:
        data = generate_json(
            f"Conversation:\n{transcript}\n\n"
            'Return JSON: {"facts":[{"bucket_key":"...", "text":"..."}]}',
            system=(
                "Extract durable facts about the person from this companion conversation. "
                "Return only JSON."
            ),
            temperature=0.1,
            max_output_tokens=600,
        )
        raw_facts = data.get("facts") or []
        if not isinstance(raw_facts, list):
            return
    except (LLMUnavailable, Exception):
        return

    link_item_id = capture_rows[0]["id"] if capture_rows else session_id
    facts = []
    for fact in raw_facts:
        if not isinstance(fact, dict):
            continue
        bucket_key = fact.get("bucket_key")
        if bucket_key not in KNOWN_BUCKET_KEYS:
            continue
        text = str(fact.get("text") or "").strip()
        if text:
            facts.append((bucket_key, text))

    if not facts:
        return

    with transaction() as conn:
        with conn.cursor() as cur:
            for bucket_key, text in facts:
                cur.execute(
                    """
                    SELECT id
                    FROM story_buckets
                    WHERE stable_key = %s AND status = 'active'
                    """,
                    (bucket_key,),
                )
                bucket = cur.fetchone()
                if bucket is None:
                    continue
                cur.execute(
                    """
                    INSERT INTO bucket_updates (
                        story_bucket_id, life_item_id, status, update_text, source_event
                    )
                    VALUES (%s, %s, 'pending', %s, %s)
                    """,
                    (
                        bucket["id"],
                        link_item_id,
                        text,
                        Jsonb({
                            "source": "curious_companion",
                            "session_id": str(session_id),
                            "bucket_key": bucket_key,
                        }),
                    ),
                )
            cur.execute(
                """
                UPDATE life_items
                SET bucket_update_status = 'complete',
                    updated_at = now()
                WHERE item_type = 'curious_capture'
                    AND payload ->> 'session_id' = %s
                    AND lifecycle_status <> 'deleted'
                """,
                (str(session_id),),
            )


def _foundational_question_fallback() -> dict[str, Any]:
    page_state = get_curious_page_state()
    if page_state.pending_questions:
        question = page_state.pending_questions[0].question
        return {
            "opening_message": question.question_text,
            "target_bucket_key": question.target_bucket_key,
            "quick_replies": [
                {"id": option.id, "label": option.label}
                for option in question.options
            ],
            "rationale": "foundational fallback",
        }
    return {
        "opening_message": "How are things going today?",
        "target_bucket_key": "who_am_i",
        "quick_replies": [],
        "rationale": "generic check-in",
    }


def _derive_title(text: str) -> str:
    title = " ".join(text.strip().split())
    if len(title) <= 80:
        return title
    return f"{title[:77].rstrip()}..."


def get_companion_state() -> CompanionState:
    prepare_due_checkin()
    session = get_or_create_companion_session()
    session_id = session["id"]

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, role, content, meta, created_at
                FROM companion_messages
                WHERE session_id = %s
                ORDER BY created_at
                """,
                (session_id,),
            )
            message_rows = cur.fetchall()
            cur.execute(
                """
                SELECT id, description, created_at
                FROM life_items
                WHERE item_type = 'curious_capture'
                    AND payload ->> 'session_id' = %s
                    AND lifecycle_status <> 'deleted'
                ORDER BY created_at DESC
                """,
                (str(session_id),),
            )
            capture_rows = cur.fetchall()

    messages = [
        CompanionMessage(
            id=row["id"],
            role=row["role"],
            content=row["content"],
            meta=dict(row.get("meta") or {}),
            created_at=row["created_at"],
        )
        for row in message_rows
    ]
    timeline = [
        CompanionTimelineEntry(
            id=row["id"],
            text=row["description"],
            captured_at=row["created_at"],
        )
        for row in capture_rows
    ]
    pending = _pending_checkin_message(session_id)

    return CompanionState(
        messages=messages,
        timeline=timeline,
        pending_checkin=pending,
        settings=_companion_settings(),
    )


def send_companion_message(text: str) -> CompanionMessageResponse:
    reply = respond_to_user_turn(text)
    return CompanionMessageResponse(reply=CompanionReply(**reply))


def end_companion_session() -> CuriousWeaveResult:
    session = get_or_create_companion_session()
    session_id = session["id"]
    synthesize_companion_session(session_id)
    result = weave_pending_curious_updates()
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE life_items
                SET payload = jsonb_set(payload, '{session_state}', '"closed"'),
                    updated_at = now()
                WHERE id = %s
                """,
                (session_id,),
            )
    return result


def _pending_checkin_message(session_id: UUID | str) -> CompanionMessage | None:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, role, content, meta, created_at
                FROM companion_messages
                WHERE session_id = %s
                    AND role = 'assistant'
                    AND meta ->> 'kind' = 'checkin'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id,),
            )
            latest = cur.fetchone()
            if latest is None:
                return None
            cur.execute(
                """
                SELECT COUNT(*) AS c
                FROM companion_messages
                WHERE session_id = %s
                    AND role = 'user'
                    AND created_at > %s
                """,
                (session_id, latest["created_at"]),
            )
            if cur.fetchone()["c"] > 0:
                return None

    return CompanionMessage(
        id=latest["id"],
        role=latest["role"],
        content=latest["content"],
        meta=dict(latest.get("meta") or {}),
        created_at=latest["created_at"],
    )
