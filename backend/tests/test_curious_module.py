from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import connect, ensure_schema
from app.main import app
from app.modules import sync_module_registry
from app.modules.curious import (
    CuriousAnswerCreate,
    CuriousPendingAnswerCreate,
    answer_pending_question,
    answer_onboarding_question,
    complete_onboarding_session,
    get_curious_page_state,
    get_onboarding_state,
    weave_pending_curious_updates,
)
from app.user_model import ensure_goals_seed, ensure_story_buckets


def _ready(tmp_path) -> None:
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


def test_curious_starts_onboarding_session_with_known_bucket_target(tmp_path) -> None:
    _ready(tmp_path)

    state = get_onboarding_state()

    assert state.completed is False
    assert state.question_count == 5
    assert state.question is not None
    assert state.question.id == "onboarding_career_stage"
    assert state.question.tier == "onboarding"
    assert state.question.update_type == "identity"
    assert state.question.foundational is True
    assert state.question.target_bucket_key == "career"
    assert state.question.target_bucket_id is not None


def test_curious_answer_writes_direct_connection_chunk_and_bucket_update(tmp_path) -> None:
    _ready(tmp_path)
    state = get_onboarding_state()
    assert state.question is not None

    next_state = answer_onboarding_question(
        CuriousAnswerCreate(
            session_id=state.session_id,
            question_id=state.question.id,
            option_id="mid_building_expertise",
        )
    )

    assert next_state.current_index == 1
    assert len(next_state.answers) == 1
    answer = next_state.answers[0]
    assert answer.question_id == "onboarding_career_stage"
    assert answer.tier == "onboarding"
    assert answer.update_type == "identity"
    assert answer.foundational is True
    assert answer.target_bucket_key == "career"
    assert answer.bucket_update_text == "Person is mid-career and focused on building expertise."

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT target_type, target_id, strength, review_source
                FROM item_connections
                WHERE source_life_item_id = %s
                """,
                (answer.life_item_id,),
            )
            connection = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS count FROM knowledge_chunks WHERE life_item_id = %s", (answer.life_item_id,))
            chunk_count = cur.fetchone()["count"]
            cur.execute("SELECT status, update_text, source_event FROM bucket_updates WHERE life_item_id = %s", (answer.life_item_id,))
            update = cur.fetchone()

    assert connection["target_type"] == "story_bucket"
    assert connection["strength"] == 1.0
    assert connection["review_source"] == "curious_direct"
    assert chunk_count == 1
    assert update["status"] == "pending"
    assert update["update_text"] == answer.bucket_update_text
    assert update["source_event"]["update_type"] == "identity"
    assert update["source_event"]["foundational"] is True


def test_curious_completion_weaves_summary_into_bucket_files(tmp_path) -> None:
    _ready(tmp_path)
    state = get_onboarding_state()

    selected_options = {
        "onboarding_career_stage": "mid_building_expertise",
        "onboarding_aspirations_orientation": "building_something",
        "onboarding_habits_thinking_mode": "long_stretches",
        "onboarding_relationships_closest_circle": "close_friends",
        "onboarding_health_relationship": "actively_manage",
    }
    for question_id, option_id in selected_options.items():
        state = answer_onboarding_question(
            CuriousAnswerCreate(
                session_id=state.session_id,
                question_id=question_id,
                option_id=option_id,
            )
        )

    completed = complete_onboarding_session(state.session_id)

    assert completed.completed is True
    assert len(completed.summary) == 5
    assert completed.preview
    assert all(group.lines for group in completed.preview)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM story_buckets WHERE stable_key = 'career'")
            career_content = cur.fetchone()["content"]
    assert "Person is mid-career and focused on building expertise." in career_content

    page_state = get_curious_page_state()
    assert page_state.pending_count == 10
    assert page_state.pending_questions[0].question.id == "bay_career_work_time"
    assert page_state.pending_questions[0].question.tier == "bay"
    assert page_state.pending_questions[0].question.foundational is False
    assert "You're mid-career" in page_state.self_profile


def test_completion_returns_user_model_preview(tmp_path) -> None:
    _ready(tmp_path)
    state = get_onboarding_state()
    selected_options = {
        "onboarding_career_stage": "mid_building_expertise",
        "onboarding_aspirations_orientation": "building_something",
        "onboarding_habits_thinking_mode": "long_stretches",
        "onboarding_relationships_closest_circle": "close_friends",
        "onboarding_health_relationship": "actively_manage",
    }
    for question_id, option_id in selected_options.items():
        state = answer_onboarding_question(
            CuriousAnswerCreate(session_id=state.session_id, question_id=question_id, option_id=option_id)
        )

    completion = complete_onboarding_session(state.session_id)

    assert completion.preview
    assert all(group.lines for group in completion.preview)
    career = next(group for group in completion.preview if group.target_bucket_key == "career")
    assert "Person is mid-career and focused on building expertise." in career.lines


def test_curious_page_answers_bay_question_and_groups_history(tmp_path) -> None:
    _ready(tmp_path)
    state = get_onboarding_state()
    selected_options = {
        "onboarding_career_stage": "mid_building_expertise",
        "onboarding_aspirations_orientation": "building_something",
        "onboarding_habits_thinking_mode": "long_stretches",
        "onboarding_relationships_closest_circle": "close_friends",
        "onboarding_health_relationship": "actively_manage",
    }
    for question_id, option_id in selected_options.items():
        state = answer_onboarding_question(
            CuriousAnswerCreate(session_id=state.session_id, question_id=question_id, option_id=option_id)
        )
    complete_onboarding_session(state.session_id)

    page_state = get_curious_page_state()
    pending = page_state.pending_questions[0]
    answered = answer_pending_question(
        CuriousPendingAnswerCreate(
            question_life_item_id=pending.life_item_id,
            question_id=pending.question.id,
            option_id="deep_individual_work",
        )
    )

    assert answered.pending_count == 9
    career_group = next(group for group in answered.answered_groups if group.target_bucket_key == "career")
    assert len(career_group.answers) == 2
    assert career_group.answers[-1].tier == "bay"
    assert career_group.answers[-1].foundational is False


def test_curious_bay_session_weaves_pending_bay_updates(tmp_path) -> None:
    _ready(tmp_path)
    state = get_onboarding_state()
    selected_options = {
        "onboarding_career_stage": "mid_building_expertise",
        "onboarding_aspirations_orientation": "building_something",
        "onboarding_habits_thinking_mode": "long_stretches",
        "onboarding_relationships_closest_circle": "close_friends",
        "onboarding_health_relationship": "actively_manage",
    }
    for question_id, option_id in selected_options.items():
        state = answer_onboarding_question(
            CuriousAnswerCreate(session_id=state.session_id, question_id=question_id, option_id=option_id)
        )
    complete_onboarding_session(state.session_id)

    pending = get_curious_page_state().pending_questions[0]
    answer_pending_question(
        CuriousPendingAnswerCreate(
            question_life_item_id=pending.life_item_id,
            question_id=pending.question.id,
            option_id="deep_individual_work",
        )
    )

    result = weave_pending_curious_updates()

    assert len(result.results) == 1
    assert result.results[0].merged_count == 1
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM story_buckets WHERE stable_key = 'career'")
            career_content = cur.fetchone()["content"]
    assert "Most of the person's work time goes to deep individual work." in career_content

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS count
                FROM bucket_updates
                WHERE source_event ->> 'source' = 'curious_bay'
                    AND status = 'pending'
                """
            )
            pending_bay = cur.fetchone()["count"]

    assert pending_bay == 0


def test_curious_http_flow(tmp_path) -> None:
    _ready(tmp_path)
    client = TestClient(app)

    response = client.get("/modules/curious/onboarding")

    assert response.status_code == 200
    body = response.json()
    assert body["question"]["id"] == "onboarding_career_stage"

    answer_response = client.post(
        "/modules/curious/onboarding/answers",
        json={
            "session_id": body["session_id"],
            "question_id": "onboarding_career_stage",
            "option_id": "transitioning",
        },
    )

    assert answer_response.status_code == 200
    assert answer_response.json()["current_index"] == 1
