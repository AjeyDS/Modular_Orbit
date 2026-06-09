from __future__ import annotations

from app.db import connect, ensure_schema
from app.modules import sync_module_registry
from app.modules.companion import build_persona_prompt
from app.user_model import ensure_goals_seed, ensure_story_buckets


def _ready_companion(tmp_path) -> None:
    ensure_schema()
    sync_module_registry()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM life_items li
                USING module_instances mi
                WHERE li.module_instance_id = mi.id
                    AND mi.module_id = 'curious'
                """
            )
        conn.commit()
    with connect() as conn:
        ensure_story_buckets(tmp_path, conn)
        conn.commit()
    ensure_goals_seed(tmp_path)


def test_companion_messages_table_exists() -> None:
    ensure_schema()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'companion_messages'
                ORDER BY column_name
                """
            )
            columns = {row["column_name"] for row in cur.fetchall()}
    assert {"id", "session_id", "role", "content", "meta", "created_at"} <= columns


def test_curious_module_has_companion_defaults() -> None:
    from app.modules import sync_module_registry

    ensure_schema()
    sync_module_registry()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT default_settings FROM modules WHERE id = 'curious'")
            settings = cur.fetchone()["default_settings"]

    assert settings["companion_enabled"] is True
    assert settings["companion_persona_preset"] == "warm"
    assert settings["companion_persona_override"] == ""
    assert settings["companion_checkins_per_day"] == 0


def test_persona_prompt_includes_preset_and_override() -> None:
    prompt = build_persona_prompt(preset="coach", override="Call me by my first name.")
    assert "coach" in prompt.lower() or "push" in prompt.lower()
    assert "Call me by my first name." in prompt


def test_persona_prompt_unknown_preset_falls_back_to_warm() -> None:
    prompt = build_persona_prompt(preset="nonsense", override="")
    assert prompt
    assert "warm" in prompt.lower() or "encourag" in prompt.lower()


def test_typed_goodbye_ends_session(tmp_path) -> None:
    from app.lifecycle import get_life_item
    from app.modules.companion import get_or_create_companion_session, respond_to_user_turn

    _ready_companion(tmp_path)
    session = get_or_create_companion_session()
    reply = respond_to_user_turn("talk to you later")
    assert reply["kind"] == "ended"
    assert get_life_item(session["id"])["payload"]["session_state"] == "closed"


def test_ending_closes_session_and_opens_fresh_one(tmp_path) -> None:
    from app.lifecycle import get_life_item
    from app.modules.companion import (
        end_companion_session,
        get_or_create_companion_session,
        record_user_turn,
    )

    _ready_companion(tmp_path)
    first = get_or_create_companion_session()
    record_user_turn(first["id"], "My EAD card was approved today")

    end_companion_session()

    second = get_or_create_companion_session()
    assert second["id"] != first["id"]
    assert second["payload"]["session_state"] == "open"
    assert get_life_item(first["id"])["payload"]["session_state"] == "closed"


def test_companion_session_is_stable(tmp_path) -> None:
    from app.modules.companion import get_or_create_companion_session

    _ready_companion(tmp_path)
    first = get_or_create_companion_session()
    second = get_or_create_companion_session()
    assert first["id"] == second["id"]
    assert first["payload"]["session_type"] == "companion"


def test_meaningfulness_gate_skips_filler() -> None:
    from app.modules.companion import is_meaningful_reply

    assert is_meaningful_reply("ok") is False
    assert is_meaningful_reply("thanks!") is False
    assert is_meaningful_reply("My EAD card was approved today") is True


def test_meaningfulness_gate_uses_llm_when_available(monkeypatch) -> None:
    import app.modules.companion as companion

    monkeypatch.setattr(companion, "generate_json", lambda *a, **k: {"meaningful": True})
    assert companion.is_meaningful_reply("ok") is True


def test_meaningful_turn_creates_log_not_curious_capture(tmp_path) -> None:
    from app.modules.companion import get_or_create_companion_session, record_user_turn

    _ready_companion(tmp_path)
    session = get_or_create_companion_session()
    record_user_turn(session["id"], "My EAD card was approved today")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role, content FROM companion_messages WHERE session_id = %s",
                (session["id"],),
            )
            messages = cur.fetchall()
            cur.execute(
                "SELECT COUNT(*) AS c FROM life_items WHERE item_type = 'curious_capture'"
            )
            assert cur.fetchone()["c"] == 0
            cur.execute(
                """
                SELECT COUNT(*) AS c FROM life_items li
                JOIN module_instances mi ON mi.id = li.module_instance_id
                WHERE mi.module_id = 'logs' AND li.item_type = 'log'
                """
            )
            assert cur.fetchone()["c"] == 1
    assert any(m["role"] == "user" and "EAD" in m["content"] for m in messages)


def test_companion_context_includes_buckets_and_goals(tmp_path) -> None:
    from app.modules.companion import build_companion_context

    _ready_companion(tmp_path)
    ctx = build_companion_context()
    assert "Story Buckets" in ctx or "buckets" in ctx.lower()
    assert isinstance(ctx, str) and ctx.strip()


def test_question_generation_falls_back_to_foundational_when_llm_down(tmp_path) -> None:
    from app.modules.companion import generate_companion_question

    _ready_companion(tmp_path)
    q = generate_companion_question()
    assert q["opening_message"]
    assert q["target_bucket_key"] in {
        "who_am_i", "goals", "interests_and_works", "career",
        "health", "relationships", "habits", "aspirations",
    }


def test_question_style_system_prompt(tmp_path, monkeypatch) -> None:
    import app.modules.companion as companion

    _ready_companion(tmp_path)
    captured: dict[str, str] = {}

    def fake(prompt, *, system, **k):
        captured["system"] = system
        return {
            "opening_message": "What's been good lately?",
            "target_bucket_key": "habits",
            "quick_replies": [{"id": "a", "label": "Work"}],
            "rationale": "light",
        }

    monkeypatch.setattr(companion, "generate_json", fake)
    q = companion.generate_companion_question(exclude_bucket=None)
    assert "conversational" in captured["system"].lower() or "short" in captured["system"].lower()
    assert q["quick_replies"]


def test_question_generation_uses_llm_when_available(tmp_path, monkeypatch) -> None:
    _ready_companion(tmp_path)
    import app.modules.companion as companion

    monkeypatch.setattr(
        companion, "generate_json",
        lambda *a, **k: {
            "opening_message": "How did the EAD news land for you?",
            "target_bucket_key": "career",
            "quick_replies": [],
            "rationale": "follow up on milestone",
        },
    )
    q = companion.generate_companion_question()
    assert q["opening_message"] == "How did the EAD news land for you?"
    assert q["target_bucket_key"] == "career"


def test_volunteered_fact_gets_short_ack_not_a_question(tmp_path, monkeypatch) -> None:
    _ready_companion(tmp_path)
    import app.modules.companion as companion

    monkeypatch.setattr(companion, "generate_text", lambda *a, **k: "Got it — that's great.")
    reply = companion.respond_to_user_turn("My EAD card was approved today")
    assert reply["kind"] == "acknowledge"
    assert reply["message"]
    assert "quick_replies" not in reply or reply["quick_replies"] == []


def test_synthesis_queues_bucket_updates_from_captures(tmp_path, monkeypatch) -> None:
    from app.modules.companion import (
        get_or_create_companion_session,
        record_user_turn,
        synthesize_companion_session,
    )

    _ready_companion(tmp_path)
    import app.modules.companion as companion

    session = get_or_create_companion_session()
    record_user_turn(session["id"], "My EAD card was approved today")
    monkeypatch.setattr(
        companion, "generate_json",
        lambda *a, **k: {"facts": [
            {"bucket_key": "career", "text": "Person's EAD work authorization was approved."}
        ]},
    )
    synthesize_companion_session(session["id"])

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT update_text, status, source_event FROM bucket_updates "
                "WHERE source_event ->> 'source' = 'curious_companion'"
            )
            rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert "EAD" in rows[0]["update_text"]


def test_synthesis_no_facts_when_llm_down(tmp_path) -> None:
    from app.modules.companion import (
        get_or_create_companion_session,
        record_user_turn,
        synthesize_companion_session,
    )

    _ready_companion(tmp_path)
    session = get_or_create_companion_session()
    record_user_turn(session["id"], "My EAD card was approved today")
    synthesize_companion_session(session["id"])
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS c FROM life_items li
                JOIN module_instances mi ON mi.id = li.module_instance_id
                WHERE mi.module_id = 'logs' AND li.item_type = 'log'
                """
            )
            assert cur.fetchone()["c"] == 1


def test_weave_merges_companion_updates(tmp_path, monkeypatch) -> None:
    from app.modules.curious import weave_pending_curious_updates

    _ready_companion(tmp_path)
    import app.modules.companion as companion

    session = companion.get_or_create_companion_session()
    companion.record_user_turn(session["id"], "My EAD card was approved today")
    monkeypatch.setattr(
        companion, "generate_json",
        lambda *a, **k: {"facts": [
            {"bucket_key": "career", "text": "Person's EAD work authorization was approved."}
        ]},
    )
    companion.synthesize_companion_session(session["id"])

    result = weave_pending_curious_updates()
    merged = sum(r.merged_count for r in result.results)
    assert merged >= 1
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM story_buckets WHERE stable_key = 'career'")
            assert "EAD" in cur.fetchone()["content"]


def test_due_check_prepares_checkin_when_enabled(tmp_path, monkeypatch) -> None:
    from app.modules.companion import get_or_create_companion_session, prepare_due_checkin

    _ready_companion(tmp_path)
    import app.modules.companion as companion

    monkeypatch.setattr(companion, "_companion_settings", lambda: {
        "companion_enabled": True, "companion_checkins_per_day": 3,
        "companion_persona_preset": "warm", "companion_persona_override": "",
    })
    monkeypatch.setattr(companion, "generate_companion_question", lambda: {
        "opening_message": "Morning — how's the day shaping up?",
        "target_bucket_key": "habits", "quick_replies": [], "rationale": "checkin",
    })

    prepared = prepare_due_checkin()
    assert prepared is not None
    assert prepare_due_checkin() is None


def test_due_check_off_when_frequency_zero(tmp_path, monkeypatch) -> None:
    _ready_companion(tmp_path)
    import app.modules.companion as companion

    monkeypatch.setattr(companion, "_companion_settings", lambda: {
        "companion_enabled": True, "companion_checkins_per_day": 0,
        "companion_persona_preset": "warm", "companion_persona_override": "",
    })
    assert companion.prepare_due_checkin() is None


def test_on_demand_ask_persists_question(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app.db import connect
    from app.main import app

    _ready_companion(tmp_path)
    client = TestClient(app)
    resp = client.post("/api/modules/curious/companion/ask")
    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"]["kind"] == "question"
    assert body["reply"]["message"]
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS c
                FROM companion_messages
                WHERE role = 'assistant' AND meta ->> 'kind' = 'question'
                """
            )
            assert cur.fetchone()["c"] == 1


def test_companion_http_send_and_state(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    _ready_companion(tmp_path)
    client = TestClient(app)

    state = client.get("/api/modules/curious/companion/state")
    assert state.status_code == 200
    assert "messages" in state.json()

    sent = client.post(
        "/api/modules/curious/companion/message",
        json={"message": "My EAD card was approved today"},
    )
    assert sent.status_code == 200
    body = sent.json()
    assert body["reply"]["message"]

    state2 = client.get("/api/modules/curious/companion/state")
    assert any("EAD" in m.get("content", "") for m in state2.json()["messages"])


def test_filler_user_turn_records_message_but_no_log(tmp_path) -> None:
    from app.modules.companion import get_or_create_companion_session, record_user_turn

    _ready_companion(tmp_path)
    session = get_or_create_companion_session()
    record_user_turn(session["id"], "thanks!")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS c FROM life_items li
                JOIN module_instances mi ON mi.id = li.module_instance_id
                WHERE mi.module_id = 'logs' AND li.item_type = 'log'
                """
            )
            assert cur.fetchone()["c"] == 0


# --- Bug fixes: bucket-key normalization, log status, gate tightening ---

import app.modules.companion as companion
from app.modules.companion import (
    _normalize_bucket_key,
    generate_companion_question,
    get_or_create_companion_session,
    is_meaningful_reply,
    record_user_turn,
    synthesize_companion_session,
)


def test_normalize_bucket_key_maps_display_names_and_rejects_invented() -> None:
    assert _normalize_bucket_key("Aspirations") == "aspirations"
    assert _normalize_bucket_key("Who Am I") == "who_am_i"
    assert _normalize_bucket_key("career") == "career"
    assert _normalize_bucket_key("employment_authorization_document") is None
    assert _normalize_bucket_key(None) is None


def test_generate_question_accepts_display_name_key(tmp_path, monkeypatch) -> None:
    _ready_companion(tmp_path)
    monkeypatch.setattr(
        companion, "generate_json",
        lambda *a, **k: {"opening_message": "What pulled at you this week?",
                         "target_bucket_key": "Aspirations", "quick_replies": [], "rationale": "x"},
    )
    q = generate_companion_question()
    assert q["target_bucket_key"] == "aspirations"
    assert q["rationale"] != "generic check-in"  # did NOT fall back


def test_synthesis_normalizes_known_and_drops_invented(tmp_path, monkeypatch) -> None:
    _ready_companion(tmp_path)
    session = get_or_create_companion_session()
    record_user_turn(session["id"], "My EAD card was approved today")
    monkeypatch.setattr(
        companion, "generate_json",
        lambda *a, **k: {"facts": [
            {"bucket_key": "Career", "text": "EAD work authorization approved."},
            {"bucket_key": "employment_authorization_document", "text": "dropped"},
        ]},
    )
    synthesize_companion_session(session["id"])
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT bucket_update->>'text' FROM ("
                "SELECT source_event AS bucket_update FROM bucket_updates "
                "WHERE source_event->>'source'='curious_companion') s"
            )
            cur.execute(
                "SELECT update_text, source_event->>'bucket_key' bk FROM bucket_updates "
                "WHERE source_event->>'source'='curious_companion'"
            )
            rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["bk"] == "career"
    assert "EAD" in rows[0]["update_text"]


def test_companion_log_marked_terminal(tmp_path) -> None:
    _ready_companion(tmp_path)
    session = get_or_create_companion_session()
    record_user_turn(session["id"], "My EAD card was approved today")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT connection_status cs, chunk_status ch, bucket_update_status bu
                FROM life_items li JOIN module_instances mi ON mi.id = li.module_instance_id
                WHERE mi.module_id = 'logs' AND li.source->>'kind' = 'companion_capture'
                """
            )
            row = cur.fetchone()
    assert row["cs"] == "complete"
    assert row["ch"] == "not_needed"
    assert row["bu"] == "not_needed"


def test_gate_rejects_vague_status_keeps_real_update() -> None:
    # LLM disabled under pytest -> exercises the deterministic fallback.
    assert is_meaningful_reply("It's going good") is False
    assert is_meaningful_reply("its going good") is False
    assert is_meaningful_reply("fine") is False
    assert is_meaningful_reply("My EAD card was approved today") is True
