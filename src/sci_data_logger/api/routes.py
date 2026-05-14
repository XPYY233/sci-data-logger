from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session

from sci_data_logger.config import Settings, get_settings
from sci_data_logger.db import repository
from sci_data_logger.db.session import get_session
from sci_data_logger.schemas import (
    DraftExperimentMetadataRequest,
    DraftExperimentRequest,
    ExperimentRecord,
    ExperimentSummary,
    ReviewStatus,
)
from sci_data_logger.services.orchestrator import ExperimentOrchestrator

router = APIRouter()
SAFE_PATH_PART_RE = re.compile(r"[^A-Za-z0-9._-]+")


class StatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReviewStatus


@router.get("/health")
def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "vlm_model": settings.qwen_vlm_model,
        "dashscope_configured": bool(settings.dashscope_api_key),
    }


@router.post("/experiments/draft", response_model=ExperimentRecord)
def create_experiment_draft(
    request: DraftExperimentMetadataRequest,
    session: Session = Depends(get_session),
) -> ExperimentRecord:
    """Create a draft from JSON metadata only.

    HTTP clients must use the upload endpoint for files so JSON bodies cannot
    point the server at arbitrary local paths.
    """

    draft_request = DraftExperimentRequest(
        experiment_id=request.experiment_id,
        user_fields=request.user_fields,
        project_id=request.project_id,
        group_id=request.group_id,
        operator=request.operator,
        title=request.title,
    )
    record = ExperimentOrchestrator().create_draft(draft_request)
    repository.save_record(session, record)
    return record


@router.post("/experiments/draft/upload", response_model=ExperimentRecord)
def create_experiment_draft_from_uploads(
    experiment_id: Annotated[str, Form()],
    images: Annotated[list[UploadFile] | None, File()] = None,
    instrument_files: Annotated[list[UploadFile] | None, File()] = None,
    user_fields: Annotated[str | None, Form()] = None,
    project_id: Annotated[str | None, Form()] = None,
    group_id: Annotated[str | None, Form()] = None,
    operator: Annotated[str | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
    session: Session = Depends(get_session),
) -> ExperimentRecord:
    settings = get_settings()
    image_paths = _save_uploads(images, settings, experiment_id, "images")
    instrument_file_paths = _save_uploads(
        instrument_files,
        settings,
        experiment_id,
        "instrument_files",
    )
    draft_request = DraftExperimentRequest(
        experiment_id=experiment_id,
        image_paths=image_paths,
        instrument_file_paths=instrument_file_paths,
        user_fields=_parse_user_fields(user_fields),
        project_id=project_id,
        group_id=group_id,
        operator=operator,
        title=title,
    )
    record = ExperimentOrchestrator().create_draft(draft_request)
    repository.save_record(session, record)
    return record


@router.get("/experiments", response_model=list[ExperimentSummary])
def list_experiments(
    project_id: str | None = Query(default=None),
    group_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[ExperimentSummary]:
    rows = repository.list_records(
        session,
        project_id=project_id,
        group_id=group_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return [
        ExperimentSummary(
            experiment_id=r.experiment_id,
            project_id=r.project_id,
            group_id=r.group_id,
            operator=r.operator,
            title=r.title,
            status=r.status,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.get("/experiments/{experiment_id}", response_model=ExperimentRecord)
def get_experiment(
    experiment_id: str,
    session: Session = Depends(get_session),
) -> ExperimentRecord:
    record = repository.get_record(session, experiment_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="experiment not found")
    return record


@router.patch("/experiments/{experiment_id}/status", response_model=ExperimentRecord)
def patch_experiment_status(
    experiment_id: str,
    body: StatusUpdateRequest,
    session: Session = Depends(get_session),
) -> ExperimentRecord:
    record = repository.update_review_status(session, experiment_id, body.status)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="experiment not found")
    return record


@router.post(
    "/experiments/{experiment_id}/review-issues/{issue_id}/resolve",
    response_model=ExperimentRecord,
)
def resolve_review_issue_endpoint(
    experiment_id: str,
    issue_id: str,
    session: Session = Depends(get_session),
) -> ExperimentRecord:
    if repository.get_record(session, experiment_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="experiment not found")
    record = repository.resolve_review_issue(session, experiment_id, issue_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="review issue not found")
    return record


@router.delete("/experiments/{experiment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_experiment(
    experiment_id: str,
    session: Session = Depends(get_session),
) -> None:
    deleted = repository.delete_record(session, experiment_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="experiment not found")
    return None


@router.get("/runtime/config")
def runtime_config() -> dict[str, object]:
    settings = get_settings()
    return {
        "qwen_base_url": settings.qwen_base_url,
        "qwen_vlm_model": settings.qwen_vlm_model,
        "instrument_registry_configured": settings.instrument_registry.exists(),
        "group_template_configured": settings.group_template.exists(),
        "storage_configured": settings.storage_root.exists() or bool(settings.storage_root),
    }


def _save_uploads(
    uploads: list[UploadFile] | None,
    settings: Settings,
    experiment_id: str,
    kind: str,
) -> list[Path]:
    return [_save_upload(upload, settings, experiment_id, kind) for upload in uploads or []]


def _save_upload(
    upload: UploadFile,
    settings: Settings,
    experiment_id: str,
    kind: str,
) -> Path:
    storage_root = settings.ensure_storage().resolve()
    destination_dir = storage_root / "api_uploads" / _safe_path_part(experiment_id) / kind
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = (destination_dir / f"{uuid4().hex}_{_safe_filename(upload.filename)}").resolve()
    if not destination.is_relative_to(storage_root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid upload destination.",
        )
    upload.file.seek(0)
    with destination.open("wb") as output:
        shutil.copyfileobj(upload.file, output)
    return destination


def _parse_user_fields(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_fields must be a JSON object.",
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_fields must be a JSON object.",
        )
    return parsed


def _safe_path_part(value: str) -> str:
    return SAFE_PATH_PART_RE.sub("_", value).strip("._-")[:80] or "draft"


def _safe_filename(filename: str | None) -> str:
    raw_name = Path((filename or "upload").replace("\\", "/")).name
    safe_name = SAFE_PATH_PART_RE.sub("_", raw_name).strip("._")
    return safe_name[:120] or "upload"
