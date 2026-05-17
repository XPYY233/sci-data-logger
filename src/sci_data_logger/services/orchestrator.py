from __future__ import annotations

import unicodedata
from concurrent.futures import ThreadPoolExecutor

from sci_data_logger.config import get_settings
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
    Sample,
    SourceType,
)
from sci_data_logger.services.document import DocumentProcessor
from sci_data_logger.services.instrument import InstrumentService
from sci_data_logger.utils.date_heuristics import infer_default_year, label_to_iso


# Leading category prefixes commonly written before a label like "管式炉 707".
# Longest-first so "管式炉" wins over "管式" — otherwise stripping "管式" would
# leave a dangling "炉" that the suffix loop only peels off once.
_INSTRUMENT_LEADING_PREFIXES: tuple[str, ...] = (
    "X射线衍射仪",
    "X射线衍射",
    "扫描电镜",
    "管式炉",
    "箱式炉",
    "立式炉",
    "马弗炉",
    "球磨机",
    "管式",
    "箱式",
    "立式",
    "球磨",
    "拉曼",
)


def _norm_instrument_token(s: str | None) -> str:
    """NFKD-fold, lowercase, strip whitespace and common Chinese instrument suffixes (炉/箱/机)."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(s))
    folded = "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()
    # Strip a leading category prefix when followed by whitespace, e.g.
    # "管式炉 707" → "707". Prefixes are matched case-insensitively because
    # `folded` is already lowercased.
    for prefix in _INSTRUMENT_LEADING_PREFIXES:
        p = prefix.lower()
        if folded.startswith(p):
            rest = folded[len(p):]
            if rest[:1].isspace():
                folded = rest.lstrip()
                break
    # Strip trailing common suffixes once to make "707炉" match "707".
    for suffix in ("炉", "箱", "机", "仪"):
        if folded.endswith(suffix):
            folded = folded[:-1].strip()
            break
    return folded


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
        # Concurrent per-file fanout. Each file yields a list of PagePackets
        # (PDFs expand to multiple pages, single images to one). Flatten while
        # preserving file order and within-PDF page order.
        per_file_results = self._analyze_pages_concurrently(request.image_paths)
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
        samples_catalog = self._merge_samples_catalog(pages)
        events, extra_issues = self._resolve_and_merge_events(
            pages, materials_catalog, instruments_catalog, samples_catalog
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
            samples_catalog=samples_catalog,
            events=events,
            measurements=measurements,
            metadata={"user_fields": request.user_fields},
        )
        record.review_issues.extend(self._basic_review(record))
        record.review_issues.extend(extra_issues)
        if record.review_issues:
            record.status = ReviewStatus.NEEDS_REVIEW
        return record

    def _analyze_pages_concurrently(self, image_paths) -> list[list[PagePacket]]:
        """Dispatch VLM page analyses with bounded concurrency, preserving input order.

        Returns a list aligned with image_paths; each element is the list of
        PagePackets that file expanded into (>=1 for PDFs).

        When falling back to sequential execution (max_workers <= 1 or single
        file) AND ``context_hint_enabled`` is True, thread the previous page's
        text_blocks tail forward as a continuation hint for the VLM. Context
        hints are only applied sequentially; with concurrency we can't define
        a "previous page" deterministically.
        """
        from sci_data_logger.services.document import _tail_of_text_blocks

        image_paths = list(image_paths)
        if not image_paths:
            return []
        settings = get_settings()
        max_workers = max(1, int(settings.vlm_concurrency or 1))
        if settings.context_hint_enabled:
            # Context threading requires a deterministic previous page; concurrency
            # would destroy that ordering. Force sequential when the user opts into
            # context hints so the flag has the intended effect even under default
            # vlm_concurrency > 1.
            max_workers = 1

        def _analyze(path, prev_tail):
            fn = self.document_processor.analyze_pages
            try:
                return fn(path, prev_tail=prev_tail)
            except TypeError:
                return fn(path)

        if max_workers <= 1 or len(image_paths) <= 1:
            results: list[list[PagePacket]] = []
            prev_tail: str | None = None
            for p in image_paths:
                page_list = _analyze(p, prev_tail if settings.context_hint_enabled else None)
                results.append(page_list)
                if settings.context_hint_enabled and page_list:
                    prev_tail = _tail_of_text_blocks(
                        page_list[-1].text_blocks, settings.context_hint_tail_chars
                    )
            return results
        # Concurrent path: no defined predecessor, so don't thread context.
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            return list(ex.map(self.document_processor.analyze_pages, image_paths))

    @staticmethod
    def _merge_materials_catalog(pages: list[PagePacket]) -> list[Material]:
        """跨页合并 materials_catalog（来自 VLM 的 raw_model_output.json.materials_catalog）。

        去重 key：canonical_name (case-insensitive, stripped). Role 不参与 key —
        同一材料在不同页面以不同 role 出现时合并为同一 catalog 条目，roles 累积。
        aliases 合并；display_name 取第一次出现的。
        如果 VLM 未提供新 schema 的 materials_catalog，则回退到 page.extracted_materials。
        """
        seen: dict[str, Material] = {}
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
                roles_field = raw.get("roles")
                incoming_roles: list[str] = []
                if isinstance(roles_field, list):
                    incoming_roles = [str(r) for r in roles_field if r]
                elif role:
                    incoming_roles = [str(role)]
                key = canon.lower()
                existing = seen.get(key)
                new_aliases = [str(a) for a in (raw.get("aliases") or []) if a]
                if existing is None:
                    seen[key] = Material(
                        canonical_name=canon,
                        display_name=raw.get("display_name") or raw.get("name"),
                        aliases=new_aliases,
                        chemical_formula=raw.get("chemical_formula"),
                        roles=list(dict.fromkeys(incoming_roles)),
                    )
                else:
                    existing.aliases = list(dict.fromkeys([*existing.aliases, *new_aliases]))
                    existing.roles = list(dict.fromkeys([*existing.roles, *incoming_roles]))
        return list(seen.values())

    @staticmethod
    def _merge_instruments_catalog(pages: list[PagePacket]) -> list[Instrument]:
        """跨页合并 instruments_catalog，去重 key: (technique, normalized instrument_label)。

        normalized 形式做 NFKD + lower + 去尾缀（炉/箱/机/仪），让 "707炉" / "707" / "７０７" 视为同一台。
        合并时把不同写法收集到 aliases。
        """
        # Key part for the label: normalized string, or None when label itself is None
        # (preserve the distinction between "labelled" and "unlabelled" instruments).
        seen: dict[tuple[str, str | None], Instrument] = {}
        for page in pages:
            catalog_items = (
                (page.raw_model_output or {}).get("json", {}).get("instruments_catalog") or []
            )
            # Fallback: legacy prompt path may only emit the flat `instruments: [str]`
            # list (surfaced as page.extracted_instruments). Mirror the materials-side
            # fallback so the catalog isn't empty on those pages. We can't infer the
            # technique from a bare string, so default to "other".
            if not catalog_items and page.extracted_instruments:
                catalog_items = [
                    {"technique": "other", "instrument_label": s.strip(), "aliases": []}
                    for s in page.extracted_instruments
                    if s and s.strip()
                ]
            for raw in catalog_items:
                if not isinstance(raw, dict):
                    continue
                tech = (raw.get("technique") or "other").strip()
                label = raw.get("instrument_label")
                model = raw.get("model")
                norm_label = _norm_instrument_token(label) if label is not None else None
                key = (tech, norm_label)
                existing = seen.get(key)
                if existing is None:
                    raw_aliases = [str(a) for a in (raw.get("aliases") or []) if a]
                    seen[key] = Instrument(
                        technique=tech,
                        instrument_label=label,
                        location=raw.get("location"),
                        manufacturer=raw.get("manufacturer"),
                        model=model,
                        aliases=raw_aliases,
                    )
                else:
                    # Record alternative surface forms as aliases. We compare *raw strings*
                    # against the canonical label/model (since they normalize equal by
                    # construction of `key`, the only thing worth tracking is a different
                    # spelling). Explicit alias entries always pass through.
                    canon_label = existing.instrument_label
                    canon_model = existing.model
                    incoming: list[str] = []
                    if label and label != canon_label:
                        incoming.append(str(label))
                    if model and model != canon_model and model != canon_label:
                        incoming.append(str(model))
                    for a in raw.get("aliases") or []:
                        if a:
                            incoming.append(str(a))
                    if incoming:
                        existing.aliases = list(
                            dict.fromkeys([*existing.aliases, *incoming])
                        )
        # Substring-containment post-pass: a short label like "707" should fold
        # into a longer one like "管式炉 707" (which normalizes to "707" only if
        # the leading-prefix strip applies — but on other catalog entries the
        # prefix may not be in our list, so containment is the safety net).
        # Keep the longer label as canonical; the shorter form becomes an alias.
        items = list(seen.values())
        merged_ids: set[str] = set()
        # Precompute normalized forms once.
        normed = [
            (ins, _norm_instrument_token(ins.instrument_label) if ins.instrument_label else "")
            for ins in items
        ]
        for i, (a, a_norm) in enumerate(normed):
            if a.instrument_id in merged_ids or not a_norm or len(a_norm) < 2:
                continue
            for j, (b, b_norm) in enumerate(normed):
                if i == j or b.instrument_id in merged_ids or not b_norm:
                    continue
                if a.technique != b.technique:
                    continue
                if a_norm == b_norm:
                    continue  # exact match already handled by `seen` keying
                # a contained in b → fold a into b (b is the longer/canonical).
                if a_norm in b_norm and len(b_norm) > len(a_norm):
                    extras: list[str] = []
                    if a.instrument_label and a.instrument_label != b.instrument_label \
                            and a.instrument_label != b.model:
                        extras.append(str(a.instrument_label))
                    if a.model and a.model != b.model and a.model != b.instrument_label:
                        extras.append(str(a.model))
                    extras.extend(str(x) for x in a.aliases if x)
                    if extras:
                        b.aliases = list(dict.fromkeys([*b.aliases, *extras]))
                    merged_ids.add(a.instrument_id)
                    break
        return [ins for ins in items if ins.instrument_id not in merged_ids]

    @staticmethod
    def _norm_sample_label(label: str) -> str:
        """Normalize sample labels for dedup.

        Treats '#3' / '样品3' / 'S3' / 'sample 3' as equivalent: NFKD-strip combining
        marks, lowercase, strip whitespace, then peel off leading prefixes
        (`#`, `样品`, `sample`, `sample `, plus the bare letter `s` when followed
        by a digit). Looped because users mix e.g. '#样品3'.
        """
        import unicodedata

        s = unicodedata.normalize("NFKD", label or "")
        s = "".join(c for c in s if not unicodedata.combining(c)).lower().strip()
        changed = True
        while changed:
            changed = False
            for prefix in ("sample ", "sample", "样品", "#"):
                if s.startswith(prefix):
                    s = s[len(prefix):].strip()
                    changed = True
                    break
            # bare 's' followed by digit -> drop the 's'
            if len(s) >= 2 and s[0] == "s" and s[1].isdigit():
                s = s[1:]
                changed = True
        return s

    @classmethod
    def _merge_samples_catalog(cls, pages: list[PagePacket]) -> list[Sample]:
        """跨页合并 samples_catalog。

        Dedup key: 归一化 canonical_label（去掉 '#', '样品', 'sample ' 前缀，
        NFKD 后小写 strip）。aliases 合并；display_label 取第一次出现的。
        Source priority per page:
          1. raw_model_output.json.samples_catalog (structured)
          2. page.extracted_samples (raw strings)
          3. page.sample_id (legacy single field)
        """
        seen: dict[str, Sample] = {}

        def _ingest(canonical: str, *, display: str | None, aliases: list[str],
                    target_ref: str | None = None, batch: str | None = None) -> None:
            canonical = (canonical or "").strip()
            if not canonical:
                return
            key = cls._norm_sample_label(canonical)
            if not key:
                return
            existing = seen.get(key)
            clean_aliases = [str(a) for a in aliases if a]
            if existing is None:
                seen[key] = Sample(
                    canonical_label=canonical,
                    display_label=display or canonical,
                    aliases=clean_aliases,
                    target_material_ref=target_ref,
                    batch=batch,
                )
            else:
                combined = list(dict.fromkeys([*existing.aliases, *clean_aliases]))
                # Track the original spelling as alias if it differs from canonical.
                if canonical and canonical != existing.canonical_label and canonical not in combined:
                    combined.append(canonical)
                existing.aliases = combined
                if existing.target_material_ref is None and target_ref:
                    existing.target_material_ref = target_ref
                if existing.batch is None and batch:
                    existing.batch = batch

        for page in pages:
            catalog_items = (
                (page.raw_model_output or {}).get("json", {}).get("samples_catalog") or []
            )
            for raw in catalog_items:
                if not isinstance(raw, dict):
                    continue
                canon = raw.get("canonical_label") or raw.get("label") or raw.get("name")
                if not canon:
                    continue
                _ingest(
                    str(canon),
                    display=raw.get("display_label"),
                    aliases=list(raw.get("aliases") or []),
                    target_ref=raw.get("target_material_ref"),
                    batch=raw.get("batch"),
                )
            # Fallback: extracted_samples raw strings
            if not catalog_items:
                for s in page.extracted_samples or []:
                    _ingest(str(s), display=None, aliases=[])
                if page.sample_id:
                    _ingest(str(page.sample_id), display=None, aliases=[])
        return list(seen.values())

    def _resolve_and_merge_events(
        self,
        pages: list[PagePacket],
        materials_catalog: list[Material],
        instruments_catalog: list[Instrument],
        samples_catalog: list[Sample] | None = None,
    ) -> tuple[list[ExperimentEvent], list[ReviewIssue]]:
        """Resolve page.extracted_events local refs to catalog IDs, global sort.

        Returns (events, extra_review_issues). Catalogs may be mutated (auto-add).
        """
        issues: list[ReviewIssue] = []
        stub_ids: set[str] = set()
        stub_sample_ids: set[str] = set()
        if samples_catalog is None:
            samples_catalog = []

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
            stub_ids.add(new_mat.material_id)
            issues.append(ReviewIssue(
                severity="warning",
                title="Material reference auto-created",
                detail=f"Material reference '{ref}' unresolved in catalog; auto-created entry. 请人工核对。",
            ))
            return new_mat

        def find_sample(ref: str) -> Sample | None:
            if not ref:
                return None
            ref_norm = ref.strip()
            ref_lower = ref_norm.lower()
            for s in samples_catalog:
                if s.canonical_label.strip().lower() == ref_lower:
                    return s
                if any(a.strip().lower() == ref_lower for a in s.aliases):
                    return s
            # normalized form (strip prefixes)
            norm = self._norm_sample_label(ref_norm)
            for s in samples_catalog:
                if self._norm_sample_label(s.canonical_label) == norm:
                    return s
                if any(self._norm_sample_label(a) == norm for a in s.aliases):
                    return s
            return None

        def find_or_create_sample(ref: str) -> Sample:
            s = find_sample(ref)
            if s is not None:
                return s
            new_s = Sample(canonical_label=ref.strip())
            samples_catalog.append(new_s)
            stub_sample_ids.add(new_s.sample_id)
            issues.append(ReviewIssue(
                severity="warning",
                title="Sample reference auto-created",
                detail=f"Sample reference '{ref}' unresolved in catalog; auto-created entry. 请人工核对。",
            ))
            return new_s

        def find_instrument(ref: str | None) -> Instrument | None:
            if not ref:
                return None
            ref_lower = ref.strip().lower()
            # 1. exact lowercase against "technique@label" / label / model / technique
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
            # 2. fuzzy: NFKD-fold + suffix-strip on both sides; also check aliases.
            ref_norm = _norm_instrument_token(ref)
            if ref_norm:
                for ins in instruments_catalog:
                    candidates = [ins.instrument_label, ins.model, *ins.aliases]
                    for cand in candidates:
                        if cand and _norm_instrument_token(cand) == ref_norm:
                            return ins
            return None

        # Fallback: pages without extracted_events but with extracted_steps (legacy) -> upgrade.
        # IMPORTANT: copy step.inputs / step.outputs into EventIO / EventOutput so
        # _link_event_chains can later trace material flow. Also pull page-level
        # signals (recipe_ratios, equations, sample_id) onto the first event of
        # the page so they're not lost in the legacy path.
        for page in pages:
            if page.extracted_events or not page.extracted_steps:
                continue
            sorted_steps = sorted(page.extracted_steps, key=lambda s: s.sequence_index)
            # Page-level signals attach to the first event only, to avoid duplication.
            first_recipe_ratio: dict | None = (
                page.extracted_recipe_ratios[0]
                if page.extracted_recipe_ratios and isinstance(page.extracted_recipe_ratios[0], dict)
                else None
            )
            first_equation: str | None = (
                page.extracted_equations[0] if page.extracted_equations else None
            )
            first_date_label: str | None = (
                page.extracted_dates[0] if page.extracted_dates else None
            )
            first_sample_ref: str | None = (
                page.sample_id if page.sample_id else None
            )
            first_instrument_ref: str | None = (
                page.extracted_instruments[0] if page.extracted_instruments else None
            )
            for idx, step in enumerate(sorted_steps):
                is_first = idx == 0
                inputs = [EventIO(material_ref=str(ref)) for ref in step.inputs if ref]
                outputs = [EventOutput(material_ref=str(ref)) for ref in step.outputs if ref]
                page.extracted_events.append(ExperimentEvent(
                    sequence_index=step.sequence_index,
                    action_type=step.step_type,
                    description=step.description,
                    inputs=inputs,
                    outputs=outputs,
                    parameters=step.parameters,
                    page_ref=page.page_id,
                    evidence_refs=step.evidence_refs,
                    confidence=step.confidence,
                    observations=list(page.extracted_observations) if is_first else [],
                    recipe_ratio=first_recipe_ratio if is_first else None,
                    equation=first_equation if is_first else None,
                    date_label=first_date_label if is_first else None,
                    sample_ref=first_sample_ref if is_first else None,
                    instrument_ref=first_instrument_ref if is_first else None,
                ))

        # Infer a default year from any full YMD label across all pages/events.
        # If none exists we leave M/D-only events with date_iso=None rather than
        # silently substituting datetime.now().year — see label_to_iso docstring.
        date_label_pool: list[str | None] = []
        for page in pages:
            for evt in page.extracted_events:
                date_label_pool.append(evt.date_label)
                if evt.date_iso:
                    date_label_pool.append(evt.date_iso)
            date_label_pool.extend(page.extracted_dates)
        inferred_year = infer_default_year(date_label_pool)

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
                sample_id_resolved = evt.sample_ref
                if sample_id_resolved:
                    smp = find_or_create_sample(sample_id_resolved)
                    sample_id_resolved = smp.sample_id
                new_date_iso = evt.date_iso or label_to_iso(
                    evt.date_label, default_year=inferred_year
                )
                new_evt = evt.model_copy(update={
                    "inputs": new_inputs,
                    "outputs": new_outputs,
                    "instrument_ref": instr_id,
                    "sample_ref": sample_id_resolved,
                    "date_iso": new_date_iso,
                })
                all_events.append((page_idx, new_evt))

        # Fold stub samples (auto-created when no catalog match) into any
        # real entry sharing the same normalized label.
        self._reconcile_stub_samples(samples_catalog, all_events, stub_sample_ids)

        # Global sort: date_iso > page_number_hint > captured_at > (page_idx, sequence_index)
        def sort_key(item):
            page_idx, e = item
            page = pages[page_idx]
            iso = e.date_iso or ""
            # Priority: (has_date_iso, date_iso) > (has_page_number_hint, hint)
            #          > (has_captured_at, captured_at) > (page_idx, sequence_index)
            return (
                iso == "",                                                   # False (has iso) sorts first
                iso,
                page.page_number_hint is None,                               # False (has hint) sorts first
                page.page_number_hint if page.page_number_hint is not None else 0,
                not page.captured_at,                                        # False (has captured_at) sorts first
                page.captured_at or "",
                page_idx,
                e.sequence_index,
            )

        all_events.sort(key=sort_key)
        final: list[ExperimentEvent] = []
        for new_idx, (_, e) in enumerate(all_events, start=1):
            final.append(e.model_copy(update={"sequence_index": new_idx}))

        # Reconcile pass: a stub created from a raw ref may collide with a real
        # catalog entry by canonical_name (case-insensitive NFKD) or by being
        # listed as one of its aliases. Merge stub -> real and rewrite refs.
        final = self._reconcile_stub_materials(
            final, materials_catalog, stub_ids, _norm
        )

        # Link event causal chains (derived_from / produces_for) based on
        # material flow between events.
        final = self._link_event_chains(final)
        return final, issues

    @classmethod
    def _reconcile_stub_samples(
        cls,
        samples_catalog: list[Sample],
        all_events: list[tuple[int, ExperimentEvent]],
        stub_sample_ids: set[str] | None = None,
    ) -> None:
        """Collapse auto-created stub Samples into pre-existing entries
        sharing the same normalized label. Rewrites event.sample_ref in place
        on the (page_idx, event) tuples.

        When ``stub_sample_ids`` is supplied, prefer a *non-stub* entry as the
        survivor for each label group. Otherwise (legacy path) the first entry
        wins, which relies on insertion order placing real entries first.
        """
        stub_sample_ids = stub_sample_ids or set()
        by_norm: dict[str, list[Sample]] = {}
        for s in samples_catalog:
            key = cls._norm_sample_label(s.canonical_label)
            by_norm.setdefault(key, []).append(s)

        rewrite: dict[str, str] = {}
        survivors: list[Sample] = []
        for _, group in by_norm.items():
            if not group:
                continue
            # Prefer the first non-stub entry as keeper; fall back to group[0].
            keeper = next(
                (s for s in group if s.sample_id not in stub_sample_ids),
                group[0],
            )
            survivors.append(keeper)
            for dup in group:
                if dup is keeper:
                    continue
                rewrite[dup.sample_id] = keeper.sample_id
                if dup.canonical_label and dup.canonical_label not in keeper.aliases \
                        and dup.canonical_label != keeper.canonical_label:
                    keeper.aliases.append(dup.canonical_label)
                for a in dup.aliases:
                    if a and a not in keeper.aliases:
                        keeper.aliases.append(a)

        if rewrite:
            samples_catalog[:] = survivors
            for i, (page_idx, evt) in enumerate(all_events):
                if evt.sample_ref in rewrite:
                    all_events[i] = (
                        page_idx,
                        evt.model_copy(update={"sample_ref": rewrite[evt.sample_ref]}),
                    )

    @staticmethod
    def _reconcile_stub_materials(
        events: list[ExperimentEvent],
        materials_catalog: list[Material],
        stub_ids: set[str],
        norm,
    ) -> list[ExperimentEvent]:
        if not stub_ids:
            return events
        # Build id -> real-id remap by scanning stubs against non-stub entries.
        id_remap: dict[str, str] = {}
        stubs = [m for m in materials_catalog if m.material_id in stub_ids]
        reals = [m for m in materials_catalog if m.material_id not in stub_ids]
        for stub in stubs:
            stub_canon_norm = norm(stub.canonical_name)
            target: Material | None = None
            for real in reals:
                if norm(real.canonical_name) == stub_canon_norm:
                    target = real
                    break
                if any(norm(a) == stub_canon_norm for a in real.aliases):
                    target = real
                    break
            if target is None:
                continue
            id_remap[stub.material_id] = target.material_id
            # Preserve the stub's name as an alias on the real entry if not
            # already present (canonical or alias).
            if norm(stub.canonical_name) != norm(target.canonical_name) and not any(
                norm(a) == stub_canon_norm for a in target.aliases
            ):
                target.aliases = [*target.aliases, stub.canonical_name]
        if not id_remap:
            return events
        # Remove merged stubs from catalog.
        merged_ids = set(id_remap.keys())
        materials_catalog[:] = [
            m for m in materials_catalog if m.material_id not in merged_ids
        ]
        # Rewrite event io refs.
        rewritten: list[ExperimentEvent] = []
        for e in events:
            new_inputs = [
                EventIO(
                    material_ref=id_remap.get(io.material_ref, io.material_ref),
                    amount=io.amount,
                    notes=io.notes,
                )
                for io in e.inputs
            ]
            new_outputs = [
                EventOutput(
                    material_ref=id_remap.get(io.material_ref, io.material_ref),
                    amount=io.amount,
                    notes=io.notes,
                    target_phase=io.target_phase,
                    failure_marker=io.failure_marker,
                )
                for io in e.outputs
            ]
            rewritten.append(e.model_copy(update={
                "inputs": new_inputs,
                "outputs": new_outputs,
            }))
        return rewritten

    @staticmethod
    def _link_event_chains(events: list[ExperimentEvent]) -> list[ExperimentEvent]:
        """Populate explicit causal chain edges (`derived_from` / `produces_for`).

        For each event E, look at its `inputs`. Any earlier event (by
        sequence_index) that lists the same material in its `outputs` is a
        producer — E.derived_from collects those producer event_ids, and the
        producer's `produces_for` reverse-index collects E.event_id.

        Acyclicity is guaranteed by the `prod_seq < e.sequence_index` filter:
        an event can only depend on strictly earlier events.
        """
        producers: dict[str, list[tuple[int, str]]] = {}
        for e in events:
            for o in e.outputs:
                producers.setdefault(o.material_ref, []).append(
                    (e.sequence_index, e.event_id)
                )

        derived: dict[str, list[str]] = {}
        produces_for_map: dict[str, list[str]] = {}
        for e in events:
            for io in e.inputs:
                for prod_seq, prod_eid in producers.get(io.material_ref, []):
                    if prod_seq < e.sequence_index:
                        derived.setdefault(e.event_id, []).append(prod_eid)
                        produces_for_map.setdefault(prod_eid, []).append(e.event_id)

        return [
            e.model_copy(
                update={
                    "derived_from": list(
                        dict.fromkeys(derived.get(e.event_id, []))
                    ),
                    "produces_for": list(
                        dict.fromkeys(produces_for_map.get(e.event_id, []))
                    ),
                }
            )
            for e in events
        ]

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
