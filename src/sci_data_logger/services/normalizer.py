from __future__ import annotations

from typing import Any

from sci_data_logger.schemas import EvidenceRef, FieldValue, SourceType


class Normalizer:
    """Normalize raw fields into canonical parameter names."""

    def normalize_parameters(
        self,
        raw_parameters: dict[str, Any],
        field_mappings: dict[str, str],
        source_id: str,
        source_type: SourceType,
    ) -> dict[str, FieldValue]:
        normalized: dict[str, FieldValue] = {}
        for raw_key, raw_value in raw_parameters.items():
            canonical_key = field_mappings.get(raw_key) or field_mappings.get(raw_key.lower())
            if not canonical_key:
                continue
            normalized[canonical_key] = FieldValue(
                value=raw_value,
                source_refs=[
                    EvidenceRef(
                        source_type=source_type,
                        source_id=source_id,
                        locator={"raw_key": raw_key},
                        confidence=0.85,
                    )
                ],
                confidence=0.85,
            )
        return normalized
