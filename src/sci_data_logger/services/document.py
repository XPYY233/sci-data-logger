from __future__ import annotations

from pathlib import Path
from typing import Any

from sci_data_logger.prompts import PAGE_ANALYSIS_PROMPT
from sci_data_logger.schemas import (
    EvidenceRef,
    FieldValue,
    MaterialInput,
    PagePacket,
    ProtocolStep,
    SourceType,
)
from sci_data_logger.vlm import QwenVLMClient


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
TEXT_SUFFIXES = {".txt", ".md"}


class DocumentProcessor:
    """Convert notebook pages into page-level packets."""

    def __init__(
        self,
        vlm_client: QwenVLMClient | None = None,
        term_aliaser: "TermAliaser | None" = None,
    ) -> None:
        from sci_data_logger.services.term_aliaser import TermAliaser
        self.vlm_client = vlm_client or QwenVLMClient()
        self.term_aliaser = term_aliaser or TermAliaser()

    def analyze_page(self, source_path: Path) -> PagePacket:
        suffix = source_path.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            return self._analyze_image(source_path)
        if suffix in TEXT_SUFFIXES:
            return self._analyze_text(source_path)
        return PagePacket(
            source_path=str(source_path),
            open_questions=[f"暂不支持该页面文件类型：{suffix or 'unknown'}"],
        )

    def _analyze_image(self, image_path: Path) -> PagePacket:
        model_result = self.vlm_client.analyze_image(image_path, PAGE_ANALYSIS_PROMPT)
        payload = model_result.get("json")
        if not isinstance(payload, dict):
            payload = {
                "_parse_error": "invalid_payload",
                "warnings": ["VLM 返回的结构化结果不是 JSON 对象。"],
                "open_questions": ["请人工检查 VLM 原始输出并补录结构化字段。"],
                "review_required": True,
            }

        warnings = self._strings_from_payload(payload.get("warnings", []))
        open_questions = self._strings_from_payload(payload.get("open_questions", []))
        review_required = bool(payload.get("review_required"))

        if payload.get("_parse_error"):
            warnings.append("VLM 输出未能解析为预期 JSON 结构。")
            if not open_questions:
                open_questions.append("请人工检查 VLM 原始输出并补录结构化字段。")
            review_required = True

        text_blocks = self._strings_from_payload(payload.get("text_blocks", []))
        raw_text = payload.get("raw_text")
        if payload.get("_parse_error") and raw_text and not text_blocks:
            text_blocks.append(str(raw_text))

        materials = self._materials_from_payload(payload.get("materials", []), image_path)
        steps = self._steps_from_payload(payload.get("steps", []), image_path)
        observations = self._observations_from_payload(payload.get("observations", []), image_path)
        instruments = self._strings_from_payload(payload.get("instruments", []))
        table_blocks = self._normalize_table_blocks(payload.get("table_blocks", []))
        extracted_facts = self._facts_from_payload(payload.get("extracted_facts", {}), image_path)

        page_types_raw = payload.get("page_type") or payload.get("page_types") or ["unknown"]
        page_types = page_types_raw if isinstance(page_types_raw, list) else [str(page_types_raw)]
        page_types = [str(pt) for pt in page_types] or ["unknown"]

        if open_questions:
            review_required = True
        if any(
            (fv.confidence is not None and fv.confidence < 0.6)
            for fv in [
                *extracted_facts.values(),
                *observations,
                *(m.amount for m in materials if m.amount is not None),
                *(p for s in steps for p in s.parameters.values()),
            ]
        ):
            review_required = True

        page = PagePacket(
            source_path=str(image_path),
            page_types=page_types,
            sample_id=payload.get("sample_id"),
            text_blocks=text_blocks,
            table_blocks=table_blocks,
            extracted_materials=materials,
            extracted_steps=steps,
            extracted_observations=observations,
            extracted_instruments=instruments,
            extracted_facts=extracted_facts,
            open_questions=self._dedupe(open_questions),
            warnings=self._dedupe(warnings),
            review_required=review_required,
            raw_model_output=model_result,
        )
        page.evidence_refs.append(
            EvidenceRef(
                source_type=SourceType.NOTEBOOK_IMAGE,
                source_id=page.page_id,
                locator={"path": str(image_path)},
                confidence=0.75,
            )
        )
        return page

    def _analyze_text(self, text_path: Path) -> PagePacket:
        text = text_path.read_text(encoding="utf-8", errors="ignore")
        return PagePacket(
            source_path=str(text_path),
            page_types=["text_note"],
            text_blocks=[text],
            evidence_refs=[
                EvidenceRef(
                    source_type=SourceType.OCR_TEXT,
                    source_id=str(text_path),
                    locator={"path": str(text_path)},
                    confidence=1.0,
                )
            ],
        )

    @staticmethod
    def _strings_from_payload(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        return [str(value)]

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        return list(dict.fromkeys(item for item in items if item))

    @staticmethod
    def _facts_from_payload(payload: Any, image_path: Path) -> dict[str, FieldValue]:
        if not isinstance(payload, dict):
            return {}
        facts: dict[str, FieldValue] = {}
        for key, item in payload.items():
            if isinstance(item, dict):
                facts[key] = FieldValue(
                    value=item.get("value"),
                    unit=item.get("unit"),
                    confidence=item.get("confidence"),
                    source_refs=[
                        EvidenceRef(
                            source_type=SourceType.NOTEBOOK_IMAGE,
                            source_id=str(image_path),
                            locator={"field": key},
                            confidence=item.get("confidence"),
                        )
                    ],
                )
            else:
                facts[key] = FieldValue(value=item)
        return facts

    @staticmethod
    def _materials_from_payload(items: Any, image_path: Path) -> list[MaterialInput]:
        if not isinstance(items, list):
            return []
        result: list[MaterialInput] = []
        for raw in items:
            if not isinstance(raw, dict) or not raw.get("name"):
                continue
            amount_raw = raw.get("amount")
            amount = None
            if isinstance(amount_raw, dict) and amount_raw.get("value") is not None:
                amount = FieldValue(
                    value=amount_raw.get("value"),
                    unit=amount_raw.get("unit"),
                    confidence=amount_raw.get("confidence"),
                    source_refs=[
                        EvidenceRef(
                            source_type=SourceType.NOTEBOOK_IMAGE,
                            source_id=str(image_path),
                            locator={"field": f"material:{raw['name']}:amount"},
                            confidence=amount_raw.get("confidence"),
                        )
                    ],
                )
            metadata = {"role_evidence": raw.get("notes")} if raw.get("notes") else {}
            result.append(
                MaterialInput(
                    name=str(raw["name"]),
                    role=raw.get("role"),
                    amount=amount,
                    metadata=metadata,
                )
            )
        return result

    def _steps_from_payload(self, items: Any, image_path: Path) -> list[ProtocolStep]:
        if not isinstance(items, list):
            return []
        result: list[ProtocolStep] = []
        for raw in items:
            if not isinstance(raw, dict) or not raw.get("description"):
                continue
            parameters: dict[str, FieldValue] = {}
            for k, v in (raw.get("parameters") or {}).items():
                if isinstance(v, dict):
                    parameters[k] = FieldValue(
                        value=v.get("value"),
                        unit=v.get("unit"),
                        confidence=v.get("confidence"),
                    )
            step_type_raw = raw.get("step_type") or raw.get("description", "")
            step_type_canonical = self.term_aliaser.canonical_step_type(step_type_raw)
            result.append(
                ProtocolStep(
                    step_type=step_type_canonical,
                    sequence_index=int(raw.get("sequence_index") or len(result) + 1),
                    description=str(raw["description"]),
                    inputs=[str(x) for x in (raw.get("inputs") or [])],
                    outputs=[str(x) for x in (raw.get("outputs") or [])],
                    parameters=parameters,
                    evidence_refs=[
                        EvidenceRef(
                            source_type=SourceType.NOTEBOOK_IMAGE,
                            source_id=str(image_path),
                            locator={"field": f"step:{len(result) + 1}"},
                            confidence=raw.get("confidence"),
                        )
                    ],
                    confidence=raw.get("confidence"),
                )
            )
        return result

    @staticmethod
    def _observations_from_payload(items: Any, image_path: Path) -> list[FieldValue]:
        if not isinstance(items, list):
            return []
        result: list[FieldValue] = []
        for raw in items:
            if isinstance(raw, dict):
                result.append(
                    FieldValue(
                        value=raw.get("value"),
                        unit=raw.get("unit"),
                        confidence=raw.get("confidence"),
                        source_refs=[
                            EvidenceRef(
                                source_type=SourceType.NOTEBOOK_IMAGE,
                                source_id=str(image_path),
                                locator={"field": "observation"},
                                confidence=raw.get("confidence"),
                            )
                        ],
                    )
                )
            else:
                result.append(FieldValue(value=str(raw)))
        return result

    @staticmethod
    def _normalize_table_blocks(items: Any) -> list[dict[str, Any]]:
        if not isinstance(items, list):
            return []
        result: list[dict[str, Any]] = []
        for tbl in items:
            if not isinstance(tbl, dict):
                continue
            rows = tbl.get("rows") or []
            normalized_rows: list[list[str]] = []
            if rows and isinstance(rows[0], dict):
                headers = list(rows[0].keys())
                normalized_rows.append([str(h) for h in headers])
                for row in rows:
                    if isinstance(row, dict):
                        normalized_rows.append([str(row.get(h, "")) for h in headers])
            else:
                for row in rows:
                    if isinstance(row, list):
                        normalized_rows.append([str(c) for c in row])
                    else:
                        normalized_rows.append([str(row)])
            result.append({"title": tbl.get("title"), "rows": normalized_rows})
        return result
