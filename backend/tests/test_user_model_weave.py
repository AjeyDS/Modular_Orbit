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


def test_weave_twice_across_captures_sequences_versions():
    """Advisory-lock owned path must still increment 1 then 2."""
    capture_fact(source="manual", text="Likes hiking on weekends.")
    first = weave_user_model()
    assert first["version"] == 1
    capture_fact(source="manual", text="Reads sci-fi novels.")
    second = weave_user_model()
    assert second["version"] == 2
    assert list_unwoven_facts() == []


def test_schedule_weave_if_needed_below_threshold():
    from fastapi import BackgroundTasks

    from app.user_model import schedule_weave_if_needed

    for i in range(3):
        capture_fact(source="manual", text=f"small fact {i}")
    bt = BackgroundTasks()
    schedule_weave_if_needed(bt)
    assert len(bt.tasks) == 0


def test_schedule_weave_if_needed_at_threshold():
    from fastapi import BackgroundTasks

    from app.user_model import schedule_weave_if_needed

    for i in range(8):
        capture_fact(source="manual", text=f"threshold fact {i}")
    bt = BackgroundTasks()
    schedule_weave_if_needed(bt)
    assert len(bt.tasks) == 1


def test_reweave_endpoint_weaves_and_clears_facts():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    capture_fact(source="manual", text="Building a side project called Orbit.")
    response = client.post("/user-model/reweave")
    assert response.status_code == 200
    body = response.json()
    assert "Orbit" in body["content"]
    assert list_unwoven_facts() == []
    # Nothing left to weave now.
    assert client.post("/user-model/reweave").status_code == 204


def test_post_note_creates_high_salience_manual_fact():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.post("/user-model/notes", json={"text": "Prefers async standups."})
    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "manual"
    assert body["salience"] == "high"
    assert body["text"] == "Prefers async standups."
    assert body["woven"] is False

    # It appears in GET /facts.
    facts = client.get("/user-model/facts").json()
    assert any(f["text"] == "Prefers async standups." for f in facts)


def test_post_note_rejects_empty_text():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.post("/user-model/notes", json={"text": ""}).status_code == 422


def test_get_facts_newest_first_and_respects_limit():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    for i in range(5):
        capture_fact(source="manual", text=f"ordered fact {i}")

    facts = client.get("/user-model/facts?limit=3").json()
    assert len(facts) == 3
    # Newest-first: the last captured fact comes first.
    assert facts[0]["text"] == "ordered fact 4"
    assert facts[1]["text"] == "ordered fact 3"
    assert facts[2]["text"] == "ordered fact 2"


def test_get_facts_validates_limit_bounds():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.get("/user-model/facts?limit=0").status_code == 422
    assert client.get("/user-model/facts?limit=101").status_code == 422


def test_get_doc_endpoint_204_then_200():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.get("/user-model/doc").status_code == 204
    capture_fact(source="manual", text="Lives in Seattle.")
    weave_user_model()
    response = client.get("/user-model/doc")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert "Seattle" in body["content"]
