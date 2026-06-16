"""Curious module service.

Curious bridges cold-start by asking structured questions whose target Story
Bucket is known at authoring time. It bypasses normal Connection Review routing
and writes direct Connections plus Bucket Updates.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from app.db import transaction
from app.lifecycle import create_life_item, get_life_item, set_lifecycle_status
from app.lifecycle.story_weave import StoryWeaveError, weave_story_bucket


QuestionTier = Literal["onboarding", "bay", "dynamic"]
QuestionType = Literal["single_choice", "short_text"]
SessionType = Literal["onboarding", "gap"]
UpdateType = Literal["identity"]


class CuriousOption(BaseModel):
    id: str
    label: str
    bucket_update_text: str


class CuriousQuestion(BaseModel):
    id: str
    tier: QuestionTier = "onboarding"
    update_type: UpdateType = "identity"
    foundational: bool = False
    target_bucket_key: str
    target_bucket_id: UUID | None = None
    target_bucket_name: str
    framing_text: str
    question_text: str
    question_type: QuestionType = "single_choice"
    source_label: str = "Onboarding"
    sort_order: int = 0
    options: list[CuriousOption]


class CuriousAnswerSummary(BaseModel):
    question_id: str
    tier: QuestionTier
    update_type: UpdateType
    foundational: bool
    target_bucket_key: str
    target_bucket_name: str
    option_id: str
    response: str
    bucket_update_text: str
    life_item_id: UUID


class CuriousPendingQuestion(BaseModel):
    life_item_id: UUID | None
    question: CuriousQuestion


class CuriousAnsweredGroup(BaseModel):
    target_bucket_key: str
    target_bucket_name: str
    answers: list[CuriousAnswerSummary]


class CuriousPreviewGroup(BaseModel):
    target_bucket_key: str
    target_bucket_name: str
    lines: list[str]


class CuriousOnboardingState(BaseModel):
    session_id: UUID
    completed: bool
    current_index: int
    question_count: int
    question: CuriousQuestion | None
    answers: list[CuriousAnswerSummary]


class CuriousAnswerCreate(BaseModel):
    session_id: UUID
    question_id: str
    option_id: str


class CuriousCompletion(BaseModel):
    session_id: UUID
    completed: bool
    summary: list[CuriousAnswerSummary]
    preview: list[CuriousPreviewGroup]


class CuriousPageState(BaseModel):
    onboarding: CuriousOnboardingState
    pending_questions: list[CuriousPendingQuestion]
    answered_groups: list[CuriousAnsweredGroup]
    preview: list[CuriousPreviewGroup] = Field(default_factory=list)
    self_profile: str
    pending_count: int


class CuriousPendingAnswerCreate(BaseModel):
    question_life_item_id: UUID | None = None
    session_id: UUID | None = None
    question_id: str
    option_id: str


class CuriousWeaveBucketResult(BaseModel):
    story_bucket_id: UUID
    status: str
    merged_count: int
    superseded_count: int
    ignored_count: int
    file_path: str


class CuriousWeaveResult(BaseModel):
    results: list[CuriousWeaveBucketResult]


ONBOARDING_QUESTIONS: tuple[CuriousQuestion, ...] = (
    CuriousQuestion(
        id="onboarding_career_stage",
        tier="onboarding",
        update_type="identity",
        foundational=True,
        target_bucket_key="career",
        target_bucket_name="Career",
        source_label="Onboarding",
        sort_order=10,
        framing_text="This helps me understand what work means to you right now.",
        question_text="Where are you in your career?",
        options=[
            CuriousOption(id="student_starting", label="Student or just starting out", bucket_update_text="Person is a student or just starting out."),
            CuriousOption(id="early_finding_path", label="Early career, still finding my path", bucket_update_text="Person is early career and still finding their path."),
            CuriousOption(id="mid_building_expertise", label="Mid-career, building expertise", bucket_update_text="Person is mid-career and focused on building expertise."),
            CuriousOption(id="senior_leading", label="Senior, leading or owning", bucket_update_text="Person is senior and focused on leading or owning work."),
            CuriousOption(id="transitioning", label="Transitioning between things", bucket_update_text="Person is transitioning between career phases or directions."),
        ],
    ),
    CuriousQuestion(
        id="onboarding_aspirations_orientation",
        tier="onboarding",
        update_type="identity",
        foundational=True,
        target_bucket_key="aspirations",
        target_bucket_name="Aspirations",
        source_label="Onboarding",
        sort_order=20,
        framing_text="This helps me know what direction matters to you.",
        question_text="When you think about the next year or two, what pulls at you most?",
        options=[
            CuriousOption(id="building_something", label="Building something — a project, business, or craft", bucket_update_text="Person's near-term orientation is building something that can grow over time."),
            CuriousOption(id="growing_in_role", label="Growing in a role or career I'm already in", bucket_update_text="Person's near-term orientation is growing in an existing role or career direction."),
            CuriousOption(id="stability_depth", label="Stability — protecting what I have and going deep", bucket_update_text="Person's near-term orientation is stability and depth."),
            CuriousOption(id="looking_for_change", label="Change — I'm looking for something different", bucket_update_text="Person's near-term orientation is meaningful change."),
            CuriousOption(id="figuring_it_out", label="Figuring it out — I don't have a clear direction yet", bucket_update_text="Person's near-term orientation is still being figured out."),
        ],
    ),
    CuriousQuestion(
        id="onboarding_habits_thinking_mode",
        tier="onboarding",
        update_type="identity",
        foundational=True,
        target_bucket_key="habits",
        target_bucket_name="Habits",
        source_label="Onboarding",
        sort_order=30,
        framing_text="This helps me understand how you work best.",
        question_text="When do you do your best thinking?",
        options=[
            CuriousOption(id="long_stretches", label="Long uninterrupted stretches", bucket_update_text="Person does their best thinking in long uninterrupted stretches."),
            CuriousOption(id="short_bursts", label="Short focused bursts", bucket_update_text="Person does their best thinking in short focused bursts."),
            CuriousOption(id="conversation", label="In conversation with other people", bucket_update_text="Person does their best thinking in conversation with other people."),
            CuriousOption(id="while_moving", label="While doing something else — walking, driving, exercising", bucket_update_text="Person does their best thinking while moving or doing something else."),
            CuriousOption(id="varies", label="It varies too much to say", bucket_update_text="Person's best thinking conditions vary too much to summarize simply."),
        ],
    ),
    CuriousQuestion(
        id="onboarding_relationships_closest_circle",
        tier="onboarding",
        update_type="identity",
        foundational=True,
        target_bucket_key="relationships",
        target_bucket_name="Relationships",
        source_label="Onboarding",
        sort_order=40,
        framing_text="This helps me know who matters in the life you're building.",
        question_text="Who is closest to your day-to-day right now?",
        options=[
            CuriousOption(id="immediate_family", label="Immediate family — partner, kids, parents", bucket_update_text="Person's closest day-to-day circle is immediate family."),
            CuriousOption(id="extended_family", label="Extended family — siblings, cousins, in-laws", bucket_update_text="Person's closest day-to-day circle is extended family."),
            CuriousOption(id="close_friends", label="A small group of close friends", bucket_update_text="Person's closest day-to-day circle is a small group of close friends."),
            CuriousOption(id="community", label="A community — coworkers, classmates, teammates", bucket_update_text="Person's closest day-to-day circle is a community such as coworkers, classmates, or teammates."),
            CuriousOption(id="solo_phase", label="Mostly myself — I'm in a solo phase", bucket_update_text="Person is mostly in a solo phase day to day."),
        ],
    ),
    CuriousQuestion(
        id="onboarding_health_relationship",
        tier="onboarding",
        update_type="identity",
        foundational=True,
        target_bucket_key="health",
        target_bucket_name="Health",
        source_label="Onboarding",
        sort_order=50,
        framing_text="Last one. This helps me know how energy works for you.",
        question_text="How do you think about your energy and wellbeing?",
        options=[
            CuriousOption(id="actively_manage", label="Something I actively manage — sleep, exercise, food", bucket_update_text="Person actively manages energy and wellbeing through things like sleep, exercise, or food."),
            CuriousOption(id="think_not_act", label="Something I think about but don't always act on", bucket_update_text="Person thinks about energy and wellbeing but does not always act on it."),
            CuriousOption(id="notice_when_off", label="Something I notice when it's off", bucket_update_text="Person notices energy and wellbeing mostly when something feels off."),
            CuriousOption(id="not_on_radar", label="Not really on my radar right now", bucket_update_text="Energy and wellbeing are not strongly on the person's radar right now."),
            CuriousOption(id="struggle_now", label="A struggle right now", bucket_update_text="Energy and wellbeing are a struggle for the person right now."),
        ],
    ),
)


BAY_QUESTIONS: tuple[CuriousQuestion, ...] = (
    CuriousQuestion(
        id="bay_career_work_time",
        tier="bay",
        update_type="identity",
        foundational=False,
        target_bucket_key="career",
        target_bucket_name="Career",
        source_label="Bay",
        sort_order=110,
        framing_text="This gives Career more texture than a stage label.",
        question_text="What does most of your work time go to right now?",
        options=[
            CuriousOption(id="deep_individual_work", label="Deep individual work", bucket_update_text="Most of the person's work time goes to deep individual work."),
            CuriousOption(id="coordination", label="Coordination and keeping things moving", bucket_update_text="Most of the person's work time goes to coordination and keeping things moving."),
            CuriousOption(id="learning", label="Learning and building skill", bucket_update_text="Most of the person's work time goes to learning and building skill."),
            CuriousOption(id="people", label="People, support, or leadership", bucket_update_text="Most of the person's work time goes to people, support, or leadership."),
            CuriousOption(id="mixed", label="A mix that changes week to week", bucket_update_text="The person's work time is a changing mix rather than one dominant mode."),
        ],
    ),
    CuriousQuestion(
        id="bay_career_change_vector",
        tier="bay",
        update_type="identity",
        foundational=False,
        target_bucket_key="career",
        target_bucket_name="Career",
        source_label="Bay",
        sort_order=120,
        framing_text="This helps Orbit understand what kind of career movement matters.",
        question_text="Over the next year, what would you most want to change about work?",
        options=[
            CuriousOption(id="more_skill", label="Build stronger expertise", bucket_update_text="Over the next year, the person most wants work to build stronger expertise."),
            CuriousOption(id="better_role", label="Move into a better role", bucket_update_text="Over the next year, the person most wants to move into a better role."),
            CuriousOption(id="more_ownership", label="Own more important work", bucket_update_text="Over the next year, the person most wants more ownership of important work."),
            CuriousOption(id="less_drain", label="Make work less draining", bucket_update_text="Over the next year, the person most wants work to become less draining."),
            CuriousOption(id="not_sure", label="I'm not sure yet", bucket_update_text="The person is not yet sure what they most want to change about work."),
        ],
    ),
    CuriousQuestion(
        id="bay_aspirations_success_picture",
        tier="bay",
        update_type="identity",
        foundational=False,
        target_bucket_key="aspirations",
        target_bucket_name="Aspirations",
        source_label="Bay",
        sort_order=210,
        framing_text="This turns direction into a concrete picture.",
        question_text="When you imagine the next year going well, what's true at the end?",
        options=[
            CuriousOption(id="visible_progress", label="I can point to visible progress", bucket_update_text="A good next year means the person can point to visible progress."),
            CuriousOption(id="more_stable", label="Life feels more stable", bucket_update_text="A good next year means life feels more stable for the person."),
            CuriousOption(id="new_door_open", label="A new door is open", bucket_update_text="A good next year means a new door has opened for the person."),
            CuriousOption(id="stronger_base", label="I have a stronger base", bucket_update_text="A good next year means the person has a stronger base to build from."),
            CuriousOption(id="clearer_direction", label="I have clearer direction", bucket_update_text="A good next year means the person has clearer direction."),
        ],
    ),
    CuriousQuestion(
        id="bay_aspirations_compounding",
        tier="bay",
        update_type="identity",
        foundational=False,
        target_bucket_key="aspirations",
        target_bucket_name="Aspirations",
        source_label="Bay",
        sort_order=220,
        framing_text="This helps Orbit spot what should compound over time.",
        question_text="What kind of progress would feel most worth compounding?",
        options=[
            CuriousOption(id="career_capital", label="Career capital", bucket_update_text="The person most wants career capital to compound over time."),
            CuriousOption(id="creative_body", label="A body of creative work", bucket_update_text="The person most wants a body of creative work to compound over time."),
            CuriousOption(id="relationships", label="Relationships and trust", bucket_update_text="The person most wants relationships and trust to compound over time."),
            CuriousOption(id="health_energy", label="Health and energy", bucket_update_text="The person most wants health and energy to compound over time."),
            CuriousOption(id="financial_room", label="Financial room to choose", bucket_update_text="The person most wants financial room and optionality to compound over time."),
        ],
    ),
    CuriousQuestion(
        id="bay_habits_sharpest_time",
        tier="bay",
        update_type="identity",
        foundational=False,
        target_bucket_key="habits",
        target_bucket_name="Habits",
        source_label="Bay",
        sort_order=310,
        framing_text="This helps Orbit time advice to your actual rhythm.",
        question_text="When are you usually sharpest?",
        options=[
            CuriousOption(id="early_morning", label="Early morning", bucket_update_text="The person is usually sharpest in the early morning."),
            CuriousOption(id="mid_morning", label="Mid-morning", bucket_update_text="The person is usually sharpest in the mid-morning."),
            CuriousOption(id="afternoon", label="Afternoon", bucket_update_text="The person is usually sharpest in the afternoon."),
            CuriousOption(id="evening", label="Evening or late night", bucket_update_text="The person is usually sharpest in the evening or late night."),
            CuriousOption(id="variable", label="It varies too much", bucket_update_text="The person's sharpest time varies too much to rely on."),
        ],
    ),
    CuriousQuestion(
        id="bay_habits_focus_derailer",
        tier="bay",
        update_type="identity",
        foundational=False,
        target_bucket_key="habits",
        target_bucket_name="Habits",
        source_label="Bay",
        sort_order=320,
        framing_text="This helps Orbit avoid plans that look good but break in real life.",
        question_text="What most often derails your focus?",
        options=[
            CuriousOption(id="interruptions", label="Interruptions", bucket_update_text="The person's focus is most often derailed by interruptions."),
            CuriousOption(id="unclear_priority", label="Unclear priority", bucket_update_text="The person's focus is most often derailed by unclear priority."),
            CuriousOption(id="low_energy", label="Low energy", bucket_update_text="The person's focus is most often derailed by low energy."),
            CuriousOption(id="too_many_threads", label="Too many open threads", bucket_update_text="The person's focus is most often derailed by too many open threads."),
            CuriousOption(id="avoidance", label="Avoidance or emotional drag", bucket_update_text="The person's focus is most often derailed by avoidance or emotional drag."),
        ],
    ),
    CuriousQuestion(
        id="bay_relationships_reorganize_for",
        tier="bay",
        update_type="identity",
        foundational=False,
        target_bucket_key="relationships",
        target_bucket_name="Relationships",
        source_label="Bay",
        sort_order=410,
        framing_text="This helps Orbit understand who has real priority, not just proximity.",
        question_text="Who would you most quickly reorganize your life for?",
        options=[
            CuriousOption(id="partner", label="Partner", bucket_update_text="The person would most quickly reorganize life for their partner."),
            CuriousOption(id="children_or_parents", label="Children or parents", bucket_update_text="The person would most quickly reorganize life for children or parents."),
            CuriousOption(id="siblings_family", label="Siblings or extended family", bucket_update_text="The person would most quickly reorganize life for siblings or extended family."),
            CuriousOption(id="close_friend", label="A close friend", bucket_update_text="The person would most quickly reorganize life for a close friend."),
            CuriousOption(id="mostly_self", label="Mostly myself right now", bucket_update_text="The person is mostly organizing life around themselves right now."),
        ],
    ),
    CuriousQuestion(
        id="bay_relationships_support_style",
        tier="bay",
        update_type="identity",
        foundational=False,
        target_bucket_key="relationships",
        target_bucket_name="Relationships",
        source_label="Bay",
        sort_order=420,
        framing_text="This helps Orbit understand what good support looks like around you.",
        question_text="What kind of support matters most to you right now?",
        options=[
            CuriousOption(id="practical_help", label="Practical help", bucket_update_text="The person most needs practical support right now."),
            CuriousOption(id="emotional_steadiness", label="Emotional steadiness", bucket_update_text="The person most needs emotional steadiness right now."),
            CuriousOption(id="honest_feedback", label="Honest feedback", bucket_update_text="The person most needs honest feedback right now."),
            CuriousOption(id="space", label="Space and trust", bucket_update_text="The person most needs space and trust right now."),
            CuriousOption(id="shared_momentum", label="Shared momentum", bucket_update_text="The person most needs shared momentum right now."),
        ],
    ),
    CuriousQuestion(
        id="bay_health_underinvested",
        tier="bay",
        update_type="identity",
        foundational=False,
        target_bucket_key="health",
        target_bucket_name="Health",
        source_label="Bay",
        sort_order=510,
        framing_text="This helps Orbit see the weak link in wellbeing.",
        question_text="Which part of health do you most underinvest in?",
        options=[
            CuriousOption(id="sleep", label="Sleep", bucket_update_text="Sleep is the part of health the person most underinvests in."),
            CuriousOption(id="movement", label="Movement", bucket_update_text="Movement is the part of health the person most underinvests in."),
            CuriousOption(id="food", label="Food", bucket_update_text="Food is the part of health the person most underinvests in."),
            CuriousOption(id="stress", label="Stress management", bucket_update_text="Stress management is the part of health the person most underinvests in."),
            CuriousOption(id="checkups", label="Medical follow-through", bucket_update_text="Medical follow-through is the part of health the person most underinvests in."),
        ],
    ),
    CuriousQuestion(
        id="bay_health_energy_driver",
        tier="bay",
        update_type="identity",
        foundational=False,
        target_bucket_key="health",
        target_bucket_name="Health",
        source_label="Bay",
        sort_order=520,
        framing_text="This helps Orbit connect plans to energy instead of pretending energy is constant.",
        question_text="What most affects your energy day to day?",
        options=[
            CuriousOption(id="sleep_quality", label="Sleep quality", bucket_update_text="Sleep quality most affects the person's day-to-day energy."),
            CuriousOption(id="stress_load", label="Stress load", bucket_update_text="Stress load most affects the person's day-to-day energy."),
            CuriousOption(id="social_load", label="Social load", bucket_update_text="Social load most affects the person's day-to-day energy."),
            CuriousOption(id="exercise", label="Exercise or movement", bucket_update_text="Exercise or movement most affects the person's day-to-day energy."),
            CuriousOption(id="unclear", label="I don't know yet", bucket_update_text="The person does not yet know what most affects their day-to-day energy."),
        ],
    ),
)


def get_onboarding_state() -> CuriousOnboardingState:
    session = _get_or_create_onboarding_session()
    return _state_for_session(session["id"])


def answer_onboarding_question(payload: CuriousAnswerCreate) -> CuriousOnboardingState:
    session = get_life_item(payload.session_id)
    if session["item_type"] != "curious_session":
        raise ValueError(f"Life Item is not a Curious Session: {payload.session_id}")
    if session["lifecycle_status"] == "completed":
        return _state_for_session(payload.session_id)

    question = _question_by_id(payload.question_id)
    option = _option_by_id(question, payload.option_id)
    bucket = _bucket_by_key(question.target_bucket_key)

    answer_text = option.label
    answer_title = f"{question.target_bucket_name}: {answer_text}"
    answer_description = f"{question.question_text}\n\nAnswer: {answer_text}"
    request_id = f"curious-answer-{payload.session_id}-{question.id}"
    result = create_life_item(
        module_id="curious",
        item_type="curious_answer",
        title=answer_title,
        description=answer_description,
        payload={
            "question_id": question.id,
            "tier": question.tier,
            "update_type": question.update_type,
            "foundational": question.foundational,
            "question_text": question.question_text,
            "question_type": question.question_type,
            "response": answer_text,
            "option_id": option.id,
            "target_bucket_id": str(bucket["id"]),
            "target_bucket_key": question.target_bucket_key,
            "target_bucket_name": question.target_bucket_name,
            "session_id": str(payload.session_id),
            "framing_text": question.framing_text,
            "bucket_update_text": option.bucket_update_text,
        },
        source={"kind": "curious_onboarding", "session_id": str(payload.session_id)},
        request_id=request_id,
    )

    if result.created:
        _persist_direct_connection_and_updates(
            life_item_id=result.item["id"],
            bucket_id=bucket["id"],
            bucket_label=bucket["display_name"],
            question=question,
            option=option,
        )
        _update_session_answer_count(payload.session_id)

    return _state_for_session(payload.session_id)


def complete_onboarding_session(session_id: UUID | str) -> CuriousCompletion:
    state = _state_for_session(session_id)
    if len(state.answers) < len(ONBOARDING_QUESTIONS):
        raise ValueError("Onboarding cannot complete until all Curious questions are answered.")

    item = get_life_item(session_id)
    if item["lifecycle_status"] != "completed":
        set_lifecycle_status(session_id, "completed")
        _mark_session_completed(session_id)

    _ensure_bay_questions()

    return CuriousCompletion(
        session_id=state.session_id,
        completed=True,
        summary=_state_for_session(session_id).answers,
        preview=_build_user_model_preview(state.answers),
    )


def get_curious_page_state() -> CuriousPageState:
    onboarding = get_onboarding_state()
    if onboarding.completed:
        _ensure_bay_questions()

    pending = _pending_questions(onboarding)
    answered = _all_answer_summaries()
    return CuriousPageState(
        onboarding=onboarding,
        pending_questions=pending[:5],
        answered_groups=_group_answers(answered),
        preview=_build_user_model_preview(onboarding.answers) if onboarding.completed else [],
        self_profile=_build_self_profile(answered),
        pending_count=len(pending),
    )


def answer_pending_question(payload: CuriousPendingAnswerCreate) -> CuriousPageState:
    if payload.question_life_item_id is None:
        session_id = payload.session_id or get_onboarding_state().session_id
        state = answer_onboarding_question(
            CuriousAnswerCreate(
                session_id=session_id,
                question_id=payload.question_id,
                option_id=payload.option_id,
            )
        )
        if len(state.answers) >= state.question_count and not state.completed:
            complete_onboarding_session(state.session_id)
        return get_curious_page_state()

    question_item = get_life_item(payload.question_life_item_id)
    if question_item["item_type"] != "curious_question":
        raise ValueError(f"Life Item is not a Curious Question: {payload.question_life_item_id}")
    if question_item["lifecycle_status"] != "active":
        return get_curious_page_state()

    question = _question_from_payload(question_item["payload"])
    option = _option_by_id(question, payload.option_id)
    bucket = _bucket_by_key(question.target_bucket_key)
    result = _create_answer_life_item(
        question=question,
        option=option,
        bucket=bucket,
        source={
            "kind": f"curious_{question.tier}",
            "question_life_item_id": str(payload.question_life_item_id),
        },
        request_id=f"curious-answer-{payload.question_life_item_id}",
        session_id=None,
    )

    if result.created:
        _persist_direct_connection_and_updates(
            life_item_id=result.item["id"],
            bucket_id=bucket["id"],
            bucket_label=bucket["display_name"],
            question=question,
            option=option,
        )

    set_lifecycle_status(payload.question_life_item_id, "completed")
    return get_curious_page_state()


def weave_pending_curious_updates() -> CuriousWeaveResult:
    """Merge pending Bay/Dynamic Curious updates after a user finishes a Curious sitting."""
    results: list[CuriousWeaveBucketResult] = []
    for bucket_id in _pending_curious_story_bucket_ids():
        try:
            result = weave_story_bucket(bucket_id)
        except StoryWeaveError:
            continue
        results.append(
            CuriousWeaveBucketResult(
                story_bucket_id=result.story_bucket_id,
                status=result.status,
                merged_count=result.merged_count,
                superseded_count=result.superseded_count,
                ignored_count=result.ignored_count,
                file_path=result.file_path,
            )
        )
    return CuriousWeaveResult(results=results)


def _create_answer_life_item(
    *,
    question: CuriousQuestion,
    option: CuriousOption,
    bucket: dict[str, Any],
    source: dict[str, Any],
    request_id: str,
    session_id: UUID | str | None,
):
    answer_text = option.label
    answer_title = f"{question.target_bucket_name}: {answer_text}"
    answer_description = f"{question.question_text}\n\nAnswer: {answer_text}"
    payload: dict[str, Any] = {
        "question_id": question.id,
        "tier": question.tier,
        "update_type": question.update_type,
        "foundational": question.foundational,
        "question_text": question.question_text,
        "question_type": question.question_type,
        "response": answer_text,
        "option_id": option.id,
        "target_bucket_id": str(bucket["id"]),
        "target_bucket_key": question.target_bucket_key,
        "target_bucket_name": question.target_bucket_name,
        "framing_text": question.framing_text,
        "bucket_update_text": option.bucket_update_text,
    }
    if session_id is not None:
        payload["session_id"] = str(session_id)

    return create_life_item(
        module_id="curious",
        item_type="curious_answer",
        title=answer_title,
        description=answer_description,
        payload=payload,
        source=source,
        request_id=request_id,
    )


def _pending_curious_story_bucket_ids() -> list[UUID]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT story_bucket_id
                FROM bucket_updates
                WHERE status = 'pending'
                    AND source_event ->> 'source' IN ('curious_bay', 'curious_dynamic', 'curious_companion')
                ORDER BY story_bucket_id
                """
            )
            return [row["story_bucket_id"] for row in cur.fetchall()]


def _get_or_create_onboarding_session() -> dict[str, Any]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT li.*
                FROM life_items li
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE m.id = 'curious'
                    AND li.item_type = 'curious_session'
                    AND li.payload ->> 'session_type' = 'onboarding'
                ORDER BY li.created_at ASC
                LIMIT 1
                """
            )
            existing = cur.fetchone()
            if existing is not None:
                return dict(existing)

    result = create_life_item(
        module_id="curious",
        item_type="curious_session",
        title="Onboarding Curiosity",
        description="Initial five-question Curious onboarding session.",
        payload={
            "session_type": "onboarding",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "question_count": len(ONBOARDING_QUESTIONS),
        },
        source={"kind": "curious_onboarding"},
        request_id="curious-onboarding-session",
    )
    _mark_session_lifecycle_not_needed(result.item["id"])
    return result.item


def _state_for_session(session_id: UUID | str) -> CuriousOnboardingState:
    answers = _answers_for_session(session_id)
    completed = get_life_item(session_id)["lifecycle_status"] == "completed"
    current_index = min(len(answers), len(ONBOARDING_QUESTIONS))
    question = None if completed or current_index >= len(ONBOARDING_QUESTIONS) else _hydrate_question(ONBOARDING_QUESTIONS[current_index])
    return CuriousOnboardingState(
        session_id=session_id,  # type: ignore[arg-type]
        completed=completed,
        current_index=current_index,
        question_count=len(ONBOARDING_QUESTIONS),
        question=question,
        answers=answers,
    )


def _answers_for_session(session_id: UUID | str) -> list[CuriousAnswerSummary]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, payload
                FROM life_items
                WHERE item_type = 'curious_answer'
                    AND payload ->> 'session_id' = %s
                    AND lifecycle_status <> 'deleted'
                ORDER BY created_at ASC
                """,
                (str(session_id),),
            )
            rows = cur.fetchall()

    return [
        CuriousAnswerSummary(
            question_id=row["payload"]["question_id"],
            tier=row["payload"].get("tier", "onboarding"),
            update_type=row["payload"].get("update_type", "identity"),
            foundational=row["payload"].get("foundational", False),
            target_bucket_key=row["payload"]["target_bucket_key"],
            target_bucket_name=row["payload"]["target_bucket_name"],
            option_id=row["payload"]["option_id"],
            response=row["payload"]["response"],
            bucket_update_text=row["payload"]["bucket_update_text"],
            life_item_id=row["id"],
        )
        for row in rows
    ]


def _all_answer_summaries() -> list[CuriousAnswerSummary]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, payload
                FROM life_items
                WHERE item_type = 'curious_answer'
                    AND lifecycle_status <> 'deleted'
                ORDER BY created_at ASC
                """
            )
            rows = cur.fetchall()

    return [
        CuriousAnswerSummary(
            question_id=row["payload"]["question_id"],
            tier=row["payload"].get("tier", "onboarding"),
            update_type=row["payload"].get("update_type", "identity"),
            foundational=row["payload"].get("foundational", False),
            target_bucket_key=row["payload"]["target_bucket_key"],
            target_bucket_name=row["payload"]["target_bucket_name"],
            option_id=row["payload"]["option_id"],
            response=row["payload"]["response"],
            bucket_update_text=row["payload"]["bucket_update_text"],
            life_item_id=row["id"],
        )
        for row in rows
    ]


def _group_answers(answers: list[CuriousAnswerSummary]) -> list[CuriousAnsweredGroup]:
    groups: dict[str, CuriousAnsweredGroup] = {}
    for answer in answers:
        group = groups.setdefault(
            answer.target_bucket_key,
            CuriousAnsweredGroup(
                target_bucket_key=answer.target_bucket_key,
                target_bucket_name=answer.target_bucket_name,
                answers=[],
            ),
        )
        group.answers.append(answer)
    return list(groups.values())


def _build_user_model_preview(answers: list[CuriousAnswerSummary]) -> list[CuriousPreviewGroup]:
    groups: dict[str, CuriousPreviewGroup] = {}
    for answer in answers:
        group = groups.setdefault(
            answer.target_bucket_key,
            CuriousPreviewGroup(
                target_bucket_key=answer.target_bucket_key,
                target_bucket_name=answer.target_bucket_name,
                lines=[],
            ),
        )
        if answer.bucket_update_text not in group.lines:
            group.lines.append(answer.bucket_update_text)
    return list(groups.values())


def _pending_questions(onboarding: CuriousOnboardingState) -> list[CuriousPendingQuestion]:
    if not onboarding.completed and onboarding.question is not None:
        return [CuriousPendingQuestion(life_item_id=None, question=onboarding.question)]

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, payload
                FROM life_items
                WHERE item_type = 'curious_question'
                    AND lifecycle_status = 'active'
                ORDER BY
                    CASE payload ->> 'tier'
                        WHEN 'dynamic' THEN 1
                        WHEN 'bay' THEN 2
                        ELSE 3
                    END,
                    COALESCE((payload ->> 'sort_order')::int, 9999),
                    created_at
                """
            )
            rows = cur.fetchall()

    return [
        CuriousPendingQuestion(
            life_item_id=row["id"],
            question=_hydrate_question(_question_from_payload(row["payload"])),
        )
        for row in rows
    ]


def _ensure_bay_questions() -> None:
    with transaction() as conn:
        with conn.cursor() as cur:
            for question in BAY_QUESTIONS:
                bucket = _bucket_by_key(question.target_bucket_key)
                payload = _question_payload(question, bucket)
                cur.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM life_items li
                    JOIN module_instances mi ON mi.id = li.module_instance_id
                    JOIN modules m ON m.id = mi.module_id
                    WHERE m.id = 'curious'
                        AND li.item_type IN ('curious_question', 'curious_answer')
                        AND li.payload ->> 'question_id' = %s
                        AND li.lifecycle_status <> 'deleted'
                    """,
                    (question.id,),
                )
                if cur.fetchone()["count"] > 0:
                    continue

                result = create_life_item(
                    module_id="curious",
                    item_type="curious_question",
                    title=question.question_text,
                    description=question.framing_text,
                    payload=payload,
                    source={"kind": "curious_bay", "question_id": question.id},
                    request_id=f"curious-question-{question.id}",
                )
                if result.created:
                    _mark_session_lifecycle_not_needed(result.item["id"])


def _question_payload(question: CuriousQuestion, bucket: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_id": question.id,
        "tier": question.tier,
        "update_type": question.update_type,
        "foundational": question.foundational,
        "target_bucket_id": str(bucket["id"]),
        "target_bucket_key": question.target_bucket_key,
        "target_bucket_name": bucket["display_name"],
        "framing_text": question.framing_text,
        "question_text": question.question_text,
        "question_type": question.question_type,
        "source_label": question.source_label,
        "sort_order": question.sort_order,
        "options": [option.model_dump() for option in question.options],
    }


def _question_from_payload(payload: dict[str, Any]) -> CuriousQuestion:
    return CuriousQuestion(
        id=payload["question_id"],
        tier=payload.get("tier", "bay"),
        update_type=payload.get("update_type", "identity"),
        foundational=payload.get("foundational", False),
        target_bucket_id=payload.get("target_bucket_id"),
        target_bucket_key=payload["target_bucket_key"],
        target_bucket_name=payload["target_bucket_name"],
        framing_text=payload["framing_text"],
        question_text=payload["question_text"],
        question_type=payload.get("question_type", "single_choice"),
        source_label=payload.get("source_label", "Bay"),
        sort_order=payload.get("sort_order", 0),
        options=[CuriousOption(**option) for option in payload["options"]],
    )


def _build_self_profile(answers: list[CuriousAnswerSummary]) -> str:
    identity_answers = [answer for answer in answers if answer.update_type == "identity"]
    if not identity_answers:
        return "I do not know enough yet. Answer Curious questions to build this profile."
    sentences = [_identity_sentence(answer.bucket_update_text) for answer in identity_answers]
    return " ".join(sentence for sentence in sentences if sentence)


def _identity_sentence(text: str) -> str:
    sentence = text.strip()
    replacements = (
        ("Person is ", "You're "),
        ("Person's ", "Your "),
        ("Person does ", "You do "),
        ("Person actively ", "You actively "),
        ("Person thinks ", "You think "),
        ("Person notices ", "You notice "),
        ("Person would ", "You would "),
        ("The person's ", "Your "),
        ("The person is ", "You're "),
        ("The person most ", "You most "),
        ("The person does ", "You do "),
        ("Most of the person's ", "Most of your "),
        ("Over the next year, the person ", "Over the next year, you "),
        ("A good next year means the person ", "A good next year means you "),
        ("Sleep is the part of health the person ", "Sleep is the part of health you "),
        ("Movement is the part of health the person ", "Movement is the part of health you "),
        ("Food is the part of health the person ", "Food is the part of health you "),
        ("Stress management is the part of health the person ", "Stress management is the part of health you "),
        ("Medical follow-through is the part of health the person ", "Medical follow-through is the part of health you "),
    )
    for before, after in replacements:
        if sentence.startswith(before):
            return after + sentence[len(before):]
    return sentence


def _persist_direct_connection_and_updates(
    *,
    life_item_id: UUID,
    bucket_id: UUID,
    bucket_label: str,
    question: CuriousQuestion,
    option: CuriousOption,
) -> None:
    chunk_content = f"{question.question_text}\nAnswer: {option.label}"
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO item_connections (
                    source_life_item_id, target_type, target_id, target_label,
                    strength, connection_note, review_source
                )
                VALUES (%s, 'story_bucket', %s, %s, 1.0, %s, 'curious_direct')
                ON CONFLICT (source_life_item_id, target_type, target_id)
                DO UPDATE SET
                    target_label = EXCLUDED.target_label,
                    strength = EXCLUDED.strength,
                    connection_note = EXCLUDED.connection_note,
                    review_source = EXCLUDED.review_source,
                    created_at = now()
                """,
                (
                    life_item_id,
                    str(bucket_id),
                    bucket_label,
                    f"Curious onboarding question explicitly targets the {bucket_label} Story Bucket.",
                ),
            )
            cur.execute(
                """
                INSERT INTO bucket_updates (
                    story_bucket_id, life_item_id, update_text, source_event
                )
                VALUES (%s, %s, %s, %s)
                """,
                (
                    bucket_id,
                    life_item_id,
                    option.bucket_update_text,
                    Jsonb(
                        {
                            "source": f"curious_{question.tier}",
                            "question_id": question.id,
                            "tier": question.tier,
                            "update_type": question.update_type,
                            "foundational": question.foundational,
                        }
                    ),
                ),
            )
            cur.execute(
                """
                INSERT INTO knowledge_chunks (life_item_id, content, source_type, metadata)
                VALUES (%s, %s, 'curious_answer', %s)
                """,
                (
                    life_item_id,
                    chunk_content,
                    Jsonb(
                        {
                            "question_id": question.id,
                            "tier": question.tier,
                            "update_type": question.update_type,
                            "foundational": question.foundational,
                            "target_bucket_key": question.target_bucket_key,
                        }
                    ),
                ),
            )
            cur.execute(
                """
                UPDATE life_items
                SET connection_status = 'complete',
                    chunk_status = 'complete',
                    bucket_update_status = 'complete',
                    updated_at = now()
                WHERE id = %s
                """,
                (life_item_id,),
            )


def _mark_session_lifecycle_not_needed(session_id: UUID | str) -> None:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE life_items
                SET connection_status = 'complete',
                    chunk_status = 'not_needed',
                    bucket_update_status = 'not_needed',
                    updated_at = now()
                WHERE id = %s
                """,
                (session_id,),
            )


def _update_session_answer_count(session_id: UUID | str) -> None:
    count = len(_answers_for_session(session_id))
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE life_items
                SET payload = jsonb_set(payload, '{answered_count}', to_jsonb(%s::int)),
                    updated_at = now()
                WHERE id = %s
                """,
                (count, session_id),
            )


def _mark_session_completed(session_id: UUID | str) -> None:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE life_items
                SET payload = jsonb_set(payload, '{completed_at}', to_jsonb(%s::text)),
                    updated_at = now()
                WHERE id = %s
                """,
                (datetime.now(timezone.utc).isoformat(), session_id),
            )


def _question_by_id(question_id: str) -> CuriousQuestion:
    for question in (*ONBOARDING_QUESTIONS, *BAY_QUESTIONS):
        if question.id == question_id:
            return question
    raise ValueError(f"Unknown Curious question: {question_id}")


def _option_by_id(question: CuriousQuestion, option_id: str) -> CuriousOption:
    for option in question.options:
        if option.id == option_id:
            return option
    raise ValueError(f"Unknown option {option_id} for Curious question {question.id}")


def _hydrate_question(question: CuriousQuestion) -> CuriousQuestion:
    bucket = _bucket_by_key(question.target_bucket_key)
    return question.model_copy(update={"target_bucket_id": bucket["id"], "target_bucket_name": bucket["display_name"]})


def _bucket_by_key(stable_key: str) -> dict[str, Any]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, stable_key, display_name
                FROM story_buckets
                WHERE stable_key = %s AND status = 'active'
                """,
                (stable_key,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Curious target Story Bucket is missing: {stable_key}")
            return dict(row)
