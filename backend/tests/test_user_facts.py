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
