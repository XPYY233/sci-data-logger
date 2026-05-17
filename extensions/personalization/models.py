from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class UserProfile:
    user_id: str
    display_name: str
    term_aliases: dict[str, str] = field(default_factory=dict)
    sample_id_patterns: list[str] = field(default_factory=list)
    preferred_fields: list[str] = field(default_factory=list)
    required_fields: list[str] = field(default_factory=list)
    handwriting_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExperimentTemplate:
    template_id: str
    display_name: str
    required_fields: list[str] = field(default_factory=list)
    preferred_fields: list[str] = field(default_factory=list)
    common_step_types: list[str] = field(default_factory=list)
    term_aliases: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class InstrumentTemplate:
    instrument_id: str
    display_name: str
    technique: str
    file_patterns: list[str] = field(default_factory=list)
    field_mappings: dict[str, str] = field(default_factory=dict)
    focus_parameters: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
