"""Small Gemini-backed LLM adapter for Modular Orbit.

The app's lifecycle stays orchestrated by Python services. This module only
executes bounded model calls and returns plain text or parsed JSON.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from google import genai
from google.genai import types

from app.core.config import settings


class LLMUnavailable(RuntimeError):
    """Raised when a model call is intentionally disabled or unavailable."""


def llm_enabled() -> bool:
    """Return whether live LLM calls should run in this process."""
    if settings.llm_mode in {"mock", "off"}:
        return False
    if settings.llm_mode == "real":
        return bool(settings.gemini_api_key)
    if "PYTEST_CURRENT_TEST" in os.environ:
        return False
    return bool(settings.gemini_api_key)


def generate_text(
    prompt: str,
    *,
    system: str,
    temperature: float = 0.5,
    max_output_tokens: int = 1200,
) -> str:
    """Run a text-generation call."""
    if not llm_enabled():
        raise LLMUnavailable("LLM calls are disabled")

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=_normalize_model_name(settings.gemini_chat_model),
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        ),
    )
    text = (response.text or "").strip()
    if not text:
        raise LLMUnavailable("LLM returned an empty response")
    return text


def generate_json(
    prompt: str,
    *,
    system: str,
    temperature: float = 0.1,
    max_output_tokens: int = 900,
) -> dict[str, Any]:
    """Run a JSON-mode call and parse the object response."""
    if not llm_enabled():
        raise LLMUnavailable("LLM calls are disabled")

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=_normalize_model_name(settings.gemini_json_model),
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",
        ),
    )
    text = (response.text or "").strip()
    if not text:
        raise LLMUnavailable("LLM returned an empty JSON response")
    return _parse_json_object(text)


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match is None:
            raise LLMUnavailable("LLM response did not contain a JSON object") from None
        parsed = json.loads(match.group(0))

    if not isinstance(parsed, dict):
        raise LLMUnavailable("LLM JSON response was not an object")
    return parsed


def embed_content(
    contents: str | list[str],
    *,
    task_type: str,
) -> list[float] | list[list[float]]:
    """Run a Gemini embedding call for retrieval document/query text."""
    if not llm_enabled():
        raise LLMUnavailable("Embedding calls are disabled")

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.embed_content(
        model=_normalize_model_name(settings.embedding_model),
        contents=contents,
        config=types.EmbedContentConfig(
            taskType=task_type,
            outputDimensionality=settings.embedding_dimension,
        ),
    )
    embeddings = [embedding.values for embedding in (response.embeddings or [])]
    if isinstance(contents, str):
        return embeddings[0] if embeddings else []
    return embeddings


def _normalize_model_name(model: str) -> str:
    return model.removeprefix("models/")
