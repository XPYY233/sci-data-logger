from __future__ import annotations

from sci_data_logger.schemas import (
    DataAsset,
    DraftExperimentRequest,
    ExperimentEvent,
    ExperimentRecord,
    Material,
    PagePacket,
    ReviewIssue,
    ReviewStatus,
    SourceType,
)
from sci_data_logger.services.document import DocumentProcessor
from sci_data_logger.services.instrument import InstrumentService


class ExperimentOrchestrator:
    """Build an experiment draft from user input, notebook pages, and instrument files."""

    def __init__(
        self,
        document_processor: DocumentProcessor | None = None,
        instrument_service: InstrumentService | None = None,
    ) -> None:
        self.document_processor = document_processor or DocumentProcessor()
        self.instrument_service = instrument_service or InstrumentService()

    def create_draft(self, request: DraftExperimentRequest) -> ExperimentRecord:
        pages = [self.document_processor.analyze_page(path) for path in request.image_paths]
        measurements = [
            self.instrument_service.parse_file(path) for path in request.instrument_file_paths
        ]
        source_assets = [
            DataAsset(source_path=str(path), source_type=SourceType.NOTEBOOK_IMAGE)
            for path in request.image_paths
        ]
        source_assets.extend(asset for packet in measurements for asset in packet.assets)

        # Phase 0 桥接：把每页的 extracted_materials/extracted_steps 升格到 catalog/events。
        # 真正的 catalog 去重 + ref 解析在后续 Task 8-13 实现；此处先用 legacy 桥接保住兼容。
        materials_catalog = self._merge_materials_catalog(pages)
        events = self._legacy_steps_to_events(pages)

        record = ExperimentRecord(
            experiment_id=request.experiment_id,
            project_id=request.project_id,
            group_id=request.group_id,
            operator=request.operator,
            title=request.title,
            source_assets=source_assets,
            pages=pages,
            materials_catalog=materials_catalog,
            instruments_catalog=[],   # Task 12 will fill
            events=events,
            measurements=measurements,
            metadata={"user_fields": request.user_fields},
        )
        record.review_issues.extend(self._basic_review(record))
        if record.review_issues:
            record.status = ReviewStatus.NEEDS_REVIEW
        return record

    @staticmethod
    def _merge_materials_catalog(pages: list[PagePacket]) -> list[Material]:
        """跨页合并 materials_catalog（来自 VLM 的 raw_model_output.json.materials_catalog）。

        去重 key：(canonical_name 大小写不敏感 strip 后, role)。
        aliases 合并；display_name 取第一次出现的。
        如果 VLM 未提供新 schema 的 materials_catalog，则回退到 page.extracted_materials。
        """
        seen: dict[tuple[str, str | None], Material] = {}
        for page in pages:
            catalog_items = (
                (page.raw_model_output or {}).get("json", {}).get("materials_catalog") or []
            )
            # Fallback: if VLM didn't provide new schema materials_catalog, use legacy extracted_materials
            if not catalog_items and page.extracted_materials:
                catalog_items = [
                    {
                        "canonical_name": m.name.strip(),
                        "role": m.role,
                        "aliases": [],
                    }
                    for m in page.extracted_materials
                ]
            for raw in catalog_items:
                if not isinstance(raw, dict):
                    continue
                canon = (raw.get("canonical_name") or raw.get("name") or "").strip()
                if not canon:
                    continue
                role = raw.get("role")
                key = (canon.lower(), role)
                existing = seen.get(key)
                new_aliases = [str(a) for a in (raw.get("aliases") or []) if a]
                if existing is None:
                    seen[key] = Material(
                        canonical_name=canon,
                        display_name=raw.get("display_name") or raw.get("name"),
                        aliases=new_aliases,
                        chemical_formula=raw.get("chemical_formula"),
                        role=role,
                    )
                else:
                    combined = list(dict.fromkeys([*existing.aliases, *new_aliases]))
                    existing.aliases = combined
        return list(seen.values())

    @staticmethod
    def _legacy_steps_to_events(pages: list[PagePacket]) -> list[ExperimentEvent]:
        """Phase 0 bridge: PagePacket.extracted_steps -> ExperimentEvent (no I/O resolution yet)."""
        merged: list[ExperimentEvent] = []
        for page in pages:
            for step in sorted(page.extracted_steps, key=lambda s: s.sequence_index):
                merged.append(ExperimentEvent(
                    sequence_index=len(merged) + 1,
                    action_type=step.step_type,
                    description=step.description,
                    parameters=step.parameters,
                    page_ref=page.page_id,
                    evidence_refs=step.evidence_refs,
                    confidence=step.confidence,
                    inputs=[],   # ref resolution in Task 13
                    outputs=[],
                    observations=[
                        obs for obs in page.extracted_observations
                    ] if step.sequence_index == 1 else [],
                ))
        return merged

    @staticmethod
    def _basic_review(record: ExperimentRecord) -> list[ReviewIssue]:
        issues: list[ReviewIssue] = []
        if not record.pages and not record.measurements:
            issues.append(
                ReviewIssue(
                    severity="warning",
                    title="缺少原始输入",
                    detail="当前实验草稿没有实验记录页面或仪器文件。",
                )
            )
        for page in record.pages:
            triggers: list[str] = []
            if page.review_required:
                triggers.append("页面自报需要复核")
            if page.warnings:
                triggers.extend(page.warnings)
            if page.open_questions:
                triggers.append(f"未解决问题 {len(page.open_questions)} 条")
            low_conf_count = sum(
                1
                for m in page.extracted_materials
                if m.amount and m.amount.confidence is not None and m.amount.confidence < 0.6
            ) + sum(
                1
                for s in page.extracted_steps
                for fv in s.parameters.values()
                if fv.confidence is not None and fv.confidence < 0.6
            )
            if low_conf_count > 0:
                triggers.append(f"低置信度字段 {low_conf_count} 个")
            if triggers:
                issues.append(
                    ReviewIssue(
                        severity="warning",
                        title="页面解析需要人工复核",
                        detail=f"文件 {page.source_path}：" + "；".join(triggers),
                        evidence_refs=page.evidence_refs,
                    )
                )
        for measurement in record.measurements:
            if not measurement.instrument_id:
                issues.append(
                    ReviewIssue(
                        severity="warning",
                        title="仪器未匹配",
                        detail=f"文件 {measurement.source_path} 未匹配到仪器注册表。",
                    )
                )
            if not measurement.normalized_parameters and measurement.raw_parameters:
                issues.append(
                    ReviewIssue(
                        severity="info",
                        title="参数尚未归一化",
                        detail=f"文件 {measurement.source_path} 已提取原始字段，但缺少字段映射。",
                    )
                )
        return issues
