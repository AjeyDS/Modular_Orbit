from __future__ import annotations
from app.db import connect

def test_user_facts_and_weave_tables_exist():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.user_facts') AS t")
        assert cur.fetchone()["t"] == "user_facts"
        cur.execute("SELECT to_regclass('public.user_model_weave') AS t")
        assert cur.fetchone()["t"] == "user_model_weave"

def test_user_facts_defaults():
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO user_facts (source, text) VALUES ('manual', 'hi') RETURNING woven, salience"
        )
        row = cur.fetchone()
        assert row["woven"] is False
        assert row["salience"] == "normal"
        conn.rollback()

def test_capture_fact_appends_unwoven():
    from app.user_model import capture_fact, list_unwoven_facts
    capture_fact(source="manual", text="Family runs Ajey Pavers in Trichy.")
    facts = list_unwoven_facts()
    assert len(facts) == 1
    assert facts[0]["text"].startswith("Family runs")
    assert facts[0]["woven"] is False

def test_unwoven_budget_counts_and_chars():
    from app.user_model import capture_fact, unwoven_budget
    capture_fact(source="companion", text="a" * 100)
    capture_fact(source="life_item", text="b" * 50, ref={"life_item_id": "x", "kind": "task"})
    count, chars = unwoven_budget()
    assert count == 2
    assert chars == 150

def test_create_life_item_captures_fact():
    from uuid import uuid4
    from app.modules.tasks import TaskCreate, create_task, remove_task
    from app.user_model import list_unwoven_facts

    task = create_task(
        TaskCreate(title="Buy concrete sealer", request_id=f"fact-create-{uuid4().hex}"),
        review=False,
    )

    facts = [f for f in list_unwoven_facts() if f["source"] == "life_item"]
    assert facts, "expected a life_item fact to be captured on create"
    assert any(task.title in f["text"] for f in facts)
    assert any(f["ref"].get("life_item_id") == str(task.id) for f in facts)

    remove_task(task.id)


def test_update_life_item_capture_gated_on_meaningful_edit():
    from uuid import uuid4
    from app.lifecycle import update_life_item
    from app.modules.tasks import TaskCreate, create_task, remove_task
    from app.user_model import list_unwoven_facts

    task = create_task(
        TaskCreate(title="Original title", request_id=f"fact-update-{uuid4().hex}"),
        review=False,
    )

    def updated_facts():
        return [
            f
            for f in list_unwoven_facts()
            if f["source"] == "life_item"
            and f["ref"].get("life_item_id") == str(task.id)
            and f["text"].startswith("Updated")
        ]

    # Baseline: only the "Added" fact from creation exists; no "Updated" facts yet.
    assert updated_facts() == []

    # Non-meaningful edit must NOT emit an "Updated" fact.
    update_life_item(task.id, title="System touched title", meaningful_edit=False)
    assert updated_facts() == [], "non-meaningful edit should not capture an Updated fact"

    # Meaningful edit must emit an "Updated" fact.
    update_life_item(task.id, title="User edited title", meaningful_edit=True)
    facts = updated_facts()
    assert len(facts) == 1, "meaningful edit should capture exactly one Updated fact"
    assert "User edited title" in facts[0]["text"]

    remove_task(task.id)
