# Event-Centric Schema · Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 sci_data_logger 中落地事件中心 schema（Materials catalog + Instruments catalog + Events）和兼容 property，让现有 21 个 pytest 全部保持绿色，为 Phase 1 prompt 改造铺路。

**Architecture:** 新增 5 个 pydantic 模型与一个 date 推断工具，PagePacket 增加 8 个空默认的新字段，ExperimentRecord 顶层增加 3 张主表 + 用 @property 派生旧字段实现向后兼容；DocumentProcessor 在解析 VLM payload 时增量填充新字段（VLM 没给就空），Orchestrator 在 create_draft 里跨页合并 catalog 并解析 events 的本地 ref。本 phase 不动 prompt、不调 VLM、不改 HTML 模板。

**Tech Stack:** Python 3.11+, Pydantic v2, pytest 7.4+

**Prereq:** spec `docs/superpowers/specs/2026-05-13-event-centric-schema-design.md` 已批准。

---

## Task 1: 添加 `Material` 模型

**Files:**
- Modify: `src/sci_data_logger/schemas.py` — 在 `MaterialInput` 之后插入新类
- Test: `tests/test_schemas.py` — 新增 `test_material_defaults`

- [ ] **Step 1: 写失败测试**

在 `tests/test_schemas.py` 末尾追加：
```python
def test_material_defaults_and_required_fields():
    from sci_data_logger.schemas import Material

    m = Material(canonical_name="Mn2O3")
    assert m.canonical_name == "Mn2O3"
    assert m.display_name is None
    assert m.aliases == []
    assert m.chemical_formula is None
    assert m.role is None
    assert m.metadata == {}
    assert m.material_id.startswith("mat_")

    m2 = Material(canonical_name="LiCl", display_name="氯化锂",
                  aliases=["LiCl·H2O"], chemical_formula="LiCl",
                  role="precursor")
    assert m2.role == "precursor"
    assert "LiCl·H2O" in m2.aliases
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/test_schemas.py::test_material_defaults_and_required_fields -v
```
Expected: FAIL with `ImportError` or `AttributeError: module 'sci_data_logger.schemas' has no attribute 'Material'`

- [ ] **Step 3: 添加 Material 模型**

在 `src/sci_data_logger/schemas.py` 的 `MaterialInput` 类之后（约第 64 行）插入：
```python
class Material(BaseModel):
    """Catalog-level material entry, deduplicated across pages."""
    material_id: str = Field(default_factory=lambda: new_id("mat"))
    canonical_name: str
    display_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    chemical_formula: str | None = None
    role: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/test_schemas.py::test_material_defaults_and_required_fields -v
```
Expected: PASS

- [ ] **Step 5: 跑全套确保不破坏现有**

```bash
pytest tests/ -v
```
Expected: 22 passed (21 old + 1 new)

- [ ] **Step 6: 提交**

```bash
git add src/sci_data_logger/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): add Material catalog model"
```

---

## Task 2: 添加 `Instrument` 模型

**Files:**
- Modify: `src/sci_data_logger/schemas.py` — 在 `InstrumentProfile` 之后追加新类（不要混淆，`InstrumentProfile` 是仪器注册表用的配置，`Instrument` 是 catalog 实例）
- Test: `tests/test_schemas.py` — 新增 `test_instrument_defaults_and_label_split`

- [ ] **Step 1: 写失败测试**

在 `tests/test_schemas.py` 追加：
```python
def test_instrument_defaults_and_label_split():
    """关键场景：'707球磨' 必须能拆成 technique=ball_mill + instrument_label='707'."""
    from sci_data_logger.schemas import Instrument

    ins = Instrument(technique="ball_mill", instrument_label="707",
                     model="高能行星球磨")
    assert ins.technique == "ball_mill"
    assert ins.instrument_label == "707"
    assert ins.location is None
    assert ins.model == "高能行星球磨"
    assert ins.instrument_id.startswith("instr_")

    # technique 必填
    import pytest
    with pytest.raises(Exception):
        Instrument()  # type: ignore[call-arg]
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/test_schemas.py::test_instrument_defaults_and_label_split -v
```
Expected: FAIL with `AttributeError: 'Instrument'`

- [ ] **Step 3: 添加 Instrument 模型**

在 `src/sci_data_logger/schemas.py` 的 `InstrumentProfile` 类之后插入（约第 88 行后）：
```python
class Instrument(BaseModel):
    """Catalog-level instrument entry. `instrument_label` 例如实验室内的红圈编号 '707'。"""
    instrument_id: str = Field(default_factory=lambda: new_id("instr"))
    technique: str           # ball_mill / xrd / sem / raman / eis / heat_treatment / weigh / other
    instrument_label: str | None = None
    location: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
```

注意：`technique` 故意用 `str` 而非 `Literal[...]`，配合 TermAliaser 的"未列出走 other"扩展策略；下游 prompt 会用 Literal 约束 VLM 输出。

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/test_schemas.py::test_instrument_defaults_and_label_split -v
```
Expected: PASS

- [ ] **Step 5: 跑全套**

```bash
pytest tests/ -v
```
Expected: 23 passed

- [ ] **Step 6: 提交**

```bash
git add src/sci_data_logger/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): add Instrument catalog model with label/technique split"
```

---

## Task 3: 添加 `EventIO` / `EventOutput` 子模型

**Files:**
- Modify: `src/sci_data_logger/schemas.py` — 紧邻新增 Material/Instrument 之后追加
- Test: `tests/test_schemas.py` — 新增 `test_event_io_models`

- [ ] **Step 1: 写失败测试**

```python
def test_event_io_models():
    from sci_data_logger.schemas import EventIO, EventOutput, FieldValue

    io = EventIO(material_ref="mat_abc", amount=FieldValue(value=1.5, unit="g"))
    assert io.material_ref == "mat_abc"
    assert io.amount.value == 1.5
    assert io.notes is None

    out = EventOutput(material_ref="mat_xyz",
                     amount=FieldValue(value=2.5, unit="g"),
                     target_phase="P-3m1",
                     failure_marker="没合成")
    assert out.target_phase == "P-3m1"
    assert out.failure_marker == "没合成"
    assert out.material_ref == "mat_xyz"
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/test_schemas.py::test_event_io_models -v
```
Expected: FAIL

- [ ] **Step 3: 添加模型**

在 `src/sci_data_logger/schemas.py` 中、Instrument 之后追加：
```python
class EventIO(BaseModel):
    """Event input/output edge — references a Material by id, optionally with amount."""
    material_ref: str
    amount: FieldValue | None = None
    notes: str | None = None


class EventOutput(EventIO):
    """Output edge with additional product-level fields."""
    target_phase: str | None = None
    failure_marker: str | None = None
```

- [ ] **Step 4: 验证通过**

```bash
pytest tests/test_schemas.py::test_event_io_models -v
```
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/sci_data_logger/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): add EventIO and EventOutput edge models"
```

---

## Task 4: 添加 `ExperimentEvent` 模型

**Files:**
- Modify: `src/sci_data_logger/schemas.py` — 在 EventIO/EventOutput 之后追加
- Test: `tests/test_schemas.py` — 新增 `test_experiment_event_defaults`

- [ ] **Step 1: 写失败测试**

```python
def test_experiment_event_defaults_and_required():
    from sci_data_logger.schemas import (
        ExperimentEvent, EventIO, EventOutput, FieldValue
    )

    e = ExperimentEvent(
        sequence_index=1,
        action_type="mill",
        description="600rpm 15h 高能行星球磨",
        page_ref="page_xxx",
    )
    assert e.event_id.startswith("evt_")
    assert e.sequence_index == 1
    assert e.date_label is None
    assert e.date_iso is None
    assert e.location is None
    assert e.instrument_ref is None
    assert e.operator is None
    assert e.inputs == []
    assert e.outputs == []
    assert e.parameters == {}
    assert e.recipe_ratio is None
    assert e.equation is None
    assert e.observations == []
    assert e.evidence_refs == []
    assert e.confidence is None

    full = ExperimentEvent(
        sequence_index=2,
        date_label="5.20",
        action_type="mill",
        description="...",
        page_ref="page_yyy",
        inputs=[EventIO(material_ref="mat_a")],
        outputs=[EventOutput(material_ref="mat_b", failure_marker="X")],
        parameters={"speed": FieldValue(value=600, unit="rpm")},
        equation="A + B = C",
        recipe_ratio={"target_element": "Na", "excess_pct": 7},
        confidence=0.9,
    )
    assert full.equation == "A + B = C"
    assert full.recipe_ratio["excess_pct"] == 7
    assert full.outputs[0].failure_marker == "X"
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/test_schemas.py::test_experiment_event_defaults_and_required -v
```
Expected: FAIL

- [ ] **Step 3: 添加模型**

在 `src/sci_data_logger/schemas.py` 中、EventOutput 之后追加：
```python
class ExperimentEvent(BaseModel):
    """Atomic unit of the experiment timeline."""
    event_id: str = Field(default_factory=lambda: new_id("evt"))
    sequence_index: int

    # Time + space anchors
    date_label: str | None = None
    date_iso: str | None = None
    location: str | None = None
    instrument_ref: str | None = None
    operator: str | None = None

    # Body
    action_type: str
    description: str
    inputs: list[EventIO] = Field(default_factory=list)
    outputs: list[EventOutput] = Field(default_factory=list)
    parameters: dict[str, FieldValue] = Field(default_factory=dict)

    # Edge-case semantic fields
    recipe_ratio: dict[str, Any] | None = None
    equation: str | None = None

    observations: list[FieldValue] = Field(default_factory=list)

    page_ref: str
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
```

- [ ] **Step 4: 验证通过**

```bash
pytest tests/test_schemas.py::test_experiment_event_defaults_and_required -v
```
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/sci_data_logger/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): add ExperimentEvent model"
```

---

## Task 5: PagePacket 扩展 8 个新字段

**Files:**
- Modify: `src/sci_data_logger/schemas.py` — PagePacket 类（当前位于约 101-121 行）
- Test: `tests/test_schemas.py` — 新增 `test_page_packet_new_fields`

- [ ] **Step 1: 写失败测试**

```python
def test_page_packet_new_extracted_fields_default_empty():
    from sci_data_logger.schemas import PagePacket

    p = PagePacket(source_path="x.jpg")
    # 已有字段
    assert p.page_types == ["unknown"]
    assert p.sample_id is None
    # 新增字段默认值
    assert p.extracted_dates == []
    assert p.extracted_locations == []
    assert p.extracted_batches == []
    assert p.extracted_equations == []
    assert p.extracted_target_phases == []
    assert p.extracted_failure_markers == []
    assert p.extracted_recipe_ratios == []
    assert p.extracted_events == []
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/test_schemas.py::test_page_packet_new_extracted_fields_default_empty -v
```
Expected: FAIL with `AttributeError: 'PagePacket' object has no attribute 'extracted_dates'`

- [ ] **Step 3: 在 PagePacket 类里添加 8 个字段**

在 `src/sci_data_logger/schemas.py` 的 `PagePacket` 类中、`raw_model_output` 字段之前插入：
```python
    extracted_dates: list[str] = Field(default_factory=list)
    extracted_locations: list[str] = Field(default_factory=list)
    extracted_batches: list[str] = Field(default_factory=list)
    extracted_equations: list[str] = Field(default_factory=list)
    extracted_target_phases: list[str] = Field(default_factory=list)
    extracted_failure_markers: list[dict[str, Any]] = Field(default_factory=list)
    extracted_recipe_ratios: list[dict[str, Any]] = Field(default_factory=list)
    extracted_events: list[ExperimentEvent] = Field(default_factory=list)
```

注意：`extracted_events` 引用 `ExperimentEvent`，所以 Task 4 必须先做。

- [ ] **Step 4: 验证通过**

```bash
pytest tests/test_schemas.py::test_page_packet_new_extracted_fields_default_empty -v
```
Expected: PASS

- [ ] **Step 5: 全套确保 21 老用例不破**

```bash
pytest tests/ -v
```
Expected: 26 passed (21 old + 5 new from Tasks 1–5)

- [ ] **Step 6: 提交**

```bash
git add src/sci_data_logger/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): extend PagePacket with 8 new extracted_* fields"
```

---

## Task 6: ExperimentRecord 加 3 张主表 + 兼容 property

**Files:**
- Modify: `src/sci_data_logger/schemas.py` — `ExperimentRecord` 类（当前约 123-138 行）
- Test: `tests/test_schemas.py` — 新增 `test_experiment_record_catalogs_and_compat_properties`

- [ ] **Step 1: 写失败测试**

```python
def test_experiment_record_catalogs_and_compat_properties():
    from sci_data_logger.schemas import (
        ExperimentRecord, Material, Instrument, ExperimentEvent,
        EventIO, EventOutput, FieldValue,
    )

    # 空 catalogs：兼容 property 退化为空
    rec = ExperimentRecord(experiment_id="EXP-0")
    assert rec.materials_catalog == []
    assert rec.instruments_catalog == []
    assert rec.events == []
    assert rec.materials == []   # property 派生
    assert rec.steps == []
    assert rec.observations == []

    # 填充 catalog + events，检查 property 派生正确
    mat_a = Material(canonical_name="LiCl", role="precursor")
    mat_b = Material(canonical_name="Li2ZrCl6", role="target")
    evt = ExperimentEvent(
        sequence_index=1,
        action_type="mill",
        description="球磨",
        page_ref="page_xxx",
        inputs=[EventIO(material_ref=mat_a.material_id)],
        outputs=[EventOutput(material_ref=mat_b.material_id, failure_marker="X")],
        observations=[FieldValue(value="没合成", confidence=0.9)],
    )
    rec2 = ExperimentRecord(
        experiment_id="EXP-1",
        materials_catalog=[mat_a, mat_b],
        events=[evt],
    )
    # property 派生
    assert len(rec2.materials) == 2
    assert {m.name for m in rec2.materials} == {"LiCl", "Li2ZrCl6"}
    assert len(rec2.steps) == 1
    assert rec2.steps[0].step_type == "mill"
    assert rec2.steps[0].description == "球磨"
    assert rec2.steps[0].sequence_index == 1
    # observations 派生
    assert len(rec2.observations) == 1
    assert rec2.observations[0].value == "没合成"
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/test_schemas.py::test_experiment_record_catalogs_and_compat_properties -v
```
Expected: FAIL

- [ ] **Step 3: 修改 ExperimentRecord**

将 `ExperimentRecord` 类替换为：
```python
class ExperimentRecord(BaseModel):
    """Experiment draft. V0: keeps materials/steps/observations as derived properties for backward compat."""

    experiment_id: str
    project_id: str | None = None
    group_id: str | None = None
    operator: str | None = None
    title: str | None = None
    status: ReviewStatus = ReviewStatus.DRAFT

    # New event-centric tables (Phase 0)
    materials_catalog: list[Material] = Field(default_factory=list)
    instruments_catalog: list[Instrument] = Field(default_factory=list)
    events: list[ExperimentEvent] = Field(default_factory=list)

    # Source / measurement (unchanged)
    source_assets: list[DataAsset] = Field(default_factory=list)
    pages: list[PagePacket] = Field(default_factory=list)
    measurements: list[MeasurementPacket] = Field(default_factory=list)
    review_issues: list[ReviewIssue] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # === Backward-compat derived properties (V0 only; deprecate in Phase 3) ===
    @property
    def materials(self) -> list[MaterialInput]:
        return [
            MaterialInput(
                name=m.canonical_name,
                role=m.role,
                amount=None,
                metadata={
                    "aliases": m.aliases,
                    "chemical_formula": m.chemical_formula,
                    **(m.metadata or {}),
                },
            )
            for m in self.materials_catalog
        ]

    @property
    def steps(self) -> list[ProtocolStep]:
        return [
            ProtocolStep(
                step_type=e.action_type,
                sequence_index=e.sequence_index,
                description=e.description,
                inputs=[io.material_ref for io in e.inputs],
                outputs=[io.material_ref for io in e.outputs],
                parameters=e.parameters,
                evidence_refs=e.evidence_refs,
                confidence=e.confidence,
            )
            for e in self.events
        ]

    @property
    def observations(self) -> list[FieldValue]:
        return [obs for e in self.events for obs in e.observations]
```

注意：原来的 `materials: list[MaterialInput]`、`steps: list[ProtocolStep]`、`observations: list[FieldValue]` 字段被 property 替代。如果现有代码（orchestrator / cli / tests）直接对这些字段赋值会出错——下一个 task 处理 orchestrator。

- [ ] **Step 4: 验证新测试通过**

```bash
pytest tests/test_schemas.py::test_experiment_record_catalogs_and_compat_properties -v
```
Expected: PASS

- [ ] **Step 5: 看现有测试是否破**

```bash
pytest tests/ -v
```
Expected: 一些 FAIL，因为 orchestrator.py 还在赋值 `record.materials=` / `.steps=` / `.observations=`。下一个 task 修。**这是预期的，不要 commit 这一步，先跳到 Task 7。**

如果意外全绿，那是因为 orchestrator 没设置这些字段。检查 `orchestrator.py` Line 36-46 是否还有 `materials=...` 等参数；如果有，下一 task 必须处理。

- [ ] **Step 6: 暂存当前改动（不 commit）**

```bash
git add -A   # 暂存
git status   # 应当显示 modified: src/sci_data_logger/schemas.py tests/test_schemas.py
```

不要 commit；继续 Task 7。

---

## Task 7: Orchestrator 适配新 ExperimentRecord（暂停旧字段赋值）

**Files:**
- Modify: `src/sci_data_logger/services/orchestrator.py` — `create_draft` 方法（约第 29-61 行）

- [ ] **Step 1: 读现有代码**

```bash
sed -n '29,61p' src/sci_data_logger/services/orchestrator.py
```

预期能看到 `materials=materials, steps=steps, observations=observations`（这些会跟新 property 冲突）。

- [ ] **Step 2: 修改 create_draft 去掉旧字段赋值**

将 `src/sci_data_logger/services/orchestrator.py` 的 `create_draft` 方法替换为：
```python
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

    # Phase 0: 直接把每页的 extracted_materials/extracted_steps/extracted_observations 上转到 catalog/events
    # 真正的 catalog 去重 + ref 解析在后续 Task 8-10 实现，此处先临时映射保住兼容
    materials_catalog = self._legacy_materials_to_catalog(pages)
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
        instruments_catalog=[],   # Task 9 填
        events=events,
        measurements=measurements,
        metadata={"user_fields": request.user_fields},
    )
    record.review_issues.extend(self._basic_review(record))
    if record.review_issues:
        record.status = ReviewStatus.NEEDS_REVIEW
    return record

@staticmethod
def _legacy_materials_to_catalog(pages: list[PagePacket]) -> list[Material]:
    """Phase 0 桥接：把旧 PagePacket.extracted_materials 映射成 Material catalog。"""
    seen: dict[tuple[str, str | None], Material] = {}
    for page in pages:
        for mat in page.extracted_materials:
            key = (mat.name.strip(), mat.role)
            if key not in seen:
                seen[key] = Material(
                    canonical_name=mat.name.strip(),
                    role=mat.role,
                    metadata=mat.metadata or {},
                )
    return list(seen.values())

@staticmethod
def _legacy_steps_to_events(pages: list[PagePacket]) -> list[ExperimentEvent]:
    """Phase 0 桥接：把旧 PagePacket.extracted_steps 映射成 ExperimentEvent。"""
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
                # inputs/outputs 字符串 → 暂不构造 EventIO（material_ref 解析在 Task 10）
                inputs=[],
                outputs=[],
                observations=[
                    obs for obs in page.extracted_observations
                ] if step.sequence_index == 1 else [],  # observations 暂挂 sequence_index=1
            ))
    return merged
```

并在 imports 增加：
```python
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
```

删除旧的 `_merge_materials` / `_merge_steps` 静态方法（Phase 0 临时方法 `_legacy_*` 替代）。

- [ ] **Step 3: 跑全套测试**

```bash
pytest tests/ -v
```
Expected: 26 passed（21 个老用例兼容 property + 5 个新 schema 用例）

如果 fail，常见原因：
- `test_unparseable_page_marks_experiment_needs_review` 检查 `record.status == NEEDS_REVIEW` → 仍然应该过
- 任何 `record.materials = ...` 风格的旧测试 → 修：用 `record.materials_catalog = ...`

- [ ] **Step 4: 提交（合并 Task 6 + Task 7 的暂存）**

```bash
git add src/sci_data_logger/schemas.py src/sci_data_logger/services/orchestrator.py tests/test_schemas.py
git commit -m "feat(schema/orchestrator): upgrade ExperimentRecord with catalogs+events, derive legacy materials/steps as properties"
```

---

## Task 8: 新增 `date_heuristics.py` 工具

**Files:**
- Create: `src/sci_data_logger/utils/date_heuristics.py`
- Test: `tests/test_date_heuristics.py` （新文件）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_date_heuristics.py`：
```python
from sci_data_logger.utils.date_heuristics import label_to_iso


def test_label_to_iso_basic_month_day():
    # M.D 形式，假设当前年
    assert label_to_iso("5.20", default_year=2026) == "2026-05-20"
    assert label_to_iso("6.10", default_year=2026) == "2026-06-10"
    assert label_to_iso("12.31", default_year=2026) == "2026-12-31"


def test_label_to_iso_full_date():
    assert label_to_iso("2026-05-20") == "2026-05-20"
    assert label_to_iso("2026.5.20", default_year=2026) == "2026-05-20"


def test_label_to_iso_unparseable_returns_none():
    assert label_to_iso("Day 3") is None
    assert label_to_iso(None) is None
    assert label_to_iso("") is None
    assert label_to_iso("???") is None
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/test_date_heuristics.py -v
```
Expected: FAIL with `ImportError: cannot import name 'label_to_iso'`

- [ ] **Step 3: 实现 date_heuristics**

创建 `src/sci_data_logger/utils/date_heuristics.py`：
```python
"""Best-effort date_label -> ISO 8601 推断。失败返回 None，不抛异常。"""
from __future__ import annotations

import re
from datetime import datetime

_MD_PATTERN = re.compile(r"^(\d{1,2})[./-](\d{1,2})$")
_YMD_PATTERN = re.compile(r"^(\d{4})[./-](\d{1,2})[./-](\d{1,2})$")


def label_to_iso(label: str | None, default_year: int | None = None) -> str | None:
    """Convert date label tokens like '5.20' or '2026.5.20' into ISO 'YYYY-MM-DD'.

    Returns None if the label can't be parsed.
    """
    if not label:
        return None
    s = str(label).strip()
    if not s:
        return None

    m = _YMD_PATTERN.match(s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
    else:
        m = _MD_PATTERN.match(s)
        if not m:
            return None
        mo, d = (int(x) for x in m.groups())
        y = default_year or datetime.now().year

    try:
        return datetime(y, mo, d).strftime("%Y-%m-%d")
    except ValueError:
        return None
```

- [ ] **Step 4: 验证通过**

```bash
pytest tests/test_date_heuristics.py -v
```
Expected: 3 PASS

- [ ] **Step 5: 提交**

```bash
git add src/sci_data_logger/utils/date_heuristics.py tests/test_date_heuristics.py
git commit -m "feat(utils): add date_heuristics.label_to_iso for M.D / YYYY-MM-DD parsing"
```

---

## Task 9: DocumentProcessor 解析 catalog (materials + instruments)

**Files:**
- Modify: `src/sci_data_logger/services/document.py` — `_analyze_image`
- Test: `tests/test_document_processor.py` — 新增 `test_catalog_parsing_from_payload`

- [ ] **Step 1: 写失败测试**

在 `tests/test_document_processor.py` 末尾追加：
```python
def test_catalog_parsing_from_vlm_payload(monkeypatch):
    """模拟 VLM 返回新 schema payload，验证 PagePacket 填充 materials/instruments catalog。"""
    from pathlib import Path
    from sci_data_logger.services.document import DocumentProcessor
    from sci_data_logger.vlm import QwenVLMClient

    class FakeVLMClient(QwenVLMClient):
        def __init__(self): pass
        def analyze_image(self, image_path, prompt):
            return {
                "raw_text": "...",
                "json": {
                    "page_types": ["synthesis_note"],
                    "sample_id": "Li2ZrCl6",
                    "materials_catalog": [
                        {"name": "LiCl", "canonical_name": "LiCl",
                         "role": "precursor", "aliases": []},
                        {"name": "ZrCl4", "canonical_name": "ZrCl4",
                         "role": "precursor", "aliases": []},
                    ],
                    "instruments_catalog": [
                        {"technique": "ball_mill", "instrument_label": "707",
                         "model": "高能行星球磨"},
                    ],
                    "events": [],
                    "extracted_dates": ["5.20"],
                    "extracted_target_phases": ["P-3m1"],
                    "text_blocks": ["..."],
                    "table_blocks": [],
                    "open_questions": [],
                    "warnings": [],
                    "review_required": False,
                },
                "model": "qwen3.6-plus",
                "usage": None,
            }

    dp = DocumentProcessor(vlm_client=FakeVLMClient())
    page = dp.analyze_page(Path("tests/test_data/147d9824a7b61f41c32e7e0b6f6dc59c.jpg"))
    # catalog 字段被填充
    assert page.sample_id == "Li2ZrCl6"
    assert len(page.extracted_materials) == 2  # 老字段仍兼容（向后映射）
    # 新字段
    assert page.extracted_dates == ["5.20"]
    assert page.extracted_target_phases == ["P-3m1"]
    # 还没有真正的 catalog parsing 进 raw_model_output 的具体处理点
    # 现在断言新字段确实被存到 page.raw_model_output["json"] 里
    assert page.raw_model_output["json"]["materials_catalog"][0]["name"] == "LiCl"
    assert page.raw_model_output["json"]["instruments_catalog"][0]["instrument_label"] == "707"
```

- [ ] **Step 2: 验证现在结果**

```bash
pytest tests/test_document_processor.py::test_catalog_parsing_from_vlm_payload -v
```
Expected: 可能 FAIL，因为 `_facts_from_payload` 等老路径不消费 catalog 字段（但 raw_model_output 应该保留 JSON）。重要：先调一下，看实际报错来定具体修改点。

- [ ] **Step 3: 修改 `_analyze_image` 填新字段**

在 `src/sci_data_logger/services/document.py` 的 `_analyze_image` 方法里、`page = PagePacket(...)` 构造之前加（参考现有逻辑模式）：
```python
        # New schema parsing (Phase 0)
        extracted_dates = self._strings_from_payload(payload.get("extracted_dates", []))
        extracted_locations = self._strings_from_payload(payload.get("extracted_locations", []))
        extracted_batches = self._strings_from_payload(payload.get("extracted_batches", []))
        extracted_equations = self._strings_from_payload(payload.get("extracted_equations", []))
        extracted_target_phases = self._strings_from_payload(payload.get("extracted_target_phases", []))
        # failure markers / recipe_ratios 是 list[dict]，原样传递
        extracted_failure_markers = payload.get("extracted_failure_markers") or []
        if not isinstance(extracted_failure_markers, list):
            extracted_failure_markers = []
        extracted_recipe_ratios = payload.get("extracted_recipe_ratios") or []
        if not isinstance(extracted_recipe_ratios, list):
            extracted_recipe_ratios = []
```

然后在 `PagePacket(...)` 构造参数里加：
```python
            extracted_dates=extracted_dates,
            extracted_locations=extracted_locations,
            extracted_batches=extracted_batches,
            extracted_equations=extracted_equations,
            extracted_target_phases=extracted_target_phases,
            extracted_failure_markers=[
                d for d in extracted_failure_markers if isinstance(d, dict)
            ],
            extracted_recipe_ratios=[
                d for d in extracted_recipe_ratios if isinstance(d, dict)
            ],
            # extracted_events 留到 Task 10
```

- [ ] **Step 4: 验证通过**

```bash
pytest tests/test_document_processor.py::test_catalog_parsing_from_vlm_payload -v
```
Expected: PASS

- [ ] **Step 5: 全套**

```bash
pytest tests/ -v
```
Expected: 30 passed（26 + 1 date_heuristics x 3 + 1 catalog parse）

- [ ] **Step 6: 提交**

```bash
git add src/sci_data_logger/services/document.py tests/test_document_processor.py
git commit -m "feat(document): parse 6 new extracted_* fields from VLM payload"
```

---

## Task 10: DocumentProcessor 解析 events (with local refs)

**Files:**
- Modify: `src/sci_data_logger/services/document.py` — 新增 `_events_from_payload` 实例方法 + 在 `_analyze_image` 调用
- Test: `tests/test_document_processor.py` — 新增 `test_events_parsing_with_local_refs`

- [ ] **Step 1: 写失败测试**

```python
def test_events_parsing_with_local_refs():
    from pathlib import Path
    from sci_data_logger.services.document import DocumentProcessor
    from sci_data_logger.vlm import QwenVLMClient

    class FakeVLMClient(QwenVLMClient):
        def __init__(self): pass
        def analyze_image(self, image_path, prompt):
            return {
                "raw_text": "...",
                "json": {
                    "page_types": ["synthesis_note"],
                    "events": [
                        {
                            "sequence_index": 1,
                            "date_label": "5.20",
                            "action_type": "mill",
                            "description": "球磨",
                            "inputs": [
                                {"material_ref_local": "LiCl",
                                 "amount": {"value": 0.665, "unit": "g", "confidence": 0.9}},
                            ],
                            "outputs": [
                                {"material_ref_local": "Li2ZrCl6",
                                 "failure_marker": "没合成"},
                            ],
                            "parameters": {
                                "speed": {"value": 600, "unit": "rpm", "confidence": 0.9}
                            },
                            "equation": "2LiCl + ZrCl4 = Li2ZrCl6",
                            "confidence": 0.9,
                        }
                    ],
                    "text_blocks": [],
                    "table_blocks": [],
                    "open_questions": [],
                    "warnings": [],
                    "review_required": False,
                },
                "model": "qwen3.6-plus",
                "usage": None,
            }

    dp = DocumentProcessor(vlm_client=FakeVLMClient())
    page = dp.analyze_page(Path("tests/test_data/147d9824a7b61f41c32e7e0b6f6dc59c.jpg"))
    assert len(page.extracted_events) == 1
    e = page.extracted_events[0]
    assert e.action_type == "mill"
    assert e.date_label == "5.20"
    assert e.equation == "2LiCl + ZrCl4 = Li2ZrCl6"
    assert e.confidence == 0.9
    assert e.page_ref == page.page_id
    # local refs 保留原字符串，等 Orchestrator 解析
    assert len(e.inputs) == 1
    assert e.inputs[0].material_ref == "LiCl"  # 暂时 == ref_local
    assert e.inputs[0].amount.value == 0.665
    assert len(e.outputs) == 1
    assert e.outputs[0].material_ref == "Li2ZrCl6"
    assert e.outputs[0].failure_marker == "没合成"
    assert e.parameters["speed"].value == 600
```

- [ ] **Step 2: 验证失败**

```bash
pytest tests/test_document_processor.py::test_events_parsing_with_local_refs -v
```
Expected: FAIL（`extracted_events == []`）

- [ ] **Step 3: 添加 _events_from_payload 与调用**

在 `src/sci_data_logger/services/document.py` 末尾、`_normalize_table_blocks` 之后追加：
```python
    def _events_from_payload(self, items, image_path, page_id):
        """Parse VLM event list. material_ref_local / instrument_ref_local 保留为字符串，
        留给 Orchestrator 解析到真正的 material_id / instrument_id。
        """
        from sci_data_logger.schemas import ExperimentEvent, EventIO, EventOutput

        if not isinstance(items, list):
            return []
        result = []
        for raw in items:
            if not isinstance(raw, dict) or not raw.get("description"):
                continue
            # parameters
            parameters = {}
            for k, v in (raw.get("parameters") or {}).items():
                if isinstance(v, dict):
                    parameters[k] = FieldValue(
                        value=v.get("value"),
                        unit=v.get("unit"),
                        confidence=v.get("confidence"),
                    )
            # inputs / outputs
            inputs = []
            for inp in raw.get("inputs") or []:
                if not isinstance(inp, dict) or not inp.get("material_ref_local"):
                    continue
                amt_raw = inp.get("amount")
                amt = None
                if isinstance(amt_raw, dict) and amt_raw.get("value") is not None:
                    amt = FieldValue(
                        value=amt_raw.get("value"),
                        unit=amt_raw.get("unit"),
                        confidence=amt_raw.get("confidence"),
                    )
                inputs.append(EventIO(
                    material_ref=str(inp["material_ref_local"]),
                    amount=amt,
                    notes=inp.get("notes"),
                ))
            outputs = []
            for outp in raw.get("outputs") or []:
                if not isinstance(outp, dict) or not outp.get("material_ref_local"):
                    continue
                amt_raw = outp.get("amount")
                amt = None
                if isinstance(amt_raw, dict) and amt_raw.get("value") is not None:
                    amt = FieldValue(
                        value=amt_raw.get("value"),
                        unit=amt_raw.get("unit"),
                        confidence=amt_raw.get("confidence"),
                    )
                outputs.append(EventOutput(
                    material_ref=str(outp["material_ref_local"]),
                    amount=amt,
                    notes=outp.get("notes"),
                    target_phase=outp.get("target_phase"),
                    failure_marker=outp.get("failure_marker"),
                ))
            # observations
            obs_list = []
            for ob in raw.get("observations") or []:
                if isinstance(ob, dict):
                    obs_list.append(FieldValue(
                        value=ob.get("value"),
                        unit=ob.get("unit"),
                        confidence=ob.get("confidence"),
                    ))
                else:
                    obs_list.append(FieldValue(value=str(ob)))
            # build event with action_type aliased
            action_type = self.term_aliaser.canonical_step_type(
                raw.get("action_type") or raw.get("description", "")
            )
            result.append(ExperimentEvent(
                sequence_index=int(raw.get("sequence_index") or len(result) + 1),
                date_label=raw.get("date_label"),
                date_iso=raw.get("date_iso"),
                location=raw.get("location"),
                instrument_ref=raw.get("instrument_ref_local"),  # 字符串，待 orchestrator 解析
                operator=raw.get("operator"),
                action_type=action_type,
                description=str(raw["description"]),
                inputs=inputs,
                outputs=outputs,
                parameters=parameters,
                recipe_ratio=raw.get("recipe_ratio") if isinstance(raw.get("recipe_ratio"), dict) else None,
                equation=raw.get("equation"),
                observations=obs_list,
                page_ref=page_id,
                confidence=raw.get("confidence"),
            ))
        return result
```

在 `_analyze_image` 中、`page = PagePacket(...)` 之前调用：
```python
        # 先创建临时 page_id（实际 PagePacket 默认会生成；这里要预读）
        # 简化：先构造 PagePacket 不带 events，构造完取 page_id 再 set events
```

更稳的实现：先 `page_id = new_id("page")`，构造 PagePacket 时传 `page_id`，并把它传给 `_events_from_payload`：
```python
        page_id = new_id("page")
        extracted_events = self._events_from_payload(
            payload.get("events", []), image_path, page_id
        )
```
然后 PagePacket 构造时：
```python
            page_id=page_id,
            extracted_events=extracted_events,
```

并在 imports 里补：
```python
from sci_data_logger.schemas import (
    EvidenceRef, FieldValue, MaterialInput, PagePacket, ProtocolStep, SourceType,
    new_id,
)
```

- [ ] **Step 4: 验证通过**

```bash
pytest tests/test_document_processor.py::test_events_parsing_with_local_refs -v
```
Expected: PASS

- [ ] **Step 5: 全套**

```bash
pytest tests/ -v
```
Expected: 31 passed

- [ ] **Step 6: 提交**

```bash
git add src/sci_data_logger/services/document.py tests/test_document_processor.py
git commit -m "feat(document): parse extracted_events with EventIO/EventOutput from VLM payload"
```

---

## Task 11: Orchestrator `_merge_materials_catalog`

**Files:**
- Modify: `src/sci_data_logger/services/orchestrator.py` — 删除 `_legacy_materials_to_catalog`，新增正式版
- Test: `tests/test_orchestrator_event_merge.py` — 新文件

- [ ] **Step 1: 写失败测试**

创建 `tests/test_orchestrator_event_merge.py`：
```python
from pathlib import Path

from sci_data_logger.schemas import (
    DraftExperimentRequest,
    Material,
    PagePacket,
)
from sci_data_logger.services.orchestrator import ExperimentOrchestrator


class _FakeDocumentProcessor:
    """注入预构造的 PagePacket 列表。"""
    def __init__(self, pages):
        self._pages = list(pages)

    def analyze_page(self, path):
        return self._pages.pop(0)


def test_merge_materials_catalog_deduplicates_across_pages(tmp_path):
    page1 = PagePacket(source_path="p1.jpg")
    page1.raw_model_output = {"json": {"materials_catalog": [
        {"canonical_name": "LiCl", "role": "precursor", "aliases": []},
        {"canonical_name": "ZrCl4", "role": "precursor"},
    ]}}
    page2 = PagePacket(source_path="p2.jpg")
    page2.raw_model_output = {"json": {"materials_catalog": [
        {"canonical_name": "LiCl", "role": "precursor"},  # dup
        {"canonical_name": "Li2ZrCl6", "role": "target"},
    ]}}

    img1 = tmp_path / "p1.jpg"; img1.write_bytes(b"x")
    img2 = tmp_path / "p2.jpg"; img2.write_bytes(b"x")
    orch = ExperimentOrchestrator(
        document_processor=_FakeDocumentProcessor([page1, page2]),
    )
    record = orch.create_draft(DraftExperimentRequest(
        experiment_id="EXP-MERGE", image_paths=[img1, img2],
    ))
    names = sorted(m.canonical_name for m in record.materials_catalog)
    assert names == ["Li2ZrCl6", "LiCl", "ZrCl4"]
    # 同名同 role 只一份
    assert sum(1 for m in record.materials_catalog if m.canonical_name == "LiCl") == 1
```

- [ ] **Step 2: 验证失败**

```bash
pytest tests/test_orchestrator_event_merge.py::test_merge_materials_catalog_deduplicates_across_pages -v
```
Expected: FAIL（当前 `_legacy_materials_to_catalog` 不读 raw_model_output.json.materials_catalog）

- [ ] **Step 3: 实现正式版 `_merge_materials_catalog`**

修改 `src/sci_data_logger/services/orchestrator.py`：
- 删除 `_legacy_materials_to_catalog` 方法
- 新增：
```python
@staticmethod
def _merge_materials_catalog(pages: list[PagePacket]) -> list[Material]:
    """跨页合并 materials_catalog（来自 VLM 的 raw_model_output.json.materials_catalog）。

    去重 key：(canonical_name 大小写不敏感 strip 后, role)。
    aliases 合并；display_name 取第一次出现的。
    """
    seen: dict[tuple[str, str | None], Material] = {}
    for page in pages:
        catalog_items = (
            (page.raw_model_output or {}).get("json", {}).get("materials_catalog") or []
        )
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
                # 合并 aliases
                combined = list(dict.fromkeys([*existing.aliases, *new_aliases]))
                existing.aliases = combined
    return list(seen.values())
```

并在 `create_draft` 里把 `_legacy_materials_to_catalog(pages)` 改成 `self._merge_materials_catalog(pages)`。

- [ ] **Step 4: 验证通过**

```bash
pytest tests/test_orchestrator_event_merge.py::test_merge_materials_catalog_deduplicates_across_pages -v
```
Expected: PASS

- [ ] **Step 5: 全套**

```bash
pytest tests/ -v
```
Expected: 32 passed

- [ ] **Step 6: 提交**

```bash
git add src/sci_data_logger/services/orchestrator.py tests/test_orchestrator_event_merge.py
git commit -m "feat(orchestrator): merge materials_catalog across pages with dedup"
```

---

## Task 12: Orchestrator `_merge_instruments_catalog`

**Files:**
- Modify: `src/sci_data_logger/services/orchestrator.py`
- Test: `tests/test_orchestrator_event_merge.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_orchestrator_event_merge.py` 追加：
```python
def test_merge_instruments_catalog_dedup_by_technique_and_label(tmp_path):
    page1 = PagePacket(source_path="p1.jpg")
    page1.raw_model_output = {"json": {"instruments_catalog": [
        {"technique": "ball_mill", "instrument_label": "707", "model": "高能行星"},
    ]}}
    page2 = PagePacket(source_path="p2.jpg")
    page2.raw_model_output = {"json": {"instruments_catalog": [
        {"technique": "ball_mill", "instrument_label": "707"},  # dup
        {"technique": "ball_mill", "instrument_label": None, "model": "其他"},
    ]}}

    img1 = tmp_path / "p1.jpg"; img1.write_bytes(b"x")
    img2 = tmp_path / "p2.jpg"; img2.write_bytes(b"x")
    orch = ExperimentOrchestrator(
        document_processor=_FakeDocumentProcessor([page1, page2]),
    )
    record = orch.create_draft(DraftExperimentRequest(
        experiment_id="EXP-INSTR", image_paths=[img1, img2],
    ))
    # 707 一份，无 label 一份，共 2 条
    assert len(record.instruments_catalog) == 2
    labels = sorted([ins.instrument_label for ins in record.instruments_catalog],
                    key=lambda x: (x is None, x))
    assert labels == ["707", None]
```

- [ ] **Step 2: 验证失败**

```bash
pytest tests/test_orchestrator_event_merge.py::test_merge_instruments_catalog_dedup_by_technique_and_label -v
```
Expected: FAIL（instruments_catalog 是 []）

- [ ] **Step 3: 实现 `_merge_instruments_catalog`**

在 orchestrator.py 追加：
```python
@staticmethod
def _merge_instruments_catalog(pages: list[PagePacket]) -> list[Instrument]:
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
```

并在 `create_draft` 中把 `instruments_catalog=[]` 换成 `instruments_catalog=self._merge_instruments_catalog(pages)`。

imports 增加：
```python
from sci_data_logger.schemas import Instrument
```

- [ ] **Step 4: 验证通过**

```bash
pytest tests/test_orchestrator_event_merge.py::test_merge_instruments_catalog_dedup_by_technique_and_label -v
```
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/sci_data_logger/services/orchestrator.py tests/test_orchestrator_event_merge.py
git commit -m "feat(orchestrator): merge instruments_catalog across pages with (technique,label) dedup"
```

---

## Task 13: Orchestrator `_resolve_and_merge_events`

**Files:**
- Modify: `src/sci_data_logger/services/orchestrator.py`
- Test: `tests/test_orchestrator_event_merge.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_orchestrator_event_merge.py` 追加：
```python
def test_resolve_events_links_local_refs_to_catalog_ids(tmp_path):
    from sci_data_logger.schemas import ExperimentEvent, EventIO, EventOutput

    page1 = PagePacket(source_path="p1.jpg")
    page1.raw_model_output = {"json": {
        "materials_catalog": [
            {"canonical_name": "LiCl", "role": "precursor", "aliases": ["氯化锂"]},
            {"canonical_name": "Li2ZrCl6", "role": "target"},
        ],
        "instruments_catalog": [
            {"technique": "ball_mill", "instrument_label": "707"},
        ],
    }}
    # 注意 extracted_events 是 PagePacket 字段，由 document.py 填，
    # 这里直接 set 模拟已经过解析的状态
    page1.extracted_events = [
        ExperimentEvent(
            sequence_index=1,
            date_label="5.20",
            action_type="mill",
            description="球磨",
            instrument_ref="ball_mill@707",   # local ref；可被解析
            inputs=[EventIO(material_ref="LiCl")],  # canonical 名直接匹配
            outputs=[EventOutput(material_ref="氯化锂")],  # alias 匹配
            page_ref=page1.page_id,
        ),
        ExperimentEvent(
            sequence_index=2,
            action_type="mill",
            description="第二步",
            inputs=[EventIO(material_ref="ZrCl4")],  # catalog 里没有 -> 自动新增
            outputs=[],
            page_ref=page1.page_id,
        ),
    ]

    img1 = tmp_path / "p1.jpg"; img1.write_bytes(b"x")
    orch = ExperimentOrchestrator(
        document_processor=_FakeDocumentProcessor([page1]),
    )
    record = orch.create_draft(DraftExperimentRequest(
        experiment_id="EXP-EVT", image_paths=[img1],
    ))
    # 解析后 events 的 material_ref 应该是真正的 material_id
    assert len(record.events) == 2
    e1 = record.events[0]
    assert e1.action_type == "mill"
    # 输入解析到 LiCl id
    licl = next(m for m in record.materials_catalog if m.canonical_name == "LiCl")
    assert e1.inputs[0].material_ref == licl.material_id
    # 输出"氯化锂"通过 alias 解析到 LiCl
    assert e1.outputs[0].material_ref == licl.material_id
    # instrument_ref 解析到 707 ball_mill id
    instr = next(i for i in record.instruments_catalog if i.instrument_label == "707")
    assert e1.instrument_ref == instr.instrument_id

    # 第二个 event 引用 catalog 里没有的 ZrCl4 -> 自动新增 + review issue
    assert any(m.canonical_name == "ZrCl4" for m in record.materials_catalog)
    e2 = record.events[1]
    zrcl4 = next(m for m in record.materials_catalog if m.canonical_name == "ZrCl4")
    assert e2.inputs[0].material_ref == zrcl4.material_id

    # 全局 sequence_index 重排
    assert [e.sequence_index for e in record.events] == [1, 2]

    # 自动新增材料 -> ReviewIssue
    assert any("unresolved" in (i.detail or "").lower() or "ZrCl4" in (i.detail or "")
               for i in record.review_issues)
```

- [ ] **Step 2: 验证失败**

```bash
pytest tests/test_orchestrator_event_merge.py::test_resolve_events_links_local_refs_to_catalog_ids -v
```
Expected: FAIL

- [ ] **Step 3: 实现 `_resolve_and_merge_events`**

在 orchestrator.py 追加：
```python
def _resolve_and_merge_events(
    self,
    pages: list[PagePacket],
    materials_catalog: list[Material],
    instruments_catalog: list[Instrument],
) -> tuple[list[ExperimentEvent], list[ReviewIssue]]:
    """解析 page.extracted_events 里的 local refs，并跨页全局排序。

    返回 (events, extra_review_issues)。
    """
    issues: list[ReviewIssue] = []

    def find_material(ref: str) -> Material | None:
        if not ref:
            return None
        ref_norm = ref.strip()
        ref_lower = ref_norm.lower()
        # 1. canonical_name 精确
        for m in materials_catalog:
            if m.canonical_name.strip().lower() == ref_lower:
                return m
        # 2. aliases
        for m in materials_catalog:
            if any(a.strip().lower() == ref_lower for a in m.aliases):
                return m
        # 3. unicode normalize（NFKD 去音标 / 去下标）
        import unicodedata
        ref_nfkd = unicodedata.normalize("NFKD", ref_norm)
        ref_strip = "".join(c for c in ref_nfkd if not unicodedata.combining(c))
        for m in materials_catalog:
            cn = unicodedata.normalize("NFKD", m.canonical_name)
            cn_strip = "".join(c for c in cn if not unicodedata.combining(c))
            if cn_strip.lower() == ref_strip.lower():
                return m
        return None

    def find_or_create_material(ref: str) -> Material:
        m = find_material(ref)
        if m is not None:
            return m
        # 自动新增 + 报 issue
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
        # ref 形式可能是 "ball_mill@707" 或 "高能行星球磨" 或 "707"
        # 先按 (technique, label) 试，再按 model fallback
        for ins in instruments_catalog:
            for token in [
                f"{ins.technique}@{ins.instrument_label}",
                ins.instrument_label,
                ins.model,
                ins.technique,
            ]:
                if token and token.strip().lower() == ref.strip().lower():
                    return ins
        return None

    # 收集所有 events，解析 refs
    all_events: list[ExperimentEvent] = []
    for page_idx, page in enumerate(pages):
        for evt in page.extracted_events:
            # resolve inputs
            new_inputs = []
            for io in evt.inputs:
                mat = find_or_create_material(io.material_ref)
                new_inputs.append(EventIO(
                    material_ref=mat.material_id,
                    amount=io.amount,
                    notes=io.notes,
                ))
            # resolve outputs
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
            # resolve instrument
            instr_id = evt.instrument_ref
            if instr_id:
                ins = find_instrument(instr_id)
                instr_id = ins.instrument_id if ins else None
            # date_iso heuristic
            from sci_data_logger.utils.date_heuristics import label_to_iso
            new_date_iso = evt.date_iso or label_to_iso(evt.date_label)
            new_evt = evt.model_copy(update={
                "inputs": new_inputs,
                "outputs": new_outputs,
                "instrument_ref": instr_id,
                "date_iso": new_date_iso,
                # 保留页内 sequence_index 暂存，全局排序后再更新
            })
            all_events.append((page_idx, new_evt))

    # 全局排序：date_iso 优先；缺失则按 (page_idx, sequence_index)
    def sort_key(item):
        page_idx, e = item
        iso = e.date_iso or ""
        return (iso == "", iso, page_idx, e.sequence_index)

    all_events.sort(key=sort_key)
    # 重排 sequence_index
    final: list[ExperimentEvent] = []
    for new_idx, (_, e) in enumerate(all_events, start=1):
        final.append(e.model_copy(update={"sequence_index": new_idx}))
    return final, issues
```

并修改 `create_draft`：
```python
materials_catalog = self._merge_materials_catalog(pages)
instruments_catalog = self._merge_instruments_catalog(pages)
events, extra_issues = self._resolve_and_merge_events(
    pages, materials_catalog, instruments_catalog
)

record = ExperimentRecord(
    ...
    materials_catalog=materials_catalog,
    instruments_catalog=instruments_catalog,
    events=events,
    ...
)
record.review_issues.extend(self._basic_review(record))
record.review_issues.extend(extra_issues)
```

删除 Task 7 临时的 `_legacy_steps_to_events`，由 `_resolve_and_merge_events` 取代。

注意：如果当前页 `page.extracted_events == []`（VLM 没给新 schema），回退到老 `page.extracted_steps` → 升格成 events。在 `_resolve_and_merge_events` 起始加：
```python
# Fallback：如果某页没 extracted_events，但有 extracted_steps（旧 schema），临时升格
for page in pages:
    if not page.extracted_events and page.extracted_steps:
        # 把旧步骤升格为简化 events
        for step in sorted(page.extracted_steps, key=lambda s: s.sequence_index):
            page.extracted_events.append(ExperimentEvent(
                sequence_index=step.sequence_index,
                action_type=step.step_type,
                description=step.description,
                parameters=step.parameters,
                page_ref=page.page_id,
                evidence_refs=step.evidence_refs,
                confidence=step.confidence,
            ))
```

确保 imports：
```python
from sci_data_logger.schemas import (
    DataAsset, DraftExperimentRequest,
    EventIO, EventOutput, ExperimentEvent, ExperimentRecord,
    Instrument, Material, PagePacket,
    ReviewIssue, ReviewStatus, SourceType,
)
```

- [ ] **Step 4: 验证通过**

```bash
pytest tests/test_orchestrator_event_merge.py::test_resolve_events_links_local_refs_to_catalog_ids -v
```
Expected: PASS

- [ ] **Step 5: 全套**

```bash
pytest tests/ -v
```
Expected: 33 passed（26 + 4 date + 1 catalog parse + 1 events parse + 3 merge）

- [ ] **Step 6: 提交**

```bash
git add src/sci_data_logger/services/orchestrator.py tests/test_orchestrator_event_merge.py
git commit -m "feat(orchestrator): resolve event local refs to catalog ids with alias/normalize fallback + auto-add"
```

---

## Task 14: 回归 e2e（不调真 VLM，用 mock）

**Files:**
- Test: `tests/test_orchestrator_event_merge.py` — 新增完整 end-to-end 测试

- [ ] **Step 1: 写失败测试**

在 `tests/test_orchestrator_event_merge.py` 追加：
```python
def test_end_to_end_event_centric_record_from_mock_vlm(tmp_path, monkeypatch):
    """完整路径：mock VLM → DocumentProcessor → Orchestrator → ExperimentRecord."""
    from pathlib import Path
    from sci_data_logger.services.document import DocumentProcessor
    from sci_data_logger.vlm import QwenVLMClient

    class FakeVLMClient(QwenVLMClient):
        def __init__(self): pass
        def analyze_image(self, image_path, prompt):
            return {
                "raw_text": "...",
                "json": {
                    "page_types": ["synthesis_note", "calculation"],
                    "sample_id": "Li2ZrCl6",
                    "materials_catalog": [
                        {"canonical_name": "LiCl", "role": "precursor"},
                        {"canonical_name": "ZrCl4", "role": "precursor"},
                        {"canonical_name": "Li2ZrCl6", "role": "target"},
                    ],
                    "instruments_catalog": [
                        {"technique": "ball_mill", "instrument_label": "707",
                         "model": "高能行星球磨"},
                    ],
                    "events": [
                        {
                            "sequence_index": 1,
                            "date_label": "5.20",
                            "action_type": "mill",
                            "description": "600rpm 15h",
                            "instrument_ref_local": "ball_mill@707",
                            "inputs": [{"material_ref_local": "LiCl"},
                                       {"material_ref_local": "ZrCl4"}],
                            "outputs": [{"material_ref_local": "Li2ZrCl6",
                                         "failure_marker": "没合成"}],
                            "parameters": {"speed": {"value": 600, "unit": "rpm"}},
                            "equation": "2LiCl + ZrCl4 = Li2ZrCl6",
                            "confidence": 0.9,
                        }
                    ],
                    "extracted_dates": ["5.20"],
                    "extracted_target_phases": ["P-3m1"],
                    "extracted_failure_markers": [{"marker": "X", "target": "Li2ZrCl6"}],
                    "text_blocks": [],
                    "table_blocks": [],
                    "open_questions": [],
                    "warnings": [],
                    "review_required": True,
                },
                "model": "qwen3.6-plus",
                "usage": None,
            }

    img = tmp_path / "fake.jpg"
    img.write_bytes(b"x")
    dp = DocumentProcessor(vlm_client=FakeVLMClient())
    orch = ExperimentOrchestrator(document_processor=dp)
    record = orch.create_draft(DraftExperimentRequest(
        experiment_id="E2E-EVENT", image_paths=[img],
    ))

    # 顶层 catalog
    assert {m.canonical_name for m in record.materials_catalog} == {"LiCl", "ZrCl4", "Li2ZrCl6"}
    assert len(record.instruments_catalog) == 1
    assert record.instruments_catalog[0].instrument_label == "707"

    # events 解析
    assert len(record.events) == 1
    e = record.events[0]
    assert e.action_type == "mill"
    assert e.date_iso == "2026-05-20"
    assert e.equation == "2LiCl + ZrCl4 = Li2ZrCl6"
    # refs 已经解析为 catalog id
    licl_id = next(m for m in record.materials_catalog if m.canonical_name == "LiCl").material_id
    assert e.inputs[0].material_ref == licl_id
    instr_id = record.instruments_catalog[0].instrument_id
    assert e.instrument_ref == instr_id

    # 兼容 property
    assert len(record.materials) == 3   # 派生
    assert len(record.steps) == 1
    assert record.steps[0].step_type == "mill"

    # PagePacket 新字段被填
    assert "5.20" in record.pages[0].extracted_dates
    assert "P-3m1" in record.pages[0].extracted_target_phases

    # status / review
    assert record.status.value == "needs_review"
```

- [ ] **Step 2: 验证**

```bash
pytest tests/test_orchestrator_event_merge.py::test_end_to_end_event_centric_record_from_mock_vlm -v
```
Expected: PASS

如果失败，常见原因：
- `_resolve_and_merge_events` 没拿到 `page.extracted_events`，可能 DocumentProcessor 没填——再看 Task 10 实现
- date_iso 不是 2026-05-20——确认 `label_to_iso` default_year

- [ ] **Step 3: 全套**

```bash
pytest tests/ -v
```
Expected: 34 passed

- [ ] **Step 4: 提交**

```bash
git add tests/test_orchestrator_event_merge.py
git commit -m "test(e2e): event-centric record from mock VLM end-to-end"
```

---

## Task 15: 验收

- [ ] **Step 1: 完整 pytest 报告**

```bash
pytest tests/ -v --tb=short
```
Expected: 34 passed, 0 failed, 0 skipped

- [ ] **Step 2: 检查不引入新 ruff 违规**

```bash
ruff check src/ tests/
```
Expected: no new violations（如果已有 baseline 违规可以忽略，但**不要新增**）

- [ ] **Step 3: 跑一次现有 e2e 验证（DEMO-001 那张 145KB 图，可选）**

```bash
source ~/.zshrc 2>/dev/null
python -c "
from pathlib import Path
from sci_data_logger.schemas import DraftExperimentRequest
from sci_data_logger.services.orchestrator import ExperimentOrchestrator

req = DraftExperimentRequest(
    experiment_id='PHASE0-CHECK',
    image_paths=[Path('tests/test_data/147d9824a7b61f41c32e7e0b6f6dc59c.jpg')],
)
record = ExperimentOrchestrator().create_draft(req)
print(f'materials_catalog: {len(record.materials_catalog)}')
print(f'instruments_catalog: {len(record.instruments_catalog)}')
print(f'events: {len(record.events)}')
print(f'materials (compat): {len(record.materials)}')
print(f'steps (compat): {len(record.steps)}')
print(f'status: {record.status}')
"
```
Expected: 
- materials_catalog ≥ 3
- events ≥ 1
- materials (compat) == len(materials_catalog)
- steps (compat) == len(events)
- status == needs_review

注意：此时 prompt 还是 V0（旧版），VLM 不会返回新 schema 的 `materials_catalog / events`，所以会走 Task 13 的 fallback 路径（升格 extracted_materials/extracted_steps）。`extracted_dates / extracted_target_phases / extracted_failure_markers / equations` 在新 prompt 上线前都是 []，这是预期的，不要焦虑。

- [ ] **Step 4: 最终提交**

```bash
git tag phase-0-event-centric-schema
git log --oneline -20   # 应该看到 Task 1-14 的清晰 commit 历史
```

---

## Self-Review Notes

**Spec coverage check**:
- Section 2.1 Material → Task 1 ✓
- Section 2.2 Instrument (707 案例) → Task 2 ✓
- Section 2.3 ExperimentEvent + EventIO/EventOutput → Task 3, 4 ✓
- Section 2.4 ExperimentRecord catalog + property → Task 6 ✓
- Section 2.5 PagePacket 8 字段 → Task 5 ✓
- Section 3.4 跨页合并 + ref 解析（含 alias / unicode normalize / auto-add） → Task 11, 12, 13 ✓
- Section 3.4 date_iso heuristic → Task 8 + Task 13 集成 ✓
- Section 3.6 错误处理（catalog 缺失退化、ref 未识别 auto-add） → Task 13 fallback + auto-create ✓
- Section 5 测试策略：单元 + 集成 + 兼容回归 → Task 1-14 ✓
- Section 6 可扩展性（technique 用 str 而非 Literal，无新 action_type 走 other）→ Task 2 注释 + TermAliaser 既有逻辑 ✓
- Section 7 Phase 0 范围 → 本 plan 全程不动 prompt / vlm/client / HTML 模板 ✓

**已知不在 Phase 0**：
- Prompt 改写（V1 + V2 fallback）→ Phase 1
- timeline HTML 可视化 → Phase 2
- 废弃旧字段 → Phase 3

**风险点**：
- Task 6 修改 ExperimentRecord 字段为 property 会**短暂破坏**现有 orchestrator（Task 7 立即修），不要在 Task 6 commit 前 push。
- Task 13 的 fallback（旧 extracted_steps 升格为 events）确保 prompt 升级前不破回归 e2e。
- 兼容 property 性能：每次 `.materials` / `.steps` / `.observations` 调用都遍历 events——高频 caller 应该 cache，但 Phase 0 不优化。
