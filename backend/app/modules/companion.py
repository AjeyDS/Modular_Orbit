"""Curious Companion: conversational, persona-driven user-model harvesting."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from app.db import transaction
from app.lifecycle import create_life_item
from app.lifecycle.bucket_keys import ALLOWED_KEYS_LINE, KNOWN_BUCKET_KEYS, normalize_bucket_key
from app.llm import LLMUnavailable, generate_json, generate_text
from app.modules.curious import (
    CuriousWeaveResult,
    _mark_session_lifecycle_not_needed,
    get_curious_page_state,
    weave_pending_curious_updates,
)
from app.modules.logs import LogCreate, create_log
from app.user_model import build_user_model_context, list_goals

logger = logging.getLogger(__name__)


class CompanionMessage(BaseModel):
    id: UUID
    role: str
    content: str
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class CompanionReply(BaseModel):
    kind: str
    message: str
    quick_replies: list[dict[str, Any]] = Field(default_factory=list)
    target_bucket_key: str | None = None


class CompanionState(BaseModel):
    messages: list[CompanionMessage]
    pending_checkin: CompanionMessage | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class CompanionMessageResponse(BaseModel):
    reply: CompanionReply

_FILLER = {
    "ok", "okay", "k", "thanks", "thank you", "thx", "yes", "no", "sure",
    "yep", "nope", "cool", "great", "lol", "haha",
}

# Vague status / pleasantry replies that carry no durable signal about the
# person. Kept out of the user model and Logs (deterministic-fallback path).
_VAGUE_STATUS = {
    "good", "im good", "i'm good", "all good", "pretty good", "going good",
    "its going good", "it's going good", "fine", "im fine", "i'm fine",
    "alright", "not much", "nothing much", "same as usual", "busy", "tired",
    "meh", "nothing", "the same", "as usual",
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
            "meaningful=true ONLY for a concrete fact, event, plan, decision, or "
            "specific preference about the person. Vague status or pleasantries "
            '("it\'s going good", "fine", "busy", "not much") are NOT meaningful.',
            system="You judge whether a chat reply carries durable signal about the person. Return only JSON.",
            temperature=0.0,
            max_output_tokens=80,
        )
        return bool(data.get("meaningful", False))
    except (LLMUnavailable, Exception):
        if cleaned in _FILLER or cleaned in _VAGUE_STATUS:
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

    log = create_log(
        LogCreate(
            text=text,
            request_id=f"companion-capture-{message_id}",
            source={"kind": "companion_capture", "session_id": str(session_id)},
        ),
        review=False,
    )
    # The companion handles user-model enrichment via session-end synthesis, not
    # per-log Connection Review. Mark the log's async statuses terminal so the
    # Logs UI does not show perpetual "pending" badges.
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE life_items
                SET connection_status = 'complete',
                    chunk_status = 'not_needed',
                    bucket_update_status = 'not_needed',
                    updated_at = now()
                WHERE id = %s
                """,
                (log.id,),
            )

    # Capture the raw answer as a companion fact (best-effort, post-commit). The
    # companion-capture log above no longer emits its own life_item fact, so this
    # is the single fact for this meaningful reply.
    try:
        from app.user_model import capture_fact
        capture_fact(
            source="companion",
            text=text,
            ref={"session_id": str(session_id), "message_id": str(message_id)},
        )
    except Exception:
        logger.warning("Failed to capture companion fact for session %s", session_id, exc_info=True)


def build_companion_context() -> str:
    sections: list[str] = []

    with transaction() as conn:
        with conn.cursor() as cur:
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
            cur.execute(
                """
                SELECT m.id AS module_id, li.item_type, li.title, li.created_at
                FROM life_items li
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE m.id IN ('logs', 'tasks', 'plans', 'documents', 'routine')
                    AND li.item_type NOT IN ('curious_session', 'curious_question')
                    AND li.lifecycle_status <> 'deleted'
                ORDER BY li.created_at DESC
                LIMIT 12
                """
            )
            recent_rows = cur.fetchall()

    user_model = build_user_model_context(budget=1800)
    if user_model.strip():
        sections.append("User model:\n" + user_model)

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

    recent_block = ""
    if recent_rows:
        recent_block = "Recent activity:\n" + "\n".join(
            f"- [{r['module_id']}] {r['title']}" for r in recent_rows
        )

    context = "\n\n".join(sections)
    if not recent_block:
        return context[:2000]

    reserved = len(recent_block) + 2
    if reserved >= 2000:
        return recent_block[:2000]
    budget = 2000 - reserved
    if len(context) > budget:
        context = context[:budget]
    return f"{context}\n\n{recent_block}" if context else recent_block


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


_QUESTION_STYLE = (
    "Ask ONE small, concrete, conversational question, answerable in a few words or "
    "more — never an essay prompt. "
    "Each quick_reply label is a SHORT FIRST-PERSON answer THE PERSON might give to "
    "your question (e.g. 'A side project', 'Mostly walking', 'For my career') — write "
    "them in the person's voice. NEVER make a quick_reply a follow-up question or "
    "anything in your own voice. Offer 2–4 when natural; the person can also type freely."
)

def generate_companion_question(exclude_bucket: str | None = None) -> dict[str, Any]:
    settings = _companion_settings()
    persona = build_persona_prompt(
        preset=str(settings.get("companion_persona_preset", "warm")),
        override=str(settings.get("companion_persona_override", "")),
    )
    system_parts = [persona, _QUESTION_STYLE, ALLOWED_KEYS_LINE]
    if exclude_bucket:
        system_parts.append(
            f"Do not target the '{exclude_bucket}' bucket; choose a different area."
        )
    system = "\n\n".join(system_parts)
    context = build_companion_context()
    try:
        data = generate_json(
            f"Context:\n{context}\n\n"
            'Return JSON: {"opening_message":"...", "target_bucket_key":"...", '
            '"quick_replies":[{"id":"...","label":"..."}], "rationale":"..."}',
            system=system,
            temperature=0.3,
            max_output_tokens=400,
        )
        bucket_key = normalize_bucket_key(data.get("target_bucket_key"))
        if bucket_key is None:
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
        return _foundational_question_fallback(exclude_bucket=exclude_bucket)


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


def _companion_ask(
    session_id: UUID | str, *, exclude_bucket: str | None = None
) -> dict[str, Any]:
    question = generate_companion_question(exclude_bucket=exclude_bucket)
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
                SELECT li.id
                FROM life_items li
                JOIN module_instances mi ON mi.id = li.module_instance_id
                WHERE mi.module_id = 'logs'
                    AND li.item_type = 'log'
                    AND li.source ->> 'session_id' = %s
                    AND li.lifecycle_status <> 'deleted'
                ORDER BY li.created_at DESC
                LIMIT 1
                """,
                (str(session_id),),
            )
            log_row = cur.fetchone()

    if not messages:
        return

    transcript = "\n".join(f"{row['role']}: {row['content']}" for row in messages)
    try:
        data = generate_json(
            f"Conversation:\n{transcript}\n\n"
            'Return JSON: {"facts":[{"bucket_key":"...", "text":"..."}]}',
            system=(
                "Extract durable facts about the person from this companion conversation. "
                "Return only JSON. " + ALLOWED_KEYS_LINE
            ),
            temperature=0.1,
            max_output_tokens=600,
        )
        raw_facts = data.get("facts") or []
        if not isinstance(raw_facts, list):
            return
    except (LLMUnavailable, Exception):
        return

    link_item_id = log_row["id"] if log_row else session_id
    facts = []
    for fact in raw_facts:
        if not isinstance(fact, dict):
            continue
        bucket_key = normalize_bucket_key(fact.get("bucket_key"))
        if bucket_key is None:
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


def _foundational_question_fallback(
    *, exclude_bucket: str | None = None
) -> dict[str, Any]:
    page_state = get_curious_page_state()
    if page_state.pending_questions:
        for pending in page_state.pending_questions:
            question = pending.question
            if exclude_bucket and question.target_bucket_key == exclude_bucket:
                continue
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
    pending = _pending_checkin_message(session_id)

    return CompanionState(
        messages=messages,
        pending_checkin=pending,
        settings=_companion_settings(),
    )


def send_companion_message(text: str) -> CompanionMessageResponse:
    reply = respond_to_user_turn(text)
    return CompanionMessageResponse(reply=CompanionReply(**reply))


def ask_companion_question() -> CompanionMessageResponse:
    session = get_or_create_companion_session()
    reply = _companion_ask(session["id"])
    return CompanionMessageResponse(reply=CompanionReply(**reply))


def skip_companion_question(bucket_key: str | None) -> CompanionMessageResponse:
    session = get_or_create_companion_session()
    reply = _companion_ask(session["id"], exclude_bucket=bucket_key)
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
