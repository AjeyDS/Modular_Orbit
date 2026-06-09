"""Plan text parser for the modular Plans module."""

from __future__ import annotations

import hashlib
import re
import textwrap
from collections import OrderedDict
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.llm import LLMUnavailable, generate_json


MAX_DEPTH = 4
MAX_LEAVES = 500
MAX_CACHE_ENTRIES = 50
GROUP_KEYWORDS = re.compile(
    r"^(week|phase|step|module|day|part|section|unit|sprint|stage|domain|milestone|chapter|lesson)\b",
    re.I,
)


class ParsedPlanNode(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    children: list["ParsedPlanNode"] = Field(default_factory=list)


class ParsedPlanDraft(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: Literal["work", "learn", "personal"] = "personal"
    nodes: list[ParsedPlanNode]


class ParsePlanRequest(BaseModel):
    raw_text: str = Field(min_length=10, max_length=50000)


class PlanParseError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        raw_llm_output: str | None = None,
        validation_error: str | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_llm_output = raw_llm_output
        self.validation_error = validation_error


ParsedPlanNode.model_rebuild()

_cache: OrderedDict[str, ParsedPlanDraft] = OrderedDict()

SYSTEM_PROMPT = """Extract the structure of a study, work, or personal plan into a nested JSON tree.
Preserve text verbatim. Do not rephrase, summarize, improve, or invent work; only extract structure.

Return JSON only with this schema:
{
  "title": "string",
  "category": "work | learn | personal",
  "nodes": [
    {
      "title": "string",
      "description": "string | null",
      "metadata": {},
      "children": []
    }
  ]
}

Example 1:
RAW INPUT:
LeetCode Blind 75 Prep Plan

Week 1: Arrays + Hashing
Day 1
- Two Sum
- Contains Duplicate
Learn: HashMap counting and collision intuition
Day 2
- Product of Array Except Self
- Valid Anagram

EXPECTED JSON:
{
  "title": "LeetCode Blind 75 Prep Plan",
  "category": "learn",
  "nodes": [
    {
      "title": "Week 1: Arrays + Hashing",
      "description": null,
      "metadata": {},
      "children": [
        {
          "title": "Day 1",
          "description": "Learn: HashMap counting and collision intuition",
          "metadata": {},
          "children": [
            {"title": "Two Sum", "description": null, "metadata": {}, "children": []},
            {"title": "Contains Duplicate", "description": null, "metadata": {}, "children": []}
          ]
        },
        {
          "title": "Day 2",
          "description": null,
          "metadata": {},
          "children": [
            {"title": "Product of Array Except Self", "description": null, "metadata": {}, "children": []},
            {"title": "Valid Anagram", "description": null, "metadata": {}, "children": []}
          ]
        }
      ]
    }
  ]
}

Example 2:
RAW INPUT:
AWS Certified Data Engineer Study Plan

Domain 1: Data Ingestion & Transformation (34%)
- AWS Glue — ETL jobs, Glue Studio, crawlers, Data Catalog
- Amazon Kinesis — Kinesis Data Streams, Firehose, Data Analytics
Domain 2: Data Store Management (26%)
- Amazon S3 — storage classes, lifecycle policies, partitioning
- Amazon Redshift — distribution styles, sort keys, Spectrum

EXPECTED JSON:
{
  "title": "AWS Certified Data Engineer Study Plan",
  "category": "learn",
  "nodes": [
    {
      "title": "Domain 1: Data Ingestion & Transformation (34%)",
      "description": null,
      "metadata": {},
      "children": [
        {"title": "AWS Glue", "description": "ETL jobs, Glue Studio, crawlers, Data Catalog", "metadata": {}, "children": []},
        {"title": "Amazon Kinesis", "description": "Kinesis Data Streams, Firehose, Data Analytics", "metadata": {}, "children": []}
      ]
    },
    {
      "title": "Domain 2: Data Store Management (26%)",
      "description": null,
      "metadata": {},
      "children": [
        {"title": "Amazon S3", "description": "storage classes, lifecycle policies, partitioning", "metadata": {}, "children": []},
        {"title": "Amazon Redshift", "description": "distribution styles, sort keys, Spectrum", "metadata": {}, "children": []}
      ]
    }
  ]
}

Rules:
- Only leaf nodes with no children represent actionable tasks.
- Group headers such as weeks, days, domains, phases, milestones, and sections are non-leaf nodes with children.
- Bullets immediately below a heading belong under that heading even if the bullets are not indented.
- Put supporting text such as "Learn:" or notes in the parent description, not as separate children.
- Use metadata only for obvious structured extras; otherwise {} is fine.
- Category inference: coding, ML, certification, or study plans are learn; deliverables and projects are work; otherwise personal.
- Max depth is 4 levels.
- If the input is not a plan, return {"title":"Imported Plan","category":"personal","nodes":[]}.
"""


def parse_plan_text(raw_text: str) -> ParsedPlanDraft:
    """Parse pasted plan text using LLM JSON, with deterministic fallback."""
    cache_key = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    cached = _cache.get(cache_key)
    if cached:
        _cache.move_to_end(cache_key)
        return cached

    heuristic_draft = _heuristic_parse(raw_text)
    raw_llm_output: str | None = None
    validation_error: str | None = None
    try:
        payload = generate_json(
            f"RAW PLAN INPUT:\n{raw_text}",
            system=SYSTEM_PROMPT,
            temperature=0.1,
            max_output_tokens=16000,
        )
        raw_llm_output = str(payload)
        draft = ParsedPlanDraft.model_validate(payload)
    except (LLMUnavailable, Exception) as exc:
        validation_error = str(exc)
        draft = heuristic_draft

    try:
        _validate_draft(draft)
    except (ValidationError, ValueError) as exc:
        raise PlanParseError(
            "Could not extract a usable plan from this text.",
            raw_llm_output=raw_llm_output,
            validation_error=str(exc) or validation_error,
        ) from exc

    if draft is not heuristic_draft and _should_prefer_heuristic(raw_text, draft, heuristic_draft):
        draft = heuristic_draft

    _cache[cache_key] = draft
    _cache.move_to_end(cache_key)
    while len(_cache) > MAX_CACHE_ENTRIES:
        _cache.popitem(last=False)
    return draft


def _validate_draft(draft: ParsedPlanDraft) -> None:
    if not draft.nodes:
        raise ValueError("Parsed plan contains no steps.")

    leaves = 0

    def walk(nodes: list[ParsedPlanNode], depth: int) -> None:
        nonlocal leaves
        if depth > MAX_DEPTH:
            raise ValueError(f"Plan depth exceeds {MAX_DEPTH}.")
        for node in nodes:
            node.title = node.title.strip()
            if not node.title:
                raise ValueError("Plan step title cannot be empty.")
            if node.children:
                walk(node.children, depth + 1)
            else:
                leaves += 1
                if leaves > MAX_LEAVES:
                    raise ValueError(f"Plan has more than {MAX_LEAVES} leaf steps.")

    walk(draft.nodes, 1)
    if leaves == 0:
        raise ValueError("Plan must contain at least one leaf step.")


def _should_prefer_heuristic(
    raw_text: str,
    llm_draft: ParsedPlanDraft,
    heuristic_draft: ParsedPlanDraft,
) -> bool:
    """Guard against sparse LLM parses that keep headings but drop child tasks."""
    heuristic_leaves = _leaf_count(heuristic_draft.nodes)
    llm_leaves = _leaf_count(llm_draft.nodes)
    if heuristic_leaves <= llm_leaves:
        return False

    actionable_lines = _actionable_line_count(raw_text)
    if actionable_lines >= 2 and llm_leaves < actionable_lines and heuristic_leaves >= actionable_lines:
        return True

    # If the heuristic found a real tree and the LLM returned mostly top-level
    # leaves, prefer the tree. This fixes "headings only" parses.
    return _max_depth(heuristic_draft.nodes) > _max_depth(llm_draft.nodes) and llm_leaves <= max(1, heuristic_leaves // 2)


def _leaf_count(nodes: list[ParsedPlanNode]) -> int:
    return sum(_leaf_count(node.children) if node.children else 1 for node in nodes)


def _max_depth(nodes: list[ParsedPlanNode], depth: int = 1) -> int:
    if not nodes:
        return 0
    return max(_max_depth(node.children, depth + 1) if node.children else depth for node in nodes)


def _actionable_line_count(raw_text: str) -> int:
    count = 0
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^[-*•]\s+\S+", line) or re.match(r"^\d+(?:\.\d+)*[.)]?\s+\S+", line):
            count += 1
    return count


def _heuristic_parse(raw_text: str) -> ParsedPlanDraft:
    lines = [line.rstrip() for line in textwrap.dedent(raw_text).splitlines()]
    title = _derive_title(lines)
    category = _infer_category(raw_text)
    roots: list[ParsedPlanNode] = []
    stack: list[tuple[int, ParsedPlanNode, str]] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        level, text, kind = _parse_plan_line(line)
        if not text or text.lower() == title.lower():
            continue
        node = _node_from_text(text)

        if kind == "support" and stack:
            parent = stack[-1][1]
            parent.description = _append_description(parent.description, text)
            continue

        if kind == "bullet":
            parent_index = _nearest_group_parent_index(stack)
            if parent_index is not None and level <= stack[parent_index][0]:
                level = min(stack[parent_index][0] + 1, MAX_DEPTH)

        if level <= 1 or not stack:
            roots.append(node)
            stack = [(level, node, kind)]
            continue
        while stack and stack[-1][0] >= level:
            stack.pop()
        if stack:
            stack[-1][1].children.append(node)
        else:
            roots.append(node)
        stack.append((level, node, kind))

    if not roots:
        sentences = [part.strip() for part in re.split(r"[.\n]", raw_text) if len(part.strip()) > 8]
        roots = [ParsedPlanNode(title=sentence[:160]) for sentence in sentences[:12]]

    return ParsedPlanDraft(title=title or "Imported Plan", category=category, nodes=roots)


def _derive_title(lines: list[str]) -> str:
    for line in lines:
        stripped = line.strip().strip("#").strip()
        if stripped:
            return _clean_line(stripped)[:200] or "Imported Plan"
    return "Imported Plan"


def _parse_plan_line(line: str) -> tuple[int, str, str]:
    heading = re.match(r"^\s*(#{1,4})\s+(.+)$", line)
    if heading:
        return len(heading.group(1)), _clean_line(heading.group(2)), "heading"

    numbered = re.match(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+(.+)$", line)
    if numbered:
        return numbered.group(1).count(".") + 1, _clean_line(numbered.group(2)), "numbered"

    bullet = re.match(r"^(\s*)[-*•]\s+(.+)$", line)
    if bullet:
        return min((len(bullet.group(1)) // 2) + 1, MAX_DEPTH), _clean_line(bullet.group(2)), "bullet"

    group = re.match(
        r"^\s*((?:week|phase|step|module|day|part|section|unit|sprint|stage|domain|milestone|chapter|lesson)\s+\d+(?:\.\d+)*)\b(.*)$",
        line,
        re.I,
    )
    if group:
        return group.group(1).count(".") + 1, _clean_line(line), "plain"

    if re.match(r"^\s*(learn|note|notes|focus|goal|outcome|objective)\s*:", line, re.I):
        return MAX_DEPTH, _clean_line(line), "support"

    return 1, _clean_line(line), "plain"


def _node_from_text(text: str) -> ParsedPlanNode:
    for separator in (" — ", " – "):
        if separator in text:
            title, description = text.split(separator, 1)
            return ParsedPlanNode(title=title.strip(), description=description.strip() or None, children=[])
    return ParsedPlanNode(title=text, children=[])


def _append_description(current: str | None, text: str) -> str:
    if not current:
        return text
    return f"{current}\n{text}"


def _nearest_group_parent_index(stack: list[tuple[int, ParsedPlanNode, str]]) -> int | None:
    for index in range(len(stack) - 1, -1, -1):
        _level, node, kind = stack[index]
        if kind in {"heading", "plain"} or GROUP_KEYWORDS.match(node.title):
            return index
    return None


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip(" :-\t")


def _infer_category(text: str) -> Literal["work", "learn", "personal"]:
    lowered = text.lower()
    if any(word in lowered for word in ("study", "learn", "course", "certification", "coding", "machine learning", "exam")):
        return "learn"
    if any(word in lowered for word in ("project", "deliverable", "client", "launch", "work", "stakeholder")):
        return "work"
    return "personal"
