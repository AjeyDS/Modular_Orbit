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
