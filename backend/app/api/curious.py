"""HTTP API for the Curious module."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from uuid import UUID

from app.modules.curious import (
    CuriousAnswerCreate,
    CuriousCompletion,
    CuriousOnboardingState,
    CuriousPageState,
    CuriousPendingAnswerCreate,
    CuriousWeaveResult,
    answer_pending_question,
    answer_onboarding_question,
    complete_onboarding_session,
    get_curious_page_state,
    get_onboarding_state,
    weave_pending_curious_updates,
)


router = APIRouter(prefix="/modules/curious", tags=["curious"])


class CuriousCompleteRequest(BaseModel):
    session_id: UUID


@router.get("/onboarding", response_model=CuriousOnboardingState)
def get_onboarding_endpoint() -> CuriousOnboardingState:
    try:
        return get_onboarding_state()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/state", response_model=CuriousPageState)
def get_curious_state_endpoint() -> CuriousPageState:
    try:
        return get_curious_page_state()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/questions/answer", response_model=CuriousPageState)
def answer_pending_question_endpoint(payload: CuriousPendingAnswerCreate) -> CuriousPageState:
    try:
        return answer_pending_question(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/weave-pending", response_model=CuriousWeaveResult)
def weave_pending_curious_endpoint() -> CuriousWeaveResult:
    return weave_pending_curious_updates()


@router.post("/onboarding/answers", response_model=CuriousOnboardingState)
def answer_onboarding_endpoint(payload: CuriousAnswerCreate) -> CuriousOnboardingState:
    try:
        return answer_onboarding_question(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/onboarding/complete", response_model=CuriousCompletion)
def complete_onboarding_endpoint(payload: CuriousCompleteRequest) -> CuriousCompletion:
    try:
        return complete_onboarding_session(payload.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
