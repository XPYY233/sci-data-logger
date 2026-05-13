from __future__ import annotations

import csv
from pathlib import Path

from sci_data_logger.adapters.base import AdapterResult
from sci_data_logger.schemas import InstrumentProfile


class GenericCSVAdapter:
    plugin_name = "generic_csv"

    def supports(self, path: Path, profile: InstrumentProfile | None = None) -> bool:
        return path.suffix.lower() in {".csv", ".tsv"}

    def parse(self, path: Path, profile: InstrumentProfile | None = None) -> AdapterResult:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        warnings: list[str] = []
        raw_parameters: dict[str, object] = {}

        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            rows = [row for row in reader if row]

        if not rows:
            return AdapterResult(warnings=["CSV 文件为空。"])

        if self._looks_like_two_column_numeric_data(rows):
            header_offset = 0 if self._is_numeric_pair(rows[0]) else 1
            columns = rows[0][:2] if header_offset else ["column_1", "column_2"]
            data_rows = rows[header_offset:]
            raw_parameters["columns"] = [column.strip() for column in columns]
            raw_parameters["row_count"] = len(data_rows)
            raw_parameters["data_preview"] = [row[:2] for row in data_rows[:5]]
            warnings.append(
                "CSV 看起来是两列数值型曲线/谱图数据，已记录列名、行数和预览，未作为 key-value 元数据解析。"
            )
        elif all(len(row) == 2 for row in rows):
            for row in rows:
                key = row[0].strip()
                value = row[1].strip()
                if key:
                    raw_parameters[key] = value
        else:
            header = rows[0]
            raw_parameters["columns"] = header
            raw_parameters["row_count"] = max(len(rows) - 1, 0)
            raw_parameters["data_preview"] = rows[1:6]
            warnings.append("CSV 看起来是数据表，已记录列名和行数，未做曲线级深度解析。")

        return AdapterResult(raw_parameters=raw_parameters, warnings=warnings)

    @classmethod
    def _looks_like_two_column_numeric_data(cls, rows: list[list[str]]) -> bool:
        if not rows or not all(len(row) == 2 for row in rows):
            return False
        data_rows = rows if cls._is_numeric_pair(rows[0]) else rows[1:]
        if len(data_rows) < 3:
            return False
        numeric_rows = [row for row in data_rows if cls._is_numeric_pair(row)]
        return len(numeric_rows) / len(data_rows) >= 0.8

    @classmethod
    def _is_numeric_pair(cls, row: list[str]) -> bool:
        return len(row) >= 2 and cls._is_number(row[0]) and cls._is_number(row[1])

    @staticmethod
    def _is_number(value: str) -> bool:
        try:
            float(value.strip())
        except ValueError:
            return False
        return True
