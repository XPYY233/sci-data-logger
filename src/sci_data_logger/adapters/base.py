from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from sci_data_logger.schemas import InstrumentProfile


@dataclass
class AdapterResult:
    raw_parameters: dict[str, object] = field(default_factory=dict)
    normalized_parameters: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class InstrumentAdapter(Protocol):
    plugin_name: str

    def supports(self, path: Path, profile: InstrumentProfile | None = None) -> bool:
        ...

    def parse(self, path: Path, profile: InstrumentProfile | None = None) -> AdapterResult:
        ...
