"""Output-heavy modules: Recommendations and Strategies."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from app.db import transaction
from app.lifecycle import LifeItemError, create_life_item, review_life_item


OutputModuleId = Literal["recommendations", "strategies"]
GeneratedOutputStatus = Literal["draft", "accepted", "rejected"]


class GenerateOutputRequest(BaseModel):
    prompt: str = Field(min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)


class GeneratedOutputItem(BaseModel):
    id: UUID
    module_id: OutputModuleId
    prompt: str
    output_text: str
    payload: dict[str, Any]
    status: GeneratedOutputStatus
    retry_of: UUID | None
    created_life_item_id: UUID | None
    created_at: datetime
    updated_at: datetime


class AcceptGeneratedOutputResponse(BaseModel):
    output: GeneratedOutputItem
    life_item_id: UUID


def generate_output(
    module_id: OutputModuleId,
    request: GenerateOutputRequest,
    *,
    retry_of: UUID | str | None = None,
) -> GeneratedOutputItem:
    output_text = _deterministic_output(module_id, request.prompt, request.context, retry_of=retry_of)
    payload = _payload_for_output(module_id, request.prompt, output_text, request.context)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO generated_outputs (
                    module_id, prompt, output_text, payload, retry_of
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (module_id, request.prompt, output_text, Jsonb(payload), retry_of),
            )
            return _row_to_output(cur.fetchone())


def retry_generated_output(output_id: UUID | str) -> GeneratedOutputItem:
    original = get_generated_output(output_id)
    return generate_output(
        original.module_id,
        GenerateOutputRequest(prompt=original.prompt, context=original.payload.get("context", {})),
        retry_of=original.id,
    )


def accept_generated_output(output_id: UUID | str) -> AcceptGeneratedOutputResponse:
    output = get_generated_output(output_id)
    if output.status == "accepted" and output.created_life_item_id is not None:
        return AcceptGeneratedOutputResponse(output=output, life_item_id=output.created_life_item_id)
    if output.status != "draft":
        raise LifeItemError(f"Generated output is not accept-ready: {output_id}")

    result = create_life_item(
        module_id=output.module_id,
        item_type="strategy" if output.module_id == "strategies" else "recommendation",
        title=output.payload["title"],
        description=output.output_text,
        payload={
            "prompt": output.prompt,
            "output_text": output.output_text,
            **output.payload,
        },
        source={
            "kind": "generated_output",
            "generated_output_id": str(output.id),
        },
        request_id=f"generated-output-{output.id}",
    )

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO knowledge_chunks (life_item_id, content, source_type, metadata)
                VALUES (%s, %s, 'accepted_output', %s)
                """,
                (
                    result.item["id"],
                    output.output_text,
                    Jsonb({"module_id": output.module_id, "generated_output_id": str(output.id)}),
                ),
            )
            cur.execute(
                """
                UPDATE generated_outputs
                SET status = 'accepted',
                    created_life_item_id = %s,
                    updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (result.item["id"], output.id),
            )
            accepted = _row_to_output(cur.fetchone())

    try:
        review_life_item(result.item["id"])
    except Exception:
        pass

    return AcceptGeneratedOutputResponse(output=accepted, life_item_id=result.item["id"])


def reject_generated_output(output_id: UUID | str) -> GeneratedOutputItem:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE generated_outputs
                SET status = 'rejected', updated_at = now()
                WHERE id = %s AND status = 'draft'
                RETURNING *
                """,
                (output_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise LifeItemError(f"Generated output is not reject-ready: {output_id}")
            return _row_to_output(row)


def get_generated_output(output_id: UUID | str) -> GeneratedOutputItem:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM generated_outputs WHERE id = %s", (output_id,))
            row = cur.fetchone()
            if row is None:
                raise LifeItemError(f"Unknown Generated Output: {output_id}")
            return _row_to_output(row)


def list_generated_outputs(
    module_id: OutputModuleId,
    *,
    status: GeneratedOutputStatus | None = None,
    limit: int = 50,
) -> list[GeneratedOutputItem]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM generated_outputs
                WHERE module_id = %(module_id)s
                    AND (%(status)s::text IS NULL OR status = %(status)s)
                ORDER BY created_at DESC
                LIMIT %(limit)s
                """,
                {"module_id": module_id, "status": status, "limit": limit},
            )
            return [_row_to_output(row) for row in cur.fetchall()]


def _row_to_output(row: dict[str, Any]) -> GeneratedOutputItem:
    return GeneratedOutputItem(
        id=row["id"],
        module_id=row["module_id"],
        prompt=row["prompt"],
        output_text=row["output_text"],
        payload=row["payload"],
        status=row["status"],
        retry_of=row["retry_of"],
        created_life_item_id=row["created_life_item_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _deterministic_output(
    module_id: OutputModuleId,
    prompt: str,
    context: dict[str, Any],
    *,
    retry_of: UUID | str | None,
) -> str:
    retry_line = "\nRevision: retry with tighter wording." if retry_of else ""
    if module_id == "strategies":
        horizon = context.get("time_horizon", "this week")
        return (
            f"Strategy for {horizon}: focus on the highest-leverage work described in '{prompt}'.\n"
            "1. Pick one primary outcome.\n"
            "2. Protect time for the hardest step.\n"
            "3. Review progress before adding more work."
            f"{retry_line}"
        )
    return (
        f"Recommendation: based on '{prompt}', choose the option with the clearest next action.\n"
        "Why: it reduces ambiguity and makes follow-through easier.\n"
        "Next: turn the recommendation into a Task or Strategy if it remains useful."
        f"{retry_line}"
    )


def _payload_for_output(
    module_id: OutputModuleId,
    prompt: str,
    output_text: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    title = _title_from_prompt(module_id, prompt)
    return {
        "title": title,
        "context": context,
        "summary": output_text.splitlines()[0],
    }


def _title_from_prompt(module_id: OutputModuleId, prompt: str) -> str:
    prefix = "Strategy" if module_id == "strategies" else "Recommendation"
    compact = " ".join(prompt.split())
    if len(compact) > 72:
        compact = f"{compact[:69].rstrip()}..."
    return f"{prefix}: {compact}"
