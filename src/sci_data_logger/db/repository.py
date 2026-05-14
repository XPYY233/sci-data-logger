from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from sci_data_logger.db.models import ExperimentRecordORM
from sci_data_logger.schemas import ExperimentRecord, ReviewStatus


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
