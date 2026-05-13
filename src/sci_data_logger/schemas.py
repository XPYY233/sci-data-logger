from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class SourceType(StrEnum):
    USER_INPUT = "user_input"
    NOTEBOOK_IMAGE = "notebook_image"
    OCR_TEXT = "ocr_text"
    INSTRUMENT_FILE = "instrument_file"
    REPORT_FILE = "report_file"
    SYSTEM_INFERENCE = "system_inference"
    MANUAL_REVIEW = "manual_review"


class ReviewStatus(StrEnum):
    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    REVIEWED = "reviewed"
    LOCKED = "locked"


class EvidenceRef(BaseModel):
    source_type: SourceType
    source_id: str
    locator: dict[str, Any] = Field(default_factory=dict)
    text: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class FieldValue(BaseModel):
    value: Any
    unit: str | None = None
    source_refs: list[EvidenceRef] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    reviewed: bool = False


class DataAsset(BaseModel):
    asset_id: str = Field(default_factory=lambda: new_id("asset"))
    source_path: str
    source_type: SourceType
    media_type: str | None = None
    checksum: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MaterialInput(BaseModel):
    material_id: str = Field(default_factory=lambda: new_id("mat"))
    name: str
    amount: FieldValue | None = None
    role: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Material(BaseModel):
    """Catalog-level material entry, deduplicated across pages."""
    material_id: str = Field(default_factory=lambda: new_id("mat"))
    canonical_name: str
    display_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    chemical_formula: str | None = None
    role: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProtocolStep(BaseModel):
    step_id: str = Field(default_factory=lambda: new_id("step"))
    step_type: str
    sequence_index: int
    description: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    parameters: dict[str, FieldValue] = Field(default_factory=dict)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)


class InstrumentProfile(BaseModel):
    instrument_id: str
    display_name: str
    technique: str
    manufacturer: str | None = None
    model: str | None = None
    aliases: list[str] = Field(default_factory=list)
    file_patterns: list[str] = Field(default_factory=list)
    parser_plugin: str = "generic_text_report"
    field_mappings: dict[str, str] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)


class Instrument(BaseModel):
    """Catalog-level instrument entry. `instrument_label` 例如实验室内的红圈编号 '707'。"""
    instrument_id: str = Field(default_factory=lambda: new_id("instr"))
    technique: str           # ball_mill / xrd / sem / raman / eis / heat_treatment / weigh / other
    instrument_label: str | None = None
    location: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventIO(BaseModel):
    """Event input/output edge — references a Material by id, optionally with amount."""
    material_ref: str
    amount: FieldValue | None = None
    notes: str | None = None


class EventOutput(EventIO):
    """Output edge with additional product-level fields."""
    target_phase: str | None = None
    failure_marker: str | None = None


class ExperimentEvent(BaseModel):
    """Atomic unit of the experiment timeline."""
    event_id: str = Field(default_factory=lambda: new_id("evt"))
    sequence_index: int

    # Time + space anchors
    date_label: str | None = None
    date_iso: str | None = None
    location: str | None = None
    instrument_ref: str | None = None
    operator: str | None = None

    # Body
    action_type: str
    description: str
    inputs: list[EventIO] = Field(default_factory=list)
    outputs: list[EventOutput] = Field(default_factory=list)
    parameters: dict[str, FieldValue] = Field(default_factory=dict)

    # Edge-case semantic fields
    recipe_ratio: dict[str, Any] | None = None
    equation: str | None = None

    observations: list[FieldValue] = Field(default_factory=list)

    page_ref: str
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)


class MeasurementPacket(BaseModel):
    run_id: str = Field(default_factory=lambda: new_id("run"))
    source_path: str
    technique: str | None = None
    instrument_id: str | None = None
    raw_parameters: dict[str, Any] = Field(default_factory=dict)
    normalized_parameters: dict[str, FieldValue] = Field(default_factory=dict)
    assets: list[DataAsset] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PagePacket(BaseModel):
    page_id: str = Field(default_factory=lambda: new_id("page"))
    source_path: str
    page_types: list[str] = Field(default_factory=lambda: ["unknown"])
    sample_id: str | None = None
    text_blocks: list[str] = Field(default_factory=list)
    table_blocks: list[dict[str, Any]] = Field(default_factory=list)
    extracted_materials: list[MaterialInput] = Field(default_factory=list)
    extracted_steps: list[ProtocolStep] = Field(default_factory=list)
    extracted_observations: list[FieldValue] = Field(default_factory=list)
    extracted_instruments: list[str] = Field(default_factory=list)
    extracted_facts: dict[str, FieldValue] = Field(default_factory=dict)
    open_questions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    review_required: bool = False
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    raw_model_output: dict[str, Any] = Field(default_factory=dict)

    @property
    def page_type(self) -> str:
        return self.page_types[0] if self.page_types else "unknown"


class ReviewIssue(BaseModel):
    issue_id: str = Field(default_factory=lambda: new_id("issue"))
    severity: str = "warning"
    title: str
    detail: str
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class ExperimentRecord(BaseModel):
    experiment_id: str
    project_id: str | None = None
    group_id: str | None = None
    operator: str | None = None
    title: str | None = None
    status: ReviewStatus = ReviewStatus.DRAFT
    source_assets: list[DataAsset] = Field(default_factory=list)
    pages: list[PagePacket] = Field(default_factory=list)
    materials: list[MaterialInput] = Field(default_factory=list)
    steps: list[ProtocolStep] = Field(default_factory=list)
    measurements: list[MeasurementPacket] = Field(default_factory=list)
    observations: list[FieldValue] = Field(default_factory=list)
    review_issues: list[ReviewIssue] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DraftExperimentRequest(BaseModel):
    experiment_id: str
    image_paths: list[Path] = Field(default_factory=list)
    instrument_file_paths: list[Path] = Field(default_factory=list)
    user_fields: dict[str, Any] = Field(default_factory=dict)
    project_id: str | None = None
    group_id: str | None = None
    operator: str | None = None
    title: str | None = None


class DraftExperimentMetadataRequest(BaseModel):
    """API JSON draft request that intentionally excludes server-local file paths."""

    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    user_fields: dict[str, Any] = Field(default_factory=dict)
    project_id: str | None = None
    group_id: str | None = None
    operator: str | None = None
    title: str | None = None
