from __future__ import annotations

import re
from pathlib import Path

from sci_data_logger.adapters.base import AdapterResult
from sci_data_logger.schemas import InstrumentProfile


KEY_VALUE_RE = re.compile(r"^\s*([^:=：]{2,80})\s*[:=：]\s*(.+?)\s*$")


class GenericTextReportAdapter:
    plugin_name = "generic_text_report"

    def supports(self, path: Path, profile: InstrumentProfile | None = None) -> bool:
        return path.suffix.lower() in {".txt", ".md", ".log", ".report"}

    def parse(self, path: Path, profile: InstrumentProfile | None = None) -> AdapterResult:
        text = path.read_text(encoding="utf-8", errors="ignore")
        raw_parameters: dict[str, object] = {}
        for line in text.splitlines():
            match = KEY_VALUE_RE.match(line)
            if not match:
                continue
            key = match.group(1).strip()
            value = match.group(2).strip()
            raw_parameters[key] = value

        warnings = []
        if not raw_parameters:
            warnings.append("未从文本报告中识别到 key-value 参数。")
            raw_parameters["raw_text_preview"] = text[:1000]

        return AdapterResult(raw_parameters=raw_parameters, warnings=warnings)
