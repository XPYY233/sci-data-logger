from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
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


def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Reject requests when SCI_DATA_LOGGER_API_KEY is configured and the
    header is missing or wrong.

    When the setting is unset / empty, ALL requests pass — this keeps
    development and existing test suites working without auth scaffolding.
    Production deployments should set SCI_DATA_LOGGER_API_KEY to a strong
    random value (≥ 32 hex chars).
    """
    configured = get_settings().api_key
    if not configured:
        return
    if not x_api_key or x_api_key != configured:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid X-API-Key header",
            headers={"WWW-Authenticate": 'ApiKey realm="sci-data-logger"'},
        )


# /health stays open for liveness probes (k8s, load balancer) which typically
# can't supply auth headers. Everything else goes on `router` with a
# router-level Depends(require_api_key).
health_router = APIRouter()
router = APIRouter(dependencies=[Depends(require_api_key)])

SAFE_PATH_PART_RE = re.compile(r"[^A-Za-z0-9._-]+")


class StatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReviewStatus


@health_router.get("/health")
def health(
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    """Liveness + readiness probe.

    - Always returns the static configuration snapshot (app name, version,
      model id, whether DashScope key is configured, whether API-key auth
      is enforced).
    - Runs ``SELECT 1`` against the DB. On failure returns HTTP 503
      ``{"status": "degraded", ...}`` so monitoring can tell the difference
      between "process alive but DB broken" and "fully healthy".
    """
    settings = get_settings()
    result: dict[str, object] = {
        "app": settings.app_name,
        "version": settings.app_version,
        "vlm_model": settings.qwen_vlm_model,
        "dashscope_configured": bool(settings.dashscope_api_key),
        "api_key_enforced": bool(settings.api_key),
    }
    try:
        session.execute(text("SELECT 1"))
        result["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 — health endpoint logs and degrades
        result["database"] = f"error: {exc.__class__.__name__}"
        result["status"] = "degraded"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return result
    result["status"] = "ok"
    return result


@router.post("/experiments/draft", response_model=ExperimentRecord)
def create_experiment_draft(
    request: DraftExperimentMetadataRequest,
    response: Response,
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
    orchestrator = ExperimentOrchestrator()
    record = orchestrator.create_draft(draft_request)
    _, rejected_locked = repository.merge_record(session, record, orchestrator)
    if rejected_locked:
        response.headers["Locked-Append-Rejected"] = "true"
    session.flush()
    return repository.get_record(session, record.experiment_id) or record


@router.post("/experiments/draft/upload", response_model=ExperimentRecord)
def create_experiment_draft_from_uploads(
    response: Response,
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
    image_pairs = _save_uploads(images, settings, experiment_id, "images")
    instrument_pairs = _save_uploads(
        instrument_files,
        settings,
        experiment_id,
        "instrument_files",
    )
    image_paths = [p for p, _ in image_pairs]
    instrument_file_paths = [p for p, _ in instrument_pairs]
    path_to_hash: dict[str, str] = {}
    for p, h in image_pairs:
        path_to_hash[str(p)] = h
    for p, h in instrument_pairs:
        path_to_hash[str(p)] = h
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
    orchestrator = ExperimentOrchestrator()
    record = orchestrator.create_draft(draft_request)
    _attach_checksums(record, path_to_hash)
    _, rejected_locked = repository.merge_record(session, record, orchestrator)
    if rejected_locked:
        response.headers["Locked-Append-Rejected"] = "true"
    session.flush()
    return repository.get_record(session, record.experiment_id) or record


@router.post("/experiments/{experiment_id}/pages", response_model=ExperimentRecord)
def append_pages_to_draft(
    experiment_id: str,
    response: Response,
    images: Annotated[list[UploadFile] | None, File()] = None,
    instrument_files: Annotated[list[UploadFile] | None, File()] = None,
    session: Session = Depends(get_session),
) -> ExperimentRecord:
    """Append additional pages / instrument files to an existing draft.

    Orchestrator re-runs cross-page consolidation against the merged page set.
    404 if experiment_id does not exist.
    """
    existing = repository.get_record(session, experiment_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="experiment not found")

    if not (images or instrument_files):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no files provided",
        )

    settings = get_settings()
    image_pairs = _save_uploads(images, settings, experiment_id, "images")
    instrument_pairs = _save_uploads(
        instrument_files, settings, experiment_id, "instrument_files"
    )
    image_paths = [p for p, _ in image_pairs]
    instrument_file_paths = [p for p, _ in instrument_pairs]
    path_to_hash: dict[str, str] = {}
    for p, h in image_pairs:
        path_to_hash[str(p)] = h
    for p, h in instrument_pairs:
        path_to_hash[str(p)] = h
    draft_request = DraftExperimentRequest(
        experiment_id=experiment_id,
        image_paths=image_paths,
        instrument_file_paths=instrument_file_paths,
        project_id=existing.project_id,
        group_id=existing.group_id,
        operator=existing.operator,
        title=existing.title,
    )
    orchestrator = ExperimentOrchestrator()
    delta = orchestrator.create_draft(draft_request)
    _attach_checksums(delta, path_to_hash)
    _, rejected_locked = repository.merge_record(session, delta, orchestrator)
    if rejected_locked:
        response.headers["Locked-Append-Rejected"] = "true"
    return repository.get_record(session, experiment_id)


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
    try:
        record = repository.update_review_status(session, experiment_id, body.status)
    except repository.IllegalStatusTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
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


# Whitelist of suffixes accepted by upload endpoints, keyed by upload "kind".
# Kept in sync with what DocumentProcessor.analyze_pages / InstrumentAdapter
# actually handle — anything else is rejected up front (415) rather than
# silently written to disk and producing a "unsupported file type" PagePacket
# downstream. The "images" kind includes PDFs and text notes because the
# document processor accepts those alongside raster images on the same input
# channel.
_UPLOAD_ALLOWLISTS: dict[str, set[str]] = {
    "images": {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".pdf", ".txt", ".md"},
    "instrument_files": {".csv", ".tsv", ".txt", ".md", ".log", ".report"},
}


def _reject_disallowed_suffix(upload: UploadFile, allowed: set[str], kind: str) -> None:
    name = (upload.filename or "").lower()
    suffix = Path(name).suffix
    if suffix not in allowed:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"{kind}: unsupported file extension '{suffix or '(none)'}'",
        )


def _save_uploads(
    uploads: list[UploadFile] | None,
    settings: Settings,
    experiment_id: str,
    kind: str,
) -> list[tuple[Path, str]]:
    try:
        allowed = _UPLOAD_ALLOWLISTS[kind]
    except KeyError as exc:
        # Defensive: future callers passing a typo'd kind would silently get the
        # wrong allowlist with the old branch-based selection.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"unknown upload kind '{kind}'",
        ) from exc
    saved: list[tuple[Path, str]] = []
    for upload in uploads or []:
        _reject_disallowed_suffix(upload, allowed, kind)
        saved.append(_save_upload(upload, settings, experiment_id, kind))
    return saved


def _save_upload(
    upload: UploadFile,
    settings: Settings,
    experiment_id: str,
    kind: str,
) -> tuple[Path, str]:
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
    hasher = hashlib.sha256()
    with destination.open("wb") as output:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
            output.write(chunk)
    return destination, hasher.hexdigest()


def _attach_checksums(record: ExperimentRecord, path_to_hash: dict[str, str]) -> None:
    """Post-fill SHA-256 checksums onto pages and source assets by source_path match.

    The orchestrator does not know about content hashing; the API layer computes
    hashes while streaming uploads to disk and attaches them here so downstream
    merge_record can dedup pages by content rather than by UUID-prefixed path.
    """
    if not path_to_hash:
        return
    for page in record.pages:
        digest = path_to_hash.get(page.source_path)
        if digest:
            page.content_checksum = digest
    for asset in record.source_assets:
        digest = path_to_hash.get(asset.source_path)
        if digest:
            asset.checksum = digest


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
