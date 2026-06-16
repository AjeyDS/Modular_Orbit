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


def test_context_doc_trimmed_to_budget():
    capture_fact(source="manual", text="X" * 500)
    weave_user_model()
    ctx = build_user_model_context(budget=50)
    # The woven doc content is clipped to the budget (no unwoven tail here).
    assert "Recently (not yet woven)" not in ctx
    assert len(ctx) <= 50


def test_context_tail_caps_and_keeps_newest():
    for i in range(10):
        capture_fact(source="manual", text=f"fact number {i}")
    ctx = build_user_model_context(tail_limit=3)
    # Only the 3 newest (7, 8, 9), newest-first; older ones excluded.
    assert "fact number 9" in ctx
    assert "fact number 7" in ctx
    assert "fact number 6" not in ctx
    assert "fact number 0" not in ctx
    assert ctx.index("fact number 9") < ctx.index("fact number 7")
