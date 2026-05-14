from __future__ import annotations

from sci_data_logger.schemas import (
    DataAsset,
    DraftExperimentRequest,
    EventIO,
    EventOutput,
    ExperimentEvent,
    ExperimentRecord,
    Instrument,
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
        # Multi-page expansion: each input file may yield multiple PagePackets (PDFs).
        # Ordering is preserved: file 0's pages come before file 1's, and within each
        # PDF page 1 precedes page 2, etc.
        per_file_results = [
            self.document_processor.analyze_pages(path) for path in request.image_paths
        ]
        pages = [pkt for sublist in per_file_results for pkt in sublist]
        measurements = [
            self.instrument_service.parse_file(path) for path in request.instrument_file_paths
        ]
        source_assets = [
            DataAsset(source_path=str(path), source_type=SourceType.NOTEBOOK_IMAGE)
            for path in request.image_paths
        ]
        source_assets.extend(asset for packet in measurements for asset in packet.assets)

        materials_catalog = self._merge_materials_catalog(pages)
        instruments_catalog = self._merge_instruments_catalog(pages)
        events, extra_issues = self._resolve_and_merge_events(
            pages, materials_catalog, instruments_catalog
        )

        record = ExperimentRecord(
            experiment_id=request.experiment_id,
            project_id=request.project_id,
            group_id=request.group_id,
            operator=request.operator,
            title=request.title,
            source_assets=source_assets,
            pages=pages,
            materials_catalog=materials_catalog,
            instruments_catalog=instruments_catalog,
            events=events,
            measurements=measurements,
            metadata={"user_fields": request.user_fields},
        )
        record.review_issues.extend(self._basic_review(record))
        record.review_issues.extend(extra_issues)
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
    def _merge_instruments_catalog(pages: list[PagePacket]) -> list[Instrument]:
        """跨页合并 instruments_catalog，去重 key: (technique, instrument_label)。"""
        seen: dict[tuple[str, str | None], Instrument] = {}
        for page in pages:
            catalog_items = (
                (page.raw_model_output or {}).get("json", {}).get("instruments_catalog") or []
            )
            for raw in catalog_items:
                if not isinstance(raw, dict):
                    continue
                tech = (raw.get("technique") or "other").strip()
                label = raw.get("instrument_label")
                key = (tech, label)
                if key not in seen:
                    seen[key] = Instrument(
                        technique=tech,
                        instrument_label=label,
                        location=raw.get("location"),
                        manufacturer=raw.get("manufacturer"),
                        model=raw.get("model"),
                    )
        return list(seen.values())

    def _resolve_and_merge_events(
        self,
        pages: list[PagePacket],
        materials_catalog: list[Material],
        instruments_catalog: list[Instrument],
    ) -> tuple[list[ExperimentEvent], list[ReviewIssue]]:
        """Resolve page.extracted_events local refs to catalog IDs, global sort.

        Returns (events, extra_review_issues). Catalogs may be mutated (auto-add).
        """
        import unicodedata
        from sci_data_logger.utils.date_heuristics import label_to_iso

        issues: list[ReviewIssue] = []

        def _norm(s: str) -> str:
            nfkd = unicodedata.normalize("NFKD", s)
            return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()

        def find_material(ref: str) -> Material | None:
            if not ref:
                return None
            ref_norm = ref.strip()
            ref_lower = ref_norm.lower()
            # 1. canonical_name exact
            for m in materials_catalog:
                if m.canonical_name.strip().lower() == ref_lower:
                    return m
            # 2. aliases exact
            for m in materials_catalog:
                if any(a.strip().lower() == ref_lower for a in m.aliases):
                    return m
            # 3. unicode NFKD strip
            ref_strip = _norm(ref_norm)
            for m in materials_catalog:
                if _norm(m.canonical_name) == ref_strip:
                    return m
                if any(_norm(a) == ref_strip for a in m.aliases):
                    return m
            return None

        def find_or_create_material(ref: str) -> Material:
            m = find_material(ref)
            if m is not None:
                return m
            new_mat = Material(canonical_name=ref.strip())
            materials_catalog.append(new_mat)
            issues.append(ReviewIssue(
                severity="warning",
                title="Material reference auto-created",
                detail=f"Material reference '{ref}' unresolved in catalog; auto-created entry. 请人工核对。",
            ))
            return new_mat

        def find_instrument(ref: str | None) -> Instrument | None:
            if not ref:
                return None
            ref_lower = ref.strip().lower()
            for ins in instruments_catalog:
                tokens = [
                    f"{ins.technique}@{ins.instrument_label}" if ins.instrument_label else None,
                    ins.instrument_label,
                    ins.model,
                    ins.technique,
                ]
                for tok in tokens:
                    if tok and tok.strip().lower() == ref_lower:
                        return ins
            return None

        # Fallback: pages without extracted_events but with extracted_steps (legacy) -> upgrade
        for page in pages:
            if not page.extracted_events and page.extracted_steps:
                for step in sorted(page.extracted_steps, key=lambda s: s.sequence_index):
                    page.extracted_events.append(ExperimentEvent(
                        sequence_index=step.sequence_index,
                        action_type=step.step_type,
                        description=step.description,
                        parameters=step.parameters,
                        page_ref=page.page_id,
                        evidence_refs=step.evidence_refs,
                        confidence=step.confidence,
                        observations=list(page.extracted_observations)
                        if step.sequence_index == 1
                        else [],
                    ))

        # Collect, resolve refs
        all_events: list[tuple[int, ExperimentEvent]] = []
        for page_idx, page in enumerate(pages):
            for evt in page.extracted_events:
                new_inputs = []
                for io in evt.inputs:
                    mat = find_or_create_material(io.material_ref)
                    new_inputs.append(EventIO(
                        material_ref=mat.material_id,
                        amount=io.amount,
                        notes=io.notes,
                    ))
                new_outputs = []
                for io in evt.outputs:
                    mat = find_or_create_material(io.material_ref)
                    new_outputs.append(EventOutput(
                        material_ref=mat.material_id,
                        amount=io.amount,
                        notes=io.notes,
                        target_phase=io.target_phase,
                        failure_marker=io.failure_marker,
                    ))
                instr_id = evt.instrument_ref
                if instr_id:
                    ins = find_instrument(instr_id)
                    instr_id = ins.instrument_id if ins else None
                new_date_iso = evt.date_iso or label_to_iso(evt.date_label)
                new_evt = evt.model_copy(update={
                    "inputs": new_inputs,
                    "outputs": new_outputs,
                    "instrument_ref": instr_id,
                    "date_iso": new_date_iso,
                })
                all_events.append((page_idx, new_evt))

        # Global sort: date_iso priority; missing -> (page_idx, sequence_index)
        def sort_key(item):
            page_idx, e = item
            iso = e.date_iso or ""
            return (iso == "", iso, page_idx, e.sequence_index)

        all_events.sort(key=sort_key)
        final: list[ExperimentEvent] = []
        for new_idx, (_, e) in enumerate(all_events, start=1):
            final.append(e.model_copy(update={"sequence_index": new_idx}))
        return final, issues

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
