from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from sci_data_logger.db.models import ExperimentRecordORM
from sci_data_logger.schemas import ExperimentRecord, PagePacket, ReviewIssue, ReviewStatus

if TYPE_CHECKING:  # pragma: no cover - circular at runtime
    from sci_data_logger.services.orchestrator import ExperimentOrchestrator


_TERMINAL_STATUSES = {ReviewStatus.REVIEWED, ReviewStatus.LOCKED}

# Status-transition graph. LOCKED has no outgoing edges (terminal).
# DRAFT can also go directly to REVIEWED for the trivial case where an empty
# draft is reviewed-on-creation, but the typical path is DRAFT → NEEDS_REVIEW.
_ALLOWED_STATUS_TRANSITIONS: dict[ReviewStatus, set[ReviewStatus]] = {
    ReviewStatus.DRAFT: {ReviewStatus.NEEDS_REVIEW, ReviewStatus.REVIEWED},
    ReviewStatus.NEEDS_REVIEW: {ReviewStatus.REVIEWED, ReviewStatus.DRAFT},
    ReviewStatus.REVIEWED: {ReviewStatus.LOCKED, ReviewStatus.NEEDS_REVIEW},
    ReviewStatus.LOCKED: set(),
}


class IllegalStatusTransition(ValueError):
    """Raised by update_review_status when a transition is not in the allowlist.

    The API layer converts this to HTTP 409.
    """


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def save_record(session: Session, record: ExperimentRecord) -> ExperimentRecordORM:
    """Insert or update the experiment row. Returns the persisted ORM object."""
    existing = session.get(ExperimentRecordORM, record.experiment_id)
    payload = record.model_dump_json()
    status_value = str(record.status)
    now = _utcnow()
    if existing is None:
        row = ExperimentRecordORM(
            experiment_id=record.experiment_id,
            project_id=record.project_id,
            group_id=record.group_id,
            operator=record.operator,
            title=record.title,
            status=status_value,
            record_json=payload,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return row
    existing.project_id = record.project_id
    existing.group_id = record.group_id
    existing.operator = record.operator
    existing.title = record.title
    existing.status = status_value
    existing.record_json = payload
    existing.updated_at = now
    session.add(existing)
    session.flush()
    return existing


def get_record(session: Session, experiment_id: str) -> ExperimentRecord | None:
    row = session.get(ExperimentRecordORM, experiment_id)
    if row is None:
        return None
    return ExperimentRecord.model_validate_json(row.record_json)


def list_records(
    session: Session,
    *,
    project_id: str | None = None,
    group_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ExperimentRecordORM]:
    stmt = select(ExperimentRecordORM)
    if project_id is not None:
        stmt = stmt.where(ExperimentRecordORM.project_id == project_id)
    if group_id is not None:
        stmt = stmt.where(ExperimentRecordORM.group_id == group_id)
    if status is not None:
        stmt = stmt.where(ExperimentRecordORM.status == status)
    stmt = stmt.order_by(ExperimentRecordORM.updated_at.desc()).limit(limit).offset(offset)
    return list(session.exec(stmt).all())


def delete_record(session: Session, experiment_id: str) -> bool:
    row = session.get(ExperimentRecordORM, experiment_id)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def update_review_status(
    session: Session,
    experiment_id: str,
    new_status: ReviewStatus,
) -> ExperimentRecord | None:
    # Validate input is a member of the enum (raises ValueError if not).
    new_status = ReviewStatus(new_status)
    row = session.get(ExperimentRecordORM, experiment_id)
    if row is None:
        return None
    record = ExperimentRecord.model_validate_json(row.record_json)
    current = (
        ReviewStatus(record.status) if not isinstance(record.status, ReviewStatus) else record.status
    )
    # No-op is fine; only block actual transitions not in the allowlist.
    if new_status != current and new_status not in _ALLOWED_STATUS_TRANSITIONS.get(current, set()):
        raise IllegalStatusTransition(
            f"illegal status transition: {current.value} -> {new_status.value}"
        )
    record.status = new_status
    row.record_json = record.model_dump_json()
    row.status = str(new_status)
    row.updated_at = _utcnow()
    session.add(row)
    session.flush()
    return record


def resolve_review_issue(
    session: Session,
    experiment_id: str,
    issue_id: str,
) -> ExperimentRecord | None:
    row = session.get(ExperimentRecordORM, experiment_id)
    if row is None:
        return None
    record = ExperimentRecord.model_validate_json(row.record_json)
    before = len(record.review_issues)
    record.review_issues = [i for i in record.review_issues if i.issue_id != issue_id]
    if len(record.review_issues) == before:
        return None
    row.record_json = record.model_dump_json()
    row.updated_at = _utcnow()
    session.add(row)
    session.flush()
    return record


def merge_record(
    session: Session,
    new_record: ExperimentRecord,
    orchestrator: "ExperimentOrchestrator",
) -> tuple[ExperimentRecordORM, bool]:
    """Upsert with cross-page merge semantics.

    If a row exists for new_record.experiment_id, concatenate pages /
    measurements / source_assets with the existing record, then re-run
    orchestrator's cross-page consolidation. Otherwise behave like save_record.

    Returns a ``(row, rejected_due_to_locked)`` tuple. The boolean is True iff
    the merge was a no-op because the existing record was in the terminal
    LOCKED state; callers (e.g. the upload endpoints) use it to surface a
    ``Locked-Append-Rejected: true`` HTTP response header so clients can tell
    their upload was *not* appended.

    - review_issues: union by issue_id (new ones appended)
    - metadata.user_fields: shallow merge, new wins on key conflict
    - status: terminal statuses (REVIEWED / LOCKED) are preserved against
      downgrades; otherwise the newer status wins

    Page dedup (E2): after concatenating ``combined_pages`` we drop later
    duplicates by ``source_path`` string and emit a single info-severity
    ``ReviewIssue`` describing how many were dropped. Note: upload endpoints
    rewrite each upload to a unique ``<uuid>_filename`` path, so re-uploading
    the same original filename produces a distinct source_path and is NOT
    caught here; this guard exists to defend against duplicate concatenation
    *within* one record (e.g. a buggy double-merge of the same packet).
    """
    existing_row = session.get(ExperimentRecordORM, new_record.experiment_id)
    if existing_row is None:
        return save_record(session, new_record), False

    existing = ExperimentRecord.model_validate_json(existing_row.record_json)

    # Locked records are terminal: refuse to append/merge new content. We
    # still return HTTP 200 with the unchanged record (semantically a no-op
    # so the locked status survives a re-upload attempt), but we also leave
    # an audit-trail ReviewIssue on the existing record so future reviewers
    # see *what* was rejected, and we signal the rejection back to the
    # caller via the second tuple element (used to set a response header).
    existing_status_for_lock_check = (
        ReviewStatus(existing.status) if not isinstance(existing.status, ReviewStatus) else existing.status
    )
    if existing_status_for_lock_check == ReviewStatus.LOCKED:
        audit_issue = ReviewIssue(
            severity="warning",
            title="Upload rejected: record is locked",
            detail=(
                f"Attempted to append {len(new_record.pages)} page(s) and "
                f"{len(new_record.measurements)} measurement(s) to a LOCKED record; "
                f"rejected per status-machine terminal rule. Unlock by transitioning "
                f"out of LOCKED first (impossible — LOCKED is terminal; create a new "
                f"experiment_id to capture additional pages)."
            ),
        )
        existing.review_issues.append(audit_issue)
        existing_row.record_json = existing.model_dump_json()
        existing_row.updated_at = _utcnow()
        session.add(existing_row)
        session.flush()
        return existing_row, True

    combined_pages: list[PagePacket] = [*existing.pages, *new_record.pages]
    combined_measurements = [*existing.measurements, *new_record.measurements]
    combined_source_assets = [*existing.source_assets, *new_record.source_assets]

    # E2: dedup pages by source_path. Keep first occurrence; drop later ones.
    seen_paths: set[str] = set()
    deduped_pages: list[PagePacket] = []
    dropped_count = 0
    for page in combined_pages:
        if page.source_path in seen_paths:
            dropped_count += 1
            continue
        seen_paths.add(page.source_path)
        deduped_pages.append(page)
    dedup_issue: ReviewIssue | None = None
    if dropped_count:
        dedup_issue = ReviewIssue(
            severity="info",
            title="Duplicate page(s) ignored",
            detail=(
                f"Skipped {dropped_count} page(s) with source_paths already in record."
            ),
        )
    combined_pages = deduped_pages

    materials_catalog = orchestrator._merge_materials_catalog(combined_pages)
    instruments_catalog = orchestrator._merge_instruments_catalog(combined_pages)
    samples_catalog = orchestrator._merge_samples_catalog(combined_pages)
    events, resolution_issues = orchestrator._resolve_and_merge_events(
        combined_pages, materials_catalog, instruments_catalog, samples_catalog
    )

    # Union review_issues by issue_id; preserve existing order. Append the
    # E2 dedup issue (if any) so reviewers see the dropped-page audit trail.
    seen_issue_ids: set[str] = set()
    merged_issues = []
    issue_sources = [*existing.review_issues, *new_record.review_issues, *resolution_issues]
    if dedup_issue is not None:
        issue_sources.append(dedup_issue)
    for issue in issue_sources:
        if issue.issue_id in seen_issue_ids:
            continue
        seen_issue_ids.add(issue.issue_id)
        merged_issues.append(issue)

    existing_meta = dict(existing.metadata or {})
    new_meta = dict(new_record.metadata or {})
    merged_user_fields = {
        **(existing_meta.get("user_fields") or {}),
        **(new_meta.get("user_fields") or {}),
    }
    merged_metadata = {**existing_meta, **new_meta, "user_fields": merged_user_fields}

    existing_status = ReviewStatus(existing.status) if not isinstance(existing.status, ReviewStatus) else existing.status
    new_status = ReviewStatus(new_record.status) if not isinstance(new_record.status, ReviewStatus) else new_record.status
    merged_status = existing_status if existing_status in _TERMINAL_STATUSES else new_status

    merged_record = ExperimentRecord(
        experiment_id=new_record.experiment_id,
        project_id=new_record.project_id or existing.project_id,
        group_id=new_record.group_id or existing.group_id,
        operator=new_record.operator or existing.operator,
        title=new_record.title or existing.title,
        status=merged_status,
        materials_catalog=materials_catalog,
        instruments_catalog=instruments_catalog,
        samples_catalog=samples_catalog,
        events=events,
        source_assets=combined_source_assets,
        pages=combined_pages,
        measurements=combined_measurements,
        review_issues=merged_issues,
        metadata=merged_metadata,
    )

    existing_row.project_id = merged_record.project_id
    existing_row.group_id = merged_record.group_id
    existing_row.operator = merged_record.operator
    existing_row.title = merged_record.title
    existing_row.status = str(merged_status)
    existing_row.record_json = merged_record.model_dump_json()
    existing_row.updated_at = _utcnow()
    session.add(existing_row)
    session.flush()
    return existing_row, False
