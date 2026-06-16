"""Assemble the User Model feed: woven doc + unwoven tail."""
from __future__ import annotations

from psycopg import Connection

from app.user_model.facts import list_unwoven_facts
from app.user_model.weave import current_woven_doc


def build_user_model_context(
    *,
    budget: int = 4000,
    tail_limit: int = 8,
    conn: Connection | None = None,
) -> str:
    doc = current_woven_doc(conn)
    facts = list_unwoven_facts(conn)

    parts: list[str] = []
    if doc and doc.get("content", "").strip():
        content = doc["content"].strip()
        if len(content) > budget:
            content = content[:budget].rstrip()
        parts.append(content)

    if facts:
        newest = list(reversed(facts))[:tail_limit]  # facts are oldest-first
        lines = "\n".join(f"- [{f['source']}] {f['text']}" for f in newest)
        parts.append(f"## Recently (not yet woven)\n{lines}")

    return "\n\n".join(parts)
