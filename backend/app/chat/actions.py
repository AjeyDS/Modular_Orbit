"""Chat modes and Capture Proposal flow."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from collections.abc import Iterator
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from app.db import transaction
from app.llm import LLMUnavailable, generate_json, generate_text, generate_text_stream
from app.modules.documents import DocumentCreate, create_document
from app.modules.logs import LogCreate, create_log
from app.modules.plans import PlanCreate, PlanStepCreate, create_plan
from app.modules.tasks import TaskCreate, create_task
from app.user_model.goals import create_goal
from app.rag import retrieve_chunks
from app.user_model import list_goals


ChatMode = Literal["fast", "understanding"]
ConfidenceBucket = Literal["low", "medium", "high"]

from app.lifecycle.bucket_keys import KNOWN_BUCKET_KEYS
_BROAD_MARKERS = (
    "what should i", "what are the things", "what do i", "focus on",
    "my life", "everything", "overall", "in general", "priorities",
    "where should i", "how am i doing",
)


@dataclass
class RouteDecision:
    breadth: str  # "narrow" | "broad"
    buckets: list[str] = field(default_factory=list)
    expansion_terms: list[str] = field(default_factory=list)
    rationale: str = ""

CONFIDENCE_SCORES: dict[ConfidenceBucket, float] = {
    "low": 0.3,
    "medium": 0.65,
    "high": 0.9,
}


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    mode: ChatMode = "understanding"
    message: str = Field(min_length=1)


class CaptureProposalPreview(BaseModel):
    id: UUID
    session_id: str
    module_id: str
    item_type: str
    title: str
    description: str
    payload: dict[str, Any]
    confidence_bucket: ConfidenceBucket
    confidence_score: float
    explicit_request: bool
    should_create_chunks: bool
    should_create_bucket_update: bool
    status: str


class ChatResponse(BaseModel):
    mode: ChatMode
    answer: str
    suggestions: list[CaptureProposalPreview]


class ConfirmCaptureProposalRequest(BaseModel):
    proposal_id: UUID


class ConfirmCaptureProposalResponse(BaseModel):
    proposal_id: UUID
    module_id: str
    life_item_id: UUID | None = None
    goal_id: str | None = None
    status: str


class DetectedProposal(BaseModel):
    module_id: Literal["logs", "tasks", "plans", "documents", "goals"]
    item_type: str
    title: str
    description: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    confidence_bucket: ConfidenceBucket
    explicit_request: bool = False


def respond_to_chat(request: ChatRequest) -> ChatResponse:
    """Return a mode-shaped answer and restrained Capture Proposal previews."""
    from app.chat.sessions import (
        insert_chat_message,
        truncate_for_title,
        upsert_session_for_message,
    )

    with transaction() as conn:
        upsert_session_for_message(
            conn,
            request.session_id,
            initial_title=truncate_for_title(request.message),
        )
        insert_chat_message(
            conn,
            session_id=request.session_id,
            role="user",
            content=request.message,
            mode=request.mode,
        )

    detected = _detect_capture_proposals(request.message)
    suggestions = [
        _persist_preview(request.session_id, proposal)
        for proposal in detected
        if _should_surface(request.session_id, proposal)
    ]

    answer = _generate_chat_answer(request, suggestions)

    suggestions_json: list[dict[str, Any]] | None
    if suggestions:
        suggestions_json = [proposal.model_dump(mode="json") for proposal in suggestions]
    else:
        suggestions_json = None

    with transaction() as conn:
        insert_chat_message(
            conn,
            session_id=request.session_id,
            role="assistant",
            content=answer,
            suggestions=suggestions_json,
        )

    return ChatResponse(
        mode=request.mode,
        answer=answer,
        suggestions=suggestions,
    )


def respond_to_chat_stream(request: ChatRequest) -> Iterator[dict[str, Any]]:
    """Stream pipeline stage events, answer deltas, and a final done event."""
    from app.chat.sessions import (
        insert_chat_message,
        truncate_for_title,
        upsert_session_for_message,
    )

    with transaction() as conn:
        upsert_session_for_message(
            conn,
            request.session_id,
            initial_title=truncate_for_title(request.message),
        )
        insert_chat_message(
            conn,
            session_id=request.session_id,
            role="user",
            content=request.message,
            mode=request.mode,
        )

    detected = _detect_capture_proposals(request.message)
    suggestions = [
        _persist_preview(request.session_id, proposal)
        for proposal in detected
        if _should_surface(request.session_id, proposal)
    ]

    if request.mode == "understanding":
        yield {"stage": "routing"}
        decision = _route_and_classify(request.message)
        yield {"stage": "retrieving"}
        chunks = _understanding_retrieval(
            request.message,
            decision,
            limit=8 if decision.breadth == "broad" else 4,
        )
        yield {"stage": "reading_story"}
        context = _build_understanding_context(request.message, decision, chunks)
    else:
        yield {"stage": "retrieving"}
        context = _build_answer_context(request.mode, request.message)

    yield {"stage": "writing"}
    system = _chat_system_prompt(request.mode)
    prompt = _answer_prompt(request, context, suggestions)
    answer_parts: list[str] = []
    try:
        for delta in generate_text_stream(
            prompt,
            system=system,
            temperature=0.45,
            max_output_tokens=2200 if request.mode == "understanding" else 1300,
        ):
            answer_parts.append(delta)
            yield {"stage": "answer", "delta": delta}
        answer = "".join(answer_parts)
    except (LLMUnavailable, Exception):
        answer = _fallback_context_answer(request.mode, context, bool(suggestions))
        yield {"stage": "answer", "delta": answer}

    suggestions_json: list[dict[str, Any]] | None
    if suggestions:
        suggestions_json = [proposal.model_dump(mode="json") for proposal in suggestions]
    else:
        suggestions_json = None

    with transaction() as conn:
        insert_chat_message(
            conn,
            session_id=request.session_id,
            role="assistant",
            content=answer,
            suggestions=suggestions_json,
        )

    yield {
        "stage": "done",
        "suggestions": suggestions_json or [],
    }


def confirm_capture_proposal(request: ConfirmCaptureProposalRequest) -> ConfirmCaptureProposalResponse:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM capture_proposals
                WHERE id = %s
                """,
                (request.proposal_id,),
            )
            proposal = cur.fetchone()
            if proposal is None:
                raise ValueError(f"Unknown Capture Proposal: {request.proposal_id}")
            if proposal["status"] == "accepted" and proposal["created_life_item_id"] is not None:
                return ConfirmCaptureProposalResponse(
                    proposal_id=proposal["id"],
                    module_id=proposal["module_id"],
                    life_item_id=proposal["created_life_item_id"],
                    status="accepted",
                )
            if proposal["status"] != "previewed":
                raise ValueError(f"Capture Proposal is not confirmable: {request.proposal_id}")

    created = _create_from_proposal(dict(proposal))

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE capture_proposals
                SET status = 'accepted',
                    created_life_item_id = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (created["life_item_id"], request.proposal_id),
            )

    return ConfirmCaptureProposalResponse(
        proposal_id=request.proposal_id,
        module_id=proposal["module_id"],
        life_item_id=created["life_item_id"],
        status="accepted",
    )


def _is_question_or_lookup(message: str) -> bool:
    text = message.strip().lower()
    if text.endswith("?"):
        return True
    first = text.split()[0] if text.split() else ""
    return first in {
        "what", "when", "where", "who", "why", "how", "which",
        "is", "are", "do", "does", "did", "can", "could", "should", "will",
    }


def _detect_capture_proposals(message: str) -> list[DetectedProposal]:
    explicit = _detect_explicit(message)
    if explicit:
        return [explicit]
    if _is_question_or_lookup(message):
        return []

    suggested = _detect_suggested_with_llm(message) or _detect_suggested(message)
    return [suggested] if suggested else []


def _detect_suggested_with_llm(message: str) -> DetectedProposal | None:
    system = (
        "You are Orbit's cheap Capture Proposal shape detector. Return only JSON. "
        "Detect whether the user message contains a clear Life-Item-Shaped Intent: "
        "a clear verb-object intent or durable life-data statement that maps to one "
        "module. Do not create suggestions for casual questions, greetings, or vague "
        "thinking. Never propose for questions or information lookups. Confidence must "
        "be one of low, medium, high and is a discrete bucket, not a probability."
    )
    prompt = f"""
Available modules:
- tasks: actionable work the person may complete
- logs: observations, updates, lightweight life events
- plans: multi-step intentions
- documents: durable reference text or notes
- goals: a durable aspiration or direction the person wants, distinct from an actionable task

Return JSON with this shape:
{{
  "has_intent": boolean,
  "module_id": "tasks" | "logs" | "plans" | "documents" | "goals" | null,
  "title": string,
  "description": string,
  "confidence_bucket": "low" | "medium" | "high",
  "horizon": "short_term" | "long_term",
  "target_note": string,
  "payload": object
}}

Message:
{message}
""".strip()
    try:
        data = generate_json(prompt, system=system, temperature=0.1, max_output_tokens=700)
    except (LLMUnavailable, Exception):
        return None

    if not data.get("has_intent"):
        return None
    module_id = data.get("module_id")
    if module_id not in {"tasks", "logs", "plans", "documents", "goals"}:
        return None
    confidence = data.get("confidence_bucket")
    if confidence not in {"low", "medium", "high"}:
        confidence = "medium"
    if confidence == "low":
        return None

    title = str(data.get("title") or _derive_title(message)).strip()
    description = str(data.get("description") or "").strip()
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    if module_id == "goals":
        horizon = data.get("horizon")
        if horizon not in {"short_term", "long_term"}:
            horizon = "long_term"
        target_note = str(data.get("target_note") or "").strip() or None
        payload = {**payload, "horizon": horizon, "target_note": target_note}
    proposal = _proposal_for_module(module_id, description or message, explicit=False)
    return proposal.model_copy(
        update={
            "title": _derive_title(title),
            "description": description,
            "payload": {**proposal.payload, **payload},
            "confidence_bucket": confidence,
            "explicit_request": False,
        }
    )


def _detect_explicit(message: str) -> DetectedProposal | None:
    patterns = [
        (r"(?:add|save)\s+(?:this\s+)?(?:to\s+)?tasks?\s*:?\s*(.+)", "tasks"),
        (r"(?:log|save)\s+(?:this\s+)?(?:to\s+)?logs?\s*:?\s*(.+)", "logs"),
        (r"(?:make|create|save)\s+(?:this\s+)?(?:as\s+)?(?:a\s+)?plans?\s*:?\s*(.+)", "plans"),
        (r"(?:save|add)\s+(?:this\s+)?(?:as\s+)?(?:a\s+)?documents?\s*:?\s*(.+)", "documents"),
        (r"(?:add|make|set)\s+(?:this\s+)?(?:as\s+)?(?:a\s+)?goals?\s*:?\s*(.+)", "goals"),
    ]
    for pattern, module_id in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return _proposal_for_module(module_id, match.group(1).strip(), explicit=True)
    return None


def _detect_suggested(message: str) -> DetectedProposal | None:
    lowered = message.lower()
    if any(marker in lowered for marker in ("i need to ", "i should ", "todo", "remind me to ")):
        return _proposal_for_module("tasks", message, explicit=False)
    if any(marker in lowered for marker in ("i noticed", "today i", "i learned", "note that")):
        return _proposal_for_module("logs", message, explicit=False)
    if "i need a plan" in lowered or "plan to " in lowered:
        return _proposal_for_module("plans", message, explicit=False)
    return None


def _proposal_for_module(module_id: str, text: str, *, explicit: bool) -> DetectedProposal:
    title = _derive_title(text)
    bucket: ConfidenceBucket = "high" if explicit or len(text.split()) >= 5 else "medium"
    if module_id == "logs":
        return DetectedProposal(
            module_id="logs",
            item_type="log",
            title=title,
            description=text,
            payload={"text": text},
            confidence_bucket=bucket,
            explicit_request=explicit,
        )
    if module_id == "tasks":
        return DetectedProposal(
            module_id="tasks",
            item_type="task",
            title=title,
            description="",
            payload={"module_status": None, "priority": None, "due_date": None},
            confidence_bucket=bucket,
            explicit_request=explicit,
        )
    if module_id == "plans":
        steps = _extract_plan_steps(text)
        return DetectedProposal(
            module_id="plans",
            item_type="plan",
            title=title,
            description=text,
            payload={"steps": steps},
            confidence_bucket=bucket,
            explicit_request=explicit,
        )
    if module_id == "goals":
        return DetectedProposal(
            module_id="goals",
            item_type="goal",
            title=title,
            description=text,
            payload={"horizon": "long_term"},
            confidence_bucket=bucket,
            explicit_request=explicit,
        )
    return DetectedProposal(
        module_id="documents",
        item_type="document",
        title=title,
        description=_derive_title(text, limit=160),
        payload={"original_name": f"{_slugify(title) or 'untitled_doc'}.md", "content": text},
        confidence_bucket=bucket,
        explicit_request=explicit,
    )


def _should_surface(session_id: str, proposal: DetectedProposal) -> bool:
    if proposal.explicit_request:
        return True

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT suggestion_threshold FROM modules WHERE id = %s", (proposal.module_id,))
            threshold = cur.fetchone()["suggestion_threshold"]
            if threshold is None:
                return False
            cur.execute("SELECT default_settings FROM modules WHERE id = 'chat'")
            chat_settings = cur.fetchone()["default_settings"]
            cur.execute("SELECT surfaced_suggestion_count FROM chat_sessions WHERE id = %s", (session_id,))
            surfaced_count = cur.fetchone()["surfaced_suggestion_count"]

    max_suggestions = chat_settings.get("max_suggestions_per_session", 2)
    return CONFIDENCE_SCORES[proposal.confidence_bucket] >= threshold and surfaced_count < max_suggestions


def _persist_preview(session_id: str, proposal: DetectedProposal) -> CaptureProposalPreview:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT retrieval_policy FROM modules WHERE id = %s", (proposal.module_id,))
            module = cur.fetchone()
            retrieval_policy = module["retrieval_policy"]
            cur.execute(
                """
                INSERT INTO capture_proposals (
                    session_id, module_id, item_type, title, description, payload,
                    source, confidence_bucket, confidence_score, explicit_request
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    session_id,
                    proposal.module_id,
                    proposal.item_type,
                    proposal.title,
                    proposal.description,
                    Jsonb(proposal.payload),
                    Jsonb({"kind": "chat_action"}),
                    proposal.confidence_bucket,
                    CONFIDENCE_SCORES[proposal.confidence_bucket],
                    proposal.explicit_request,
                ),
            )
            row = cur.fetchone()
            if not proposal.explicit_request:
                cur.execute(
                    """
                    UPDATE chat_sessions
                    SET surfaced_suggestion_count = surfaced_suggestion_count + 1,
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (session_id,),
                )

    return _row_to_preview(row, retrieval_policy)


def _create_from_proposal(proposal: dict[str, Any]) -> dict[str, UUID]:
    request_id = f"chat-proposal-{proposal['id']}"
    payload = proposal["payload"] or {}
    module_id = proposal["module_id"]

    if module_id == "logs":
        item = create_log(
            LogCreate(
                title=proposal["title"],
                text=payload.get("text") or proposal["description"],
                request_id=request_id,
                source={"kind": "chat_action", "proposal_id": str(proposal["id"])},
            )
        )
    elif module_id == "tasks":
        item = create_task(
            TaskCreate(
                title=proposal["title"],
                description=proposal["description"],
                due_date=payload.get("due_date"),
                priority=payload.get("priority"),
                module_status=payload.get("module_status"),
                request_id=request_id,
                source={"kind": "chat_action", "proposal_id": str(proposal["id"])},
            )
        )
    elif module_id == "plans":
        item = create_plan(
            PlanCreate(
                title=proposal["title"],
                description=proposal["description"],
                steps=[
                    PlanStepCreate(title=step["title"], description=step.get("description", ""))
                    for step in _normalize_plan_steps(payload.get("steps", []))
                ],
                request_id=request_id,
                source={"kind": "chat_action", "proposal_id": str(proposal["id"])},
            )
        )
    elif module_id == "documents":
        item = create_document(
            DocumentCreate(
                original_name=payload["original_name"],
                content=payload["content"],
                request_id=request_id,
                source={"kind": "chat_action", "proposal_id": str(proposal["id"])},
            )
        )
    else:
        raise ValueError(f"Unsupported proposal module: {module_id}")

    return {"life_item_id": item.id}


def _row_to_preview(row: dict[str, Any], retrieval_policy: dict[str, Any]) -> CaptureProposalPreview:
    return CaptureProposalPreview(
        id=row["id"],
        session_id=row["session_id"],
        module_id=row["module_id"],
        item_type=row["item_type"],
        title=row["title"],
        description=row["description"],
        payload=row["payload"],
        confidence_bucket=row["confidence_bucket"],
        confidence_score=row["confidence_score"],
        explicit_request=row["explicit_request"],
        should_create_chunks=bool(retrieval_policy.get("create_chunks", True)),
        should_create_bucket_update=bool(retrieval_policy.get("create_bucket_updates", True)),
        status=row["status"],
    )


def _mode_answer(mode: ChatMode, has_suggestion: bool) -> str:
    suffix = " I found a possible item to preview." if has_suggestion else ""
    if mode == "fast":
        return f"LLM is unavailable, so Fast Chat can only report retrieved knowledge right now.{suffix}"
    return f"LLM is unavailable, so Understanding Chat can only report routed context right now.{suffix}"


def _answer_prompt(
    request: ChatRequest,
    context: str,
    suggestions: list[CaptureProposalPreview],
) -> str:
    suggestion_context = "\n".join(
        f"- {proposal.module_id}: {proposal.title} ({proposal.confidence_bucket})"
        for proposal in suggestions
    ) or "None"
    return f"""
User message:
{request.message}

Mode:
{request.mode}

Available Orbit context:
{context}

Prepared Capture Proposal previews:
{suggestion_context}

Answer naturally as Orbit. If context is missing, say so plainly. Do not claim
that chat itself was stored as memory. If previews exist, briefly mention that
the user can save the preview; do not pressure them.
""".strip()


def _generate_chat_answer(
    request: ChatRequest,
    suggestions: list[CaptureProposalPreview],
) -> str:
    context = _build_answer_context(request.mode, request.message)
    system = _chat_system_prompt(request.mode)
    prompt = _answer_prompt(request, context, suggestions)
    try:
        return generate_text(
            prompt,
            system=system,
            temperature=0.45,
            max_output_tokens=2200 if request.mode == "understanding" else 1300,
        )
    except (LLMUnavailable, Exception):
        return _fallback_context_answer(request.mode, context, bool(suggestions))


def _chat_system_prompt(mode: ChatMode) -> str:
    base = (
        "You are Orbit, a personal AI advisor for one person. Be concise, grounded, "
        "and useful. Use the provided Story Buckets, Goals, module data, Connections, "
        "and Knowledge Chunks only as context; do not invent private facts."
    )
    if mode == "fast":
        return f"{base} This is Fast Chat: answer directly from retrieved knowledge; minimal assumptions."
    return (
        f"{base} This is Understanding Chat: use the selected Story Buckets to frame and personalize, "
        "but answer the user's actual question; do not wander."
    )


def _fallback_context_answer(mode: ChatMode, context: str, has_suggestion: bool) -> str:
    suffix = "\n\nI also found a possible item to preview." if has_suggestion else ""
    if mode == "fast":
        return _mode_answer(mode, has_suggestion)
    if not context.strip() or context == "No Orbit context found yet.":
        return f"LLM generation is unavailable, and I could not find relevant Orbit context for this turn.{suffix}"

    excerpts = _context_excerpts(context)
    if not excerpts:
        return f"LLM generation is unavailable, but Orbit did retrieve context for this turn.{suffix}"

    return (
        "LLM generation is unavailable, but Orbit did retrieve context for this turn.\n\n"
        + "\n\n".join(excerpts)
        + suffix
    )


def _context_excerpts(context: str, *, limit: int = 4) -> list[str]:
    lines = [line.strip() for line in context.splitlines() if line.strip()]
    chunk_lines = [line for line in lines if line.startswith("- From ")]
    module_lines = [line for line in lines if line.startswith("- [")]
    useful = chunk_lines + module_lines
    if not useful:
        useful = [line for line in lines if not line.endswith(":")]
    return [line[:700] for line in useful[:limit]]


def _build_answer_context(mode: ChatMode, message: str) -> str:
    if mode == "fast":
        sections = [_chunk_context(message, limit=4), _connection_context(message), _goal_context()]
        return "\n\n".join(s for s in sections if s.strip()) or "No Orbit context found yet."

    decision = _route_and_classify(message)
    chunks = _understanding_retrieval(message, decision, limit=8 if decision.breadth == "broad" else 4)
    return _build_understanding_context(message, decision, chunks)


def _build_understanding_context(
    message: str, decision: RouteDecision, chunks: list
) -> str:
    chunk_block = _chunks_to_context(chunks)
    sections = [
        chunk_block,
        _connection_context(message),
        _selected_bucket_context(decision.buckets),
        _goal_context(),
    ]
    return "\n\n".join(s for s in sections if s.strip()) or "No Orbit context found yet."


def _selected_bucket_context(keys: list[str]) -> str:
    if not keys:
        return ""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT display_name, description, content
                FROM story_buckets
                WHERE status='active' AND stable_key = ANY(%s)
                """,
                (keys,),
            )
            rows = cur.fetchall()
    if not rows:
        return ""
    lines = [
        f"- {r['display_name']}: {r['description']}\n{(r.get('content') or '')[:1400].strip()}"
        for r in rows
    ]
    return "Story Buckets:\n" + "\n".join(lines)


def _goal_context() -> str:
    goals = list_goals()
    if not goals:
        return ""
    return "Goals:\n" + "\n".join(
        f"- {goal.status}: {goal.title} ({goal.goal_id})\n{goal.body[:500]}"
        for goal in goals[:10]
    )


def _connection_context(message: str) -> str:
    tokens = set(_tokens(message))
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ic.target_type, ic.target_label, ic.connection_note, ic.strength, li.title
                FROM item_connections ic
                JOIN life_items li ON li.id = ic.source_life_item_id
                ORDER BY ic.created_at DESC
                LIMIT 30
                """
            )
            rows = cur.fetchall()

    scored = sorted(
        rows,
        key=lambda row: _overlap(tokens, f"{row['title']} {row['target_label']} {row['connection_note']}"),
        reverse=True,
    )[:8]
    if not scored:
        return ""
    return "Connections:\n" + "\n".join(
        f"- {row['title']} -> {row['target_type']} {row['target_label']} ({row['strength']}): {row['connection_note']}"
        for row in scored
    )


def _chunk_context(message: str, *, limit: int) -> str:
    chunks = retrieve_chunks(message, limit=limit)
    return _chunks_to_context(chunks)


def _chunks_to_context(chunks: list) -> str:
    if not chunks:
        return ""
    return "Knowledge Chunks:\n" + "\n".join(
        f"- From {chunk.title} [{chunk.source_type}, {chunk.retrieval_mode}, score={chunk.score:.3f}]: {chunk.content[:900]}"
        for chunk in chunks
    )


def _overlap(left_tokens: set[str], text: str) -> int:
    if not left_tokens:
        return 0
    return len(left_tokens & set(_tokens(text)))


def _extract_plan_steps(text: str) -> list[dict[str, str]]:
    lines = [
        re.sub(r"^[-*\d.\s]+", "", line).strip()
        for line in text.splitlines()
        if line.strip()
    ]
    if len(lines) <= 1:
        return [{"title": "Clarify next step", "description": text}]
    return [{"title": line, "description": ""} for line in lines[:10]]


def _normalize_plan_steps(raw_steps: Any) -> list[dict[str, str]]:
    if not isinstance(raw_steps, list):
        return []
    normalized = []
    for step in raw_steps[:12]:
        if isinstance(step, str):
            title = step.strip()
            description = ""
        elif isinstance(step, dict):
            title = str(step.get("title") or "").strip()
            description = str(step.get("description") or "").strip()
        else:
            continue
        if title:
            normalized.append({"title": title, "description": description})
    return normalized


def _derive_title(text: str, limit: int = 80) -> str:
    title = " ".join(text.strip().split())
    if len(title) <= limit:
        return title
    return f"{title[: limit - 3].rstrip()}..."


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    normalized = re.sub(r"_+", "_", normalized)
    if not normalized or not normalized[0].isalpha():
        return ""
    return normalized


def _bucket_catalog() -> list[dict[str, str]]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT stable_key, display_name, description FROM story_buckets WHERE status='active'"
            )
            return [dict(row) for row in cur.fetchall()]


def _route_and_classify(message: str) -> RouteDecision:
    catalog = _bucket_catalog()
    try:
        data = generate_json(
            _route_prompt(message, catalog),
            system=(
                "You route a personal-assistant query to the user's story buckets. "
                "Return only JSON. breadth is 'narrow' for specific questions and "
                "'broad' for wide/vague life questions. Pick 1-3 bucket keys. "
                "expansion_terms is non-empty ONLY when breadth is broad."
            ),
            temperature=0.1,
            max_output_tokens=400,
        )
        breadth = data.get("breadth")
        if breadth not in {"narrow", "broad"}:
            raise ValueError("bad breadth")
        buckets = [k for k in (data.get("buckets") or []) if k in KNOWN_BUCKET_KEYS][:3]
        terms = [str(t).strip() for t in (data.get("expansion_terms") or []) if str(t).strip()]
        if breadth == "narrow":
            terms = []
        if not buckets:
            buckets = _select_buckets_fallback(message, catalog)
        return RouteDecision(breadth=breadth, buckets=buckets, expansion_terms=terms,
                             rationale=str(data.get("rationale") or ""))
    except (LLMUnavailable, Exception):
        breadth = _breadth_fallback(message)
        return RouteDecision(
            breadth=breadth,
            buckets=_select_buckets_fallback(message, catalog),
            expansion_terms=[],
            rationale="lexical fallback",
        )


def _breadth_fallback(message: str) -> str:
    lowered = message.lower()
    if any(marker in lowered for marker in _BROAD_MARKERS):
        return "broad"
    return "broad" if len(_tokens(message)) <= 2 else "narrow"


def _select_buckets_fallback(message: str, catalog: list[dict[str, str]] | None = None) -> list[str]:
    catalog = catalog if catalog is not None else _bucket_catalog()
    tokens = set(_tokens(message))
    scored = sorted(
        catalog,
        key=lambda b: _overlap(tokens, f"{b['display_name']} {b['description']}"),
        reverse=True,
    )
    picked = [b["stable_key"] for b in scored if _overlap(tokens, f"{b['display_name']} {b['description']}") > 0][:3]
    return picked or [scored[0]["stable_key"]] if scored else []


def _sufficiency_check(message: str, chunks: list) -> tuple[bool, str]:
    """Return (sufficient, follow_up_query). Fallback: sufficient."""
    if not chunks:
        return True, ""
    summary = "\n".join(f"- {getattr(c, 'title', '')}: {getattr(c, 'content', '')[:200]}" for c in chunks[:6])
    try:
        data = generate_json(
            f'Query:\n{message}\n\nRetrieved:\n{summary}\n\n'
            'Return JSON: {"sufficient": bool, "follow_up_query": "" }. '
            'Only set sufficient=false if the retrieved context clearly misses '
            'something the query explicitly asked for.',
            system="You judge whether retrieved context answers the query. Return only JSON.",
            temperature=0.1,
            max_output_tokens=200,
        )
        sufficient = bool(data.get("sufficient", True))
        follow_up = str(data.get("follow_up_query") or "").strip()
        return (sufficient, "" if sufficient else follow_up)
    except (LLMUnavailable, Exception):
        return True, ""


def _understanding_retrieval(message: str, decision: RouteDecision, *, limit: int = 4) -> list:
    query = _retrieval_query(message, decision)
    chunks = retrieve_chunks(query, limit=limit)
    sufficient, follow_up = _sufficiency_check(message, chunks)
    if not sufficient and follow_up:
        extra = retrieve_chunks(follow_up, limit=limit)
        seen = {getattr(c, "id", id(c)) for c in chunks}
        chunks = chunks + [c for c in extra if getattr(c, "id", id(c)) not in seen]
    return chunks


def _retrieval_query(message: str, decision: RouteDecision) -> str:
    if decision.breadth == "broad" and decision.expansion_terms:
        return f"{message} " + " ".join(decision.expansion_terms)
    return message


def _route_prompt(message: str, catalog: list[dict[str, str]]) -> str:
    lines = "\n".join(f"- {b['stable_key']}: {b['display_name']} — {b['description']}" for b in catalog)
    return (
        "Buckets:\n" + lines + "\n\n"
        'Return JSON: {"breadth":"narrow|broad","buckets":["key"],'
        '"expansion_terms":["..."],"rationale":"one line"}\n\n'
        f"Query:\n{message}"
    )


def _tokens(text: str) -> list[str]:
    stopwords = {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "in", "into", "is", "it", "of", "on", "or", "the", "this", "to",
        "with", "what", "why", "how", "when", "where", "should", "could",
    }
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in stopwords
    ]
