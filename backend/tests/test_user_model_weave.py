from __future__ import annotations

from app.user_model import (
    capture_fact,
    current_woven_doc,
    list_unwoven_facts,
    weave_user_model,
)


def test_weave_creates_version_and_marks_facts():
    capture_fact(source="manual", text="Targeting Data Scientist + DE roles.")
    capture_fact(source="manual", text="OPT starts mid-June 2026.")
    result = weave_user_model()
    assert result["version"] == 1
    doc = current_woven_doc()
    assert "Data Scientist" in doc["content"]
    assert list_unwoven_facts() == []


def test_weave_noop_when_no_unwoven_facts():
    assert weave_user_model() is None


def test_weave_preserves_prior_content_across_versions():
    capture_fact(source="manual", text="Family runs Ajey Pavers.")
    weave_user_model()
    capture_fact(source="manual", text="From Trichy, Tamil Nadu.")
    weave_user_model()
    doc = current_woven_doc()
    assert "Ajey Pavers" in doc["content"]
    assert "Trichy" in doc["content"]
    assert doc["version"] == 2


def test_should_weave_threshold_boundary():
    from app.user_model import should_weave
    for i in range(7):
        capture_fact(source="manual", text=f"fact {i}")
    assert should_weave() is False
    capture_fact(source="manual", text="fact 8")
    assert should_weave() is True
