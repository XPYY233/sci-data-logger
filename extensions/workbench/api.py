from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from extensions.personalization.config import DEFAULT_LOCAL_ROOT
from extensions.personalization.repository import DEFAULT_DB_PATH
from extensions.personalization.service import (
    analyze_and_store,
    get_user_profile,
    list_available_templates,
    list_user_profiles,
    save_user_profile,
    summarize_effective_profile,
)

router = APIRouter(prefix="/workbench/api", tags=["workbench"])


class UserProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    term_aliases: dict[str, str] = Field(default_factory=dict)
    sample_id_patterns: list[str] = Field(default_factory=list)
    preferred_fields: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    handwriting_notes: list[str] = Field(default_factory=list)


class PersonalizedAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record: dict[str, Any]
    user_id: str | None = None
    experiment_template_id: str | None = None
    instrument_id: str | None = None
    group_id: str = "materials_default"


@router.get("/users")
def get_users() -> list[dict[str, Any]]:
    return list_user_profiles(local_root=DEFAULT_LOCAL_ROOT)


@router.get("/users/{user_id}")
def get_user(user_id: str) -> dict[str, Any]:
    payload = get_user_profile(user_id, local_root=DEFAULT_LOCAL_ROOT)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user profile not found")
    return payload


@router.put("/users/{user_id}")
def put_user(user_id: str, body: UserProfileUpdateRequest) -> dict[str, Any]:
    try:
        return save_user_profile(
            user_id,
            body.model_dump(exclude_none=True),
            local_root=DEFAULT_LOCAL_ROOT,
            db_path=DEFAULT_DB_PATH,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/templates")
def get_templates() -> dict[str, list[dict[str, Any]]]:
    return list_available_templates(local_root=DEFAULT_LOCAL_ROOT)


@router.get("/effective-profile")
def get_effective_profile(
    user_id: str | None = Query(default=None),
    experiment_template_id: str | None = Query(default=None),
    instrument_id: str | None = Query(default=None),
    group_id: str = Query(default="materials_default"),
) -> dict[str, Any]:
    return summarize_effective_profile(
        user_id=user_id,
        experiment_template_id=experiment_template_id,
        instrument_id=instrument_id,
        group_id=group_id,
        local_root=DEFAULT_LOCAL_ROOT,
    )


@router.post("/personalized-analysis")
def create_personalized_analysis(body: PersonalizedAnalysisRequest) -> dict[str, Any]:
    analysis = analyze_and_store(
        body.record,
        user_id=body.user_id,
        experiment_template_id=body.experiment_template_id,
        instrument_id=body.instrument_id,
        group_id=body.group_id,
        local_root=DEFAULT_LOCAL_ROOT,
        db_path=DEFAULT_DB_PATH,
    )
    profile_summary = summarize_effective_profile(
        user_id=body.user_id,
        experiment_template_id=body.experiment_template_id,
        instrument_id=body.instrument_id,
        group_id=body.group_id,
        local_root=DEFAULT_LOCAL_ROOT,
    )
    return {
        "analysis_run_id": analysis["analysis_run_id"],
        "profile_context": analysis["profile_context"],
        "profile_summary": profile_summary,
        "normalized_step_changes": [
            step
            for step in analysis["normalized_steps"]
            if step["raw_step_type"] != step["normalized_step_type"]
        ],
        "missing_required_fields": analysis["missing_required_fields"],
        "review_issues": analysis["review_issues"],
        "raw_analysis": analysis,
    }
