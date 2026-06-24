"""Unit tests for the LLM client's transient-error retry behavior.

These mock the Gemini client entirely — no real API calls, no DB access — but
the autouse DB-cleanup fixture still applies, so run against a test database.
"""

from __future__ import annotations

import pytest
from google.genai import errors as genai_errors

from app.llm import client as llm_client


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModels:
    def __init__(self, behaviors: list[object]) -> None:
        self._behaviors = behaviors
        self.calls = 0

    def _next(self):
        behavior = self._behaviors[min(self.calls, len(self._behaviors) - 1)]
        self.calls += 1
        if isinstance(behavior, Exception):
            raise behavior
        return behavior

    def generate_content(self, **_kwargs):
        return self._next()


class _FakeClient:
    def __init__(self, behaviors: list[object]) -> None:
        self.models = _FakeModels(behaviors)


def _overloaded() -> genai_errors.ServerError:
    return genai_errors.ServerError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})


def _patch(monkeypatch, behaviors: list[object]) -> tuple[_FakeClient, list[float]]:
    sleeps: list[float] = []
    fake = _FakeClient(behaviors)
    monkeypatch.setattr(llm_client, "llm_enabled", lambda: True)
    monkeypatch.setattr(llm_client.genai, "Client", lambda **_kwargs: fake)
    monkeypatch.setattr(llm_client.time, "sleep", lambda seconds: sleeps.append(seconds))
    return fake, sleeps


def test_generate_text_retries_transient_503(monkeypatch) -> None:
    fake, sleeps = _patch(monkeypatch, [_overloaded(), _Resp("hello world")])

    result = llm_client.generate_text("prompt", system="sys")

    assert result == "hello world"
    assert fake.models.calls == 2  # failed once, retried, succeeded
    assert len(sleeps) == 1  # backed off once


def test_generate_text_gives_up_after_max_attempts(monkeypatch) -> None:
    fake, _sleeps = _patch(monkeypatch, [_overloaded(), _overloaded(), _overloaded()])

    with pytest.raises(genai_errors.ServerError):
        llm_client.generate_text("prompt", system="sys")

    assert fake.models.calls == llm_client._RETRY_ATTEMPTS


def test_generate_text_does_not_retry_non_transient_400(monkeypatch) -> None:
    bad_request = genai_errors.ClientError(400, {"error": {"message": "bad request"}})
    fake, sleeps = _patch(monkeypatch, [bad_request, _Resp("never reached")])

    with pytest.raises(genai_errors.ClientError):
        llm_client.generate_text("prompt", system="sys")

    assert fake.models.calls == 1  # 4xx (non-429) is not retried
    assert sleeps == []


def test_generate_json_retries_transient_then_parses(monkeypatch) -> None:
    fake, _sleeps = _patch(monkeypatch, [_overloaded(), _Resp('{"ok": true}')])

    result = llm_client.generate_json("prompt", system="sys")

    assert result == {"ok": True}
    assert fake.models.calls == 2
