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
_FOCUS_MARKERS = (
    "focus on",
    "what should i do",
    "what should i focus",
    "prioritize",
    "priorities",
    "plan my day",
    "what now",
    "where should i start",
    "how should i spend",
    "what's important",
    "whats important",
)
_ACTIONABLE_MODULES = frozenset({"tasks", "plans", "routines", "goals"})
_QUESTION_TYPES = frozenset({"lookup", "gap_analysis", "prioritize", "how_to", "reflection", "open"})
_FOCUS_APPROACH = (
    "If the user asks what to focus on or how to prioritize, use the Structured data "
    "to RANK concrete items (tasks, plans, routines) by urgency (soonest or overdue "
    "due dates first), then priority, then alignment to active goals. Recommend an "
    "ordered short list (top 3), each with a one-line reason, leading with the single "
    "most important. Decide; don't just describe."
)
_GAP_APPROACH = (
    "When the person asks what to learn, improve, or do next, don't just recombine "
    "what they already have. Compare their current skills, projects, and routines "
    "against what their goals typically require, and surface 1–3 concrete things "
    "they have NOT already listed (a real gap), each with a one-line why. Suggest "
    "skill areas, topics, and types of resources — do not fabricate specific course "
    "names, products, or links."
)
_DEFAULT_APPROACH = (
    "Answer the user's actual question directly using the retrieved context. "
    "Be concise and grounded."
)
_ADVICE_MARKERS = (
    "what can i learn",
    "what should i learn",
    "what to learn",
    "what am i missing",
    "how do i improve",
    "how can i improve",
    "level up",
    "fuel my career",
    "make the most",
    "what's next",
    "whats next",
    "what should i do next",
)
QUERYABLE_MODULES = frozenset({"tasks", "plans", "goals", "routines"})


@dataclass
class RouteDecision:
    breadth: str  # "narrow" | "broad"
    buckets: list[str] = field(default_factory=list)
    expansion_terms: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    rationale: str = ""


@dataclass
class ThinkingPlan:
    question_type: str = "open"
    approach: str = ""
    retrieval_hint: str = ""

CONFIDENCE_SCORES: dict[ConfidenceBucket, float] = {
    "low": 0.3,
    "medium": 0.65,
    "high": 0.9,
}


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    mode: ChatMode = "understanding"
    message: str = Field(min_length=1)


SourceKind = Literal["document", "item", "bucket", "module"]


class SourceRef(BaseModel):
    kind: SourceKind
    label: str


_MODULE_LABELS = {"tasks": "Tasks", "plans": "Plans", "goals": "Goals", "routines": "Routines"}


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
    sources: list[SourceRef] = []


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

    answer, sources = _generate_chat_answer(request, suggestions)

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
        sources=sources,
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

    chunks: list = []
    decision: RouteDecision | None = None
    if request.mode == "understanding":
        yield {"stage": "routing"}
        decision = _route_and_classify(request.message)
        if decision.modules:
            yield {"stage": "checking_state"}
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
        context, chunks, decision = _prepare_chat_context(request.mode, request.message)

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

    sources = _collect_sources(chunks, decision)
    yield {
        "stage": "done",
        "suggestions": suggestions_json or [],
        "sources": [source.model_dump() for source in sources],
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
            if proposal["status"] == "accepted":
                if proposal["module_id"] == "goals" and proposal.get("created_goal_id"):
                    return ConfirmCaptureProposalResponse(
                        proposal_id=proposal["id"],
                        module_id=proposal["module_id"],
                        goal_id=proposal["created_goal_id"],
                        status="accepted",
                    )
                if proposal["created_life_item_id"] is not None:
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
            if proposal["module_id"] == "goals":
                cur.execute(
                    """
                    UPDATE capture_proposals
                    SET status = 'accepted',
                        created_goal_id = %s,
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (created["goal_id"], request.proposal_id),
                )
            else:
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

    if proposal["module_id"] == "goals":
        return ConfirmCaptureProposalResponse(
            proposal_id=request.proposal_id,
            module_id=proposal["module_id"],
            goal_id=created["goal_id"],
            status="accepted",
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


def _create_from_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
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
    elif module_id == "goals":
        goal = create_goal(
            title=proposal["title"],
            body=proposal["description"],
            status="tentative",
            horizon=payload.get("horizon", "long_term"),
            target_note=payload.get("target_note"),
        )
        return {"goal_id": goal.goal_id}
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
) -> tuple[str, list[SourceRef]]:
    context, chunks, decision = _prepare_chat_context(request.mode, request.message)
    sources = _collect_sources(chunks, decision)
    system = _chat_system_prompt(request.mode)
    prompt = _answer_prompt(request, context, suggestions)
    try:
        answer = generate_text(
            prompt,
            system=system,
            temperature=0.45,
            max_output_tokens=2200 if request.mode == "understanding" else 1300,
        )
    except (LLMUnavailable, Exception):
        answer = _fallback_context_answer(request.mode, context, bool(suggestions))
    return answer, sources


def _chat_system_prompt(mode: ChatMode) -> str:
    formatting = (
        "Format cleanly: short paragraphs; use bullet lists only when they genuinely help; "
        "avoid heavy bolding and stacked headings; at most one bullet level."
    )
    base = (
        "You are Orbit, a personal AI advisor for one person. Be concise, grounded, "
        "and useful. The provided Story Buckets, Goals, module data, Connections, "
        "and Knowledge Chunks are the source of truth for facts ABOUT THE PERSON — "
        "never invent or guess personal facts. You MAY and SHOULD contribute general "
        "world knowledge, opinions, and gap analysis (skills, learning paths, what's "
        "commonly needed for the person's goals), framed clearly as suggestions, "
        "never as facts about the person. "
        f"{formatting} "
        "Render values in plain, natural language. Do not echo raw field names or status "
        "codes verbatim (e.g. 'Admit Until Date: D/S'); translate them ('admitted for "
        "duration of status') or omit if unclear."
    )
    if mode == "fast":
        return f"{base} This is Fast Chat: answer directly from retrieved knowledge; minimal assumptions."
    return (
        f"{base} This is Understanding Chat: use the selected Story Buckets to frame and personalize, "
        "but answer the user's actual question; do not wander. "
        "If the user asks what to focus on or how to prioritize, use the Structured data "
        "to RANK concrete items (tasks, plans, routines) by urgency (soonest or overdue "
        "due dates first), then priority, then alignment to active goals. Recommend an "
        "ordered short list (top 3), each with a one-line reason, leading with the single "
        "most important. Decide; don't just describe. "
        "When the person asks what to learn, improve, or do next, don't just recombine "
        "what they already have. Compare their current skills, projects, and routines "
        "against what their goals typically require, and surface 1–3 concrete things "
        "they have NOT already listed (a real gap), each with a one-line why. Suggest "
        "skill areas, topics, and types of resources — do not fabricate specific course "
        "names, products, or links."
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


def _collect_sources(chunks: list, decision: RouteDecision | None = None) -> list[SourceRef]:
    refs: list[SourceRef] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: SourceKind, label: str) -> None:
        normalized = (label or "").strip()
        if not normalized or (kind, normalized.lower()) in seen:
            return
        seen.add((kind, normalized.lower()))
        refs.append(SourceRef(kind=kind, label=normalized))

    for chunk in (chunks or [])[:6]:
        kind: SourceKind = "document" if getattr(chunk, "source_type", "") == "document" else "item"
        add(kind, getattr(chunk, "title", ""))
    if decision is not None:
        for bucket in getattr(decision, "buckets", []) or []:
            add("bucket", bucket)
        for module in getattr(decision, "modules", []) or []:
            add("module", _MODULE_LABELS.get(module, module))
    return refs


def _structured_tasks_context() -> str:
    from app.modules.tasks import list_tasks

    tasks = list_tasks(status="active", limit=10)
    if not tasks:
        return ""

    def key(t):
        return (t.due_date is None, t.due_date)

    lines = [
        f"- {t.title} — due {t.due_date or 'none'}, priority {t.priority or '-'}, {t.module_status or 'active'}"
        for t in sorted(tasks, key=key)
    ]
    return "Tasks:\n" + "\n".join(lines)


def _structured_plans_context() -> str:
    from app.modules.plans import list_plans

    plans = list_plans(status="active")
    if not plans:
        return ""
    return "Plans:\n" + "\n".join(
        f"- {p.title} — {p.completed_steps}/{p.total_steps} steps ({p.progress_percent}%)"
        for p in plans
    )


def _structured_goals_context() -> str:
    from app.user_model.goals import list_goals as list_structured_goals

    goals = list_structured_goals()
    if not goals:
        return ""
    return "Goals:\n" + "\n".join(
        f"- {g.status}/{g.horizon}: {g.title}"
        + (f" — target {g.target_note or g.target_date}" if (g.target_note or g.target_date) else "")
        for g in goals[:10]
    )


def _structured_routines_context() -> str:
    from app.modules.routine import list_routine_state

    state = list_routine_state()
    if not state.items:
        return ""
    return "Routines:\n" + "\n".join(
        f"- {it.title} — streak {it.streak_count}, today: {'done' if it.today_completed else 'not done'}"
        for it in state.items[:10]
    )


_STRUCTURED = {
    "tasks": _structured_tasks_context,
    "plans": _structured_plans_context,
    "goals": _structured_goals_context,
    "routines": _structured_routines_context,
}


def _structured_context(modules: list[str]) -> str:
    blocks: list[str] = []
    for module in modules:
        fn = _STRUCTURED.get(module)
        if fn is None:
            continue
        try:
            block = fn()
        except Exception:
            block = ""
        if block:
            blocks.append(block)
    if not blocks:
        return ""
    return "Structured data:\n" + "\n\n".join(blocks)


def _prepare_chat_context(
    mode: ChatMode, message: str
) -> tuple[str, list, RouteDecision | None]:
    if mode == "fast":
        chunks = retrieve_chunks(message, limit=4)
        sections = [_chunks_to_context(chunks), _connection_context(message), _goal_context()]
        context = "\n\n".join(s for s in sections if s.strip()) or "No Orbit context found yet."
        return context, chunks, None

    decision = _route_and_classify(message)
    chunks = _understanding_retrieval(message, decision, limit=8 if decision.breadth == "broad" else 4)
    context = _build_understanding_context(message, decision, chunks)
    return context, chunks, decision


def _build_answer_context(mode: ChatMode, message: str) -> str:
    context, _, _ = _prepare_chat_context(mode, message)
    return context


def _build_understanding_context(
    message: str, decision: RouteDecision, chunks: list
) -> str:
    chunk_block = _chunks_to_context(chunks)
    structured = _structured_context(decision.modules)
    sections = [
        chunk_block,
        structured,
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


def _user_model_index() -> str:
    catalog = _bucket_catalog()
    bucket_lines = [f"- {row['display_name']}: {row['description']}" for row in catalog]
    goals = list_goals()
    goal_lines = [f"- {goal.status}/{goal.horizon}: {goal.title}" for goal in goals[:10]]
    modules = ", ".join(sorted(QUERYABLE_MODULES))
    sections = [
        "Story buckets:\n" + "\n".join(bucket_lines) if bucket_lines else "",
        "Goals:\n" + "\n".join(goal_lines) if goal_lines else "",
        f"Queryable modules: {modules}",
        "Recent activity: logs, tasks, plans, documents, and routines appear in structured data when retrieved.",
    ]
    return "\n\n".join(section for section in sections if section.strip())


def _think(message: str) -> ThinkingPlan:
    try:
        data = generate_json(
            f"Question:\n{message}\n\nUser model index:\n{_user_model_index()}\n\n"
            'Return JSON: {"question_type":"lookup|gap_analysis|prioritize|how_to|reflection|open",'
            '"approach":"how to tackle THIS question and what a great answer looks like",'
            '"retrieval_hint":"which life areas/modules/data to pull and why"}',
            system=(
                "You plan how to answer a personal-assistant question. Think about the person's "
                "context and what a great answer needs. Return only JSON."
            ),
            temperature=0.2,
            max_output_tokens=350,
        )
        question_type = data.get("question_type")
        if question_type not in _QUESTION_TYPES:
            question_type = "open"
        approach = str(data.get("approach") or "").strip()
        if not approach:
            raise ValueError("empty approach")
        return ThinkingPlan(
            question_type=str(question_type),
            approach=approach,
            retrieval_hint=str(data.get("retrieval_hint") or "").strip(),
        )
    except (LLMUnavailable, Exception):
        return _think_fallback(message)


def _think_fallback(message: str) -> ThinkingPlan:
    if _is_focus_query(message):
        return ThinkingPlan("prioritize", _FOCUS_APPROACH, "tasks, plans, routines, goals")
    if _is_advice_query(message):
        return ThinkingPlan("gap_analysis", _GAP_APPROACH, "tasks, plans, routines, goals, career")
    return ThinkingPlan("open", _DEFAULT_APPROACH, "")


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
        modules = [
            m for m in (data.get("modules") or [])
            if isinstance(m, str) and m in QUERYABLE_MODULES
        ]
        if not modules:
            modules = _modules_fallback(message)
        return _finalize_route_decision(
            message,
            breadth=breadth,
            buckets=buckets,
            expansion_terms=terms,
            modules=modules,
            rationale=str(data.get("rationale") or ""),
        )
    except (LLMUnavailable, Exception):
        breadth = _breadth_fallback(message)
        return _finalize_route_decision(
            message,
            breadth=breadth,
            buckets=_select_buckets_fallback(message, catalog),
            expansion_terms=[],
            modules=_modules_fallback(message),
            rationale="lexical fallback",
        )


def _is_focus_query(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _FOCUS_MARKERS)


def _is_advice_query(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _ADVICE_MARKERS)


def _finalize_route_decision(
    message: str,
    *,
    breadth: str,
    buckets: list[str],
    expansion_terms: list[str],
    modules: list[str],
    rationale: str,
) -> RouteDecision:
    if _is_focus_query(message) or _is_advice_query(message):
        modules = sorted(set(modules) | _ACTIONABLE_MODULES)
        breadth = "broad"
    return RouteDecision(
        breadth=breadth,
        buckets=buckets,
        expansion_terms=expansion_terms,
        modules=modules,
        rationale=rationale,
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


def _modules_fallback(message: str) -> list[str]:
    lowered = message.lower()
    modules: list[str] = []
    if re.search(r"\b(due|overdue|task|todo)\b", lowered):
        modules.append("tasks")
    if re.search(r"\b(plan|progress|step|milestone)\b", lowered):
        modules.append("plans")
    if re.search(r"(goal|aspir|aiming)", lowered):
        modules.append("goals")
    if re.search(r"\b(routine|habit|streak|daily)\b", lowered):
        modules.append("routines")
    return modules


def _route_prompt(message: str, catalog: list[dict[str, str]]) -> str:
    queryable = ", ".join(sorted(QUERYABLE_MODULES))
    lines = "\n".join(f"- {b['stable_key']}: {b['display_name']} — {b['description']}" for b in catalog)
    return (
        "Buckets:\n" + lines + "\n\n"
        f"Queryable modules: {queryable}. Pick modules whose structured data would help answer "
        "the query, or [] if none.\n\n"
        'Return JSON: {"breadth":"narrow|broad","buckets":["key"],'
        '"expansion_terms":["..."],"modules":["tasks|plans|goals|routines"],'
        '"rationale":"one line"}\n\n'
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
