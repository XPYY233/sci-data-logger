from __future__ import annotations

import fnmatch
import json
from pathlib import Path

from sci_data_logger.adapters import GenericCSVAdapter, GenericTextReportAdapter, InstrumentAdapter
from sci_data_logger.config import Settings, get_settings
from sci_data_logger.schemas import (
    DataAsset,
    InstrumentProfile,
    MeasurementPacket,
    SourceType,
)
from sci_data_logger.services.normalizer import Normalizer


class InstrumentService:
    """Resolve instrument profiles and parse measurement files."""

    def __init__(self, settings: Settings | None = None, normalizer: Normalizer | None = None) -> None:
        self.settings = settings or get_settings()
        self.normalizer = normalizer or Normalizer()
        self.profiles = self._load_profiles(self.settings.instrument_registry)
        self.adapters: list[InstrumentAdapter] = [
            GenericCSVAdapter(),
            GenericTextReportAdapter(),
        ]

    def parse_file(self, path: Path) -> MeasurementPacket:
        profile = self.match_profile(path)
        adapter = self._select_adapter(path, profile)
        if adapter is None:
            return MeasurementPacket(
                source_path=str(path),
                warnings=[f"没有找到可处理该文件的仪器适配器：{path.suffix or 'unknown'}"],
                assets=[self._asset_for(path)],
            )

        result = adapter.parse(path, profile)
        normalized = self.normalizer.normalize_parameters(
            result.raw_parameters,
            profile.field_mappings if profile else {},
            source_id=str(path),
            source_type=SourceType.INSTRUMENT_FILE,
        )
        return MeasurementPacket(
            source_path=str(path),
            technique=profile.technique if profile else None,
            instrument_id=profile.instrument_id if profile else None,
            raw_parameters=result.raw_parameters,
            normalized_parameters=normalized,
            assets=[self._asset_for(path)],
            warnings=result.warnings,
        )

    def match_profile(self, path: Path) -> InstrumentProfile | None:
        filename = path.name.lower()
        for profile in self.profiles:
            values = [profile.display_name, profile.instrument_id, *profile.aliases]
            if any(value and value.lower() in filename for value in values):
                return profile
            if any(fnmatch.fnmatch(filename, pattern.lower()) for pattern in profile.file_patterns):
                return profile
        return None

    def _select_adapter(
        self,
        path: Path,
        profile: InstrumentProfile | None,
    ) -> InstrumentAdapter | None:
        if profile:
            for adapter in self.adapters:
                if adapter.plugin_name == profile.parser_plugin and adapter.supports(path, profile):
                    return adapter
        for adapter in self.adapters:
            if adapter.supports(path, profile):
                return adapter
        return None

    @staticmethod
    def _asset_for(path: Path) -> DataAsset:
        return DataAsset(source_path=str(path), source_type=SourceType.INSTRUMENT_FILE)

    @staticmethod
    def _load_profiles(path: Path) -> list[InstrumentProfile]:
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [InstrumentProfile.model_validate(item) for item in data.get("instruments", [])]
