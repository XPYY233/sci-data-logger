from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from sci_data_logger.config import Settings, get_settings
from sci_data_logger.schemas import (
    DraftExperimentMetadataRequest,
    DraftExperimentRequest,
    ExperimentRecord,
)
from sci_data_logger.services.orchestrator import ExperimentOrchestrator

router = APIRouter()
SAFE_PATH_PART_RE = re.compile(r"[^A-Za-z0-9._-]+")


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
def create_experiment_draft(request: DraftExperimentMetadataRequest) -> ExperimentRecord:
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
    return ExperimentOrchestrator().create_draft(draft_request)


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
    return ExperimentOrchestrator().create_draft(draft_request)


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
