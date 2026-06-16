from __future__ import annotations

from app.user_model import (
    build_user_model_context,
    capture_fact,
    weave_user_model,
)


def test_context_includes_doc_and_tail():
    capture_fact(source="manual", text="Builder-first, direct, fast iteration.")
    weave_user_model()
    capture_fact(source="life_item", text="Added task: LeetCode Blind 75")
    ctx = build_user_model_context()
    assert "Builder-first" in ctx
    assert "Recently (not yet woven)" in ctx
    assert "Blind 75" in ctx


def test_context_empty_is_safe():
    assert build_user_model_context() == ""


def test_context_doc_only_when_no_unwoven():
    capture_fact(source="manual", text="From Trichy, Tamil Nadu.")
    weave_user_model()
    ctx = build_user_model_context()
    assert "Trichy" in ctx
    assert "Recently (not yet woven)" not in ctx


def test_context_tail_only_when_no_doc():
    capture_fact(source="manual", text="Owns Ajey Pavers.")
    ctx = build_user_model_context()
    assert "Recently (not yet woven)" in ctx
    assert "Ajey Pavers" in ctx
