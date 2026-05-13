from __future__ import annotations

from sci_data_logger.schemas import (
    DataAsset,
    DraftExperimentRequest,
    ExperimentRecord,
    MaterialInput,
    PagePacket,
    ProtocolStep,
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

        materials = self._merge_materials(pages)
        steps = self._merge_steps(pages)
        observations = [obs for page in pages for obs in page.extracted_observations]

        record = ExperimentRecord(
            experiment_id=request.experiment_id,
            project_id=request.project_id,
            group_id=request.group_id,
            operator=request.operator,
            title=request.title,
            source_assets=source_assets,
            pages=pages,
            materials=materials,
            steps=steps,
            observations=observations,
            measurements=measurements,
            metadata={"user_fields": request.user_fields},
        )
        record.review_issues.extend(self._basic_review(record))
        if record.review_issues:
            record.status = ReviewStatus.NEEDS_REVIEW
        return record

    @staticmethod
    def _merge_materials(pages: list[PagePacket]) -> list[MaterialInput]:
        seen: dict[tuple[str, str | None], MaterialInput] = {}
        for page in pages:
            for mat in page.extracted_materials:
                key = (mat.name.strip(), mat.role)
                if key not in seen:
                    seen[key] = mat
        return list(seen.values())

    @staticmethod
    def _merge_steps(pages: list[PagePacket]) -> list[ProtocolStep]:
        merged: list[ProtocolStep] = []
        for page in pages:
            for step in sorted(page.extracted_steps, key=lambda s: s.sequence_index):
                merged.append(step.model_copy(update={"sequence_index": len(merged) + 1}))
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
