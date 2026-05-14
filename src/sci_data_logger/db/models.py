"""Single-table ORM for ExperimentRecord: top-level columns + JSON blob.

Hybrid storage: indexable scalars live in real columns; the rest of the
pydantic ExperimentRecord (catalogs, events, pages, measurements, review
issues) is serialized into ``record_json`` as a single JSON string. The
schema is still evolving (Phase 0 / Phase 1), so normalizing every
relationship now would be premature. SQLite JSON1 keeps filtering viable
when needed, and inserts stay atomic.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExperimentRecordORM(SQLModel, table=True):
    __tablename__ = "experiments"

    experiment_id: str = Field(primary_key=True)
    project_id: str | None = Field(default=None, index=True)
    group_id: str | None = Field(default=None, index=True)
    operator: str | None = None
    title: str | None = None
    status: str = Field(default="draft", index=True)
    record_json: str
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
