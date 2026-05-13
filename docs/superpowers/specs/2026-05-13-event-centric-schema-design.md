# Event-Centric Experiment Record Schema · Design Spec

- **Date**: 2026-05-13
- **Author**: ylll · 主对话 + brainstorming subagents
- **Status**: Draft (待用户复核)
- **Supersedes**: 当前 PagePacket 扁平 schema（materials/steps/observations 三段式）

---

## 1. 目标与背景

### 1.1 用户痛点
现行 schema（V1，已上线）只把 VLM 输出解析成 `materials / steps / observations` 三段。在真实实验本数据上跑过 6 张图（agent 1 报告 + DEMO-001）后暴露三类硬伤：

1. **语义分类粒度不够**：用户在 DEMO-001 可视化里圈出的红圈 "707" 被合并成 `instrument="707球磨"`，但 707 其实是**实验室内的设备编号 / 红圈标签**，应该跟 `technique="ball_mill"` 拆开。这一类"编号 vs 类型"的歧义在材料实验本里普遍存在。
2. **缺失 7 类边缘语义**：日期（5.20 / 5.21 / 6.10）、批次（batch_1/2/3）、目标晶相（P-3m1）、化学方程式（2LiCl+ZrCl4=Li2ZrCl6）、失败标记（X / 没合成）、配方比例（Na 过量 7%）、位置（实验室号）——现在都散在 `extracted_facts` 里，下游无法结构化检索/可视化。
3. **缺乏时间维度**：实验本上的 5.20/5.21/6.10 同一组实验跨多日演化，但 V1 schema 把每个步骤当作扁平 list，丢失了"什么时候做的"这条时间线，复现实验时只能从描述文本里手动挑日期。

### 1.2 设计目标
- **G1**：把 PagePacket → ExperimentRecord 的核心升级为**事件中心模型**，每个事件（event）承载时间、地点、动作、输入产物、参数、现象，让"实验记录本"等同于一条事件流。
- **G2**：拆出独立的 **Materials Catalog + Instruments Catalog** 主数据表，跨页/跨日的同名物质/设备自动去重，607-style 设备编号与 technique 解耦。
- **G3**：新 schema 必须**向后兼容**——21 个现有 pytest 与 API/CLI caller 在过渡期间不被破坏。
- **G4**：可视化升级为**时间轴主导**的 3 区布局，左 catalog / 中 timeline / 右原图+复核。
- **G5**：未来增加图片（用户提到"后续会增加更多的图片"）无需改 schema，仅靠 prompt 枚举 + group_templates 别名扩展。

### 1.3 非目标（明确不做）
- **跨实验共享 catalog**（方案 C，project-level catalog）：本轮 YAGNI，单实验内 catalog 足够。
- **review UI 写回**：本轮只读 HTML，标 issue 给人工，写回是 V2。
- **多模态融合**：不在本轮处理仪器原始数据文件（CSV/TXT 仪器报告）与 events 的合并，沿用现有 `MeasurementPacket`。
- **跨实验路径检索**："Mn2O3 在哪些实验里用过"是 V2 能力，本轮不做。

### 1.4 前置实证依据（已完成）
- **batch_extract 全量**（已完成）：55 张 .jpg 跑完，**ok=44, fail=11（成功率 80%）**，总耗时 56 min，总 token ~720K，估算成本 ~$2.5。摘要在 `reports/batch_extraction_summary_2026-05-13.md`，原始结果在 `/tmp/batch_results/`。
- **Prompt A/B 报告**（`reports/prompt_ab_test_2026-05-13.md`）：sandbox 限制下 V1 数据来自 batch_extract 实测，V2 是 token 数学外推。结论：**V1 单次默认 + V2 复杂页 fallback**（V2 总成本 V1×1.16，触发率 10-20%）。

**Schema 缺口的硬证据（来自 batch_extract 实测）**：
| 现象 | 数据 | 对应 design 决策 |
|---|---|---|
| `extracted_facts` 不同 key 数 | **105 个**跨 44 张图 | 必须升级到结构化 events / catalog，再不能靠扁平 dict |
| Top 1 fact key | `date`（4 张图） | `extracted_dates` 单独字段必要 |
| `instruments` 真实出现 | `707炉` ×3、`球磨机` ×2、`EIS` ×3、`真空干燥箱` ×3、`XRD` ×2 | 707-style 编号 vs 设备类型必须拆开 |
| review_required=True 率 | ~50% | 复核流程必须存在 |
| 失败率与图大小 | 失败全集中 2-5MB 区间 | timeout 治理是独立 P1 TODO |

---

## 2. 数据模型

### 2.1 Material（升级版）
```python
class Material(BaseModel):
    material_id: str = Field(default_factory=lambda: new_id("mat"))
    canonical_name: str                # "Mn2O3" — 规范化（化学式优先）
    display_name: str | None           # "三氧化二锰" — 实验本原文写法
    aliases: list[str]                 # ["Mn₂O₃", "Mn2O3", "三氧化二锰"]
    chemical_formula: str | None
    role: Literal["precursor","target","dopant","additive","solvent","product","byproduct"] | None
    metadata: dict[str, Any]
```
**解决**：跨页同物质不同写法 → 同一 material_id。

### 2.2 Instrument（**回答 707 案例**）
```python
class Instrument(BaseModel):
    instrument_id: str = Field(default_factory=lambda: new_id("instr"))
    technique: Literal["ball_mill","xrd","sem","raman","eis","heat_treatment","weigh","other"]
    instrument_label: str | None       # "707" — 实验室内的编号 / 红圈圈出的那种
    location: str | None               # 房间号 / 实验室名
    manufacturer: str | None
    model: str | None                  # "高能行星球磨"
    metadata: dict[str, Any]
```
**解决**：原文"707球磨"现在拆成 `technique="ball_mill"` + `instrument_label="707"`。

### 2.3 ExperimentEvent（时间轴单元）
```python
class ExperimentEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("evt"))
    sequence_index: int                # 全局序号（orchestrator 重排）

    # 时间 + 空间锚点
    date_label: str | None             # "5.20" / "Day 1" — 原文 token
    date_iso: str | None               # "2026-05-20" — VLM 推断或人工修订
    location: str | None
    instrument_ref: str | None         # instrument_id
    operator: str | None

    # 事件主体
    action_type: Literal["weigh","mix","mill","grind","heat","hold","cool",
                         "calcine","sinter","filter","wash","dry",
                         "characterize","measure","observe","compute","other"]
    description: str
    inputs: list[EventIO]              # 输入物质 + 量
    outputs: list[EventOutput]         # 输出物质 + 量 + target_phase + failure_marker

    # 反应条件
    parameters: dict[str, FieldValue]

    # 你提的"边缘语义"
    recipe_ratio: dict | None          # {"target_element": "Na", "excess_pct": 7}
    equation: str | None               # "2LiCl + ZrCl4 = Li2ZrCl6"
    observations: list[FieldValue]

    # 溯源
    page_ref: str                      # 来自哪一页 PagePacket.page_id
    evidence_refs: list[EvidenceRef]
    confidence: float


class EventIO(BaseModel):
    material_ref: str                  # material_id 引用
    amount: FieldValue | None
    notes: str | None                  # 例 "Na 过量 7%"


class EventOutput(EventIO):
    target_phase: str | None           # "P-3m1" / "Fm-3m" / "单斜"
    failure_marker: str | None         # "X" / "没合成" / "纯度低"
```

### 2.4 ExperimentRecord（顶层升级）
```python
class ExperimentRecord(BaseModel):
    experiment_id: str
    project_id: str | None
    group_id: str | None
    operator: str | None
    title: str | None
    status: ReviewStatus

    # 新增 3 张主表
    materials_catalog: list[Material]
    instruments_catalog: list[Instrument]
    events: list[ExperimentEvent]      # 主时间轴

    # 原始溯源（不变）
    pages: list[PagePacket]
    source_assets: list[DataAsset]
    measurements: list[MeasurementPacket]

    review_issues: list[ReviewIssue]
    metadata: dict[str, Any]

    # === 兼容 property（V0 阶段保留，V3 阶段废弃）===
    @property
    def materials(self) -> list[MaterialInput]:
        """旧 schema 兼容：从 materials_catalog 派生扁平视图"""
        return [
            MaterialInput(name=m.canonical_name, role=m.role, amount=None,
                          metadata={"aliases": m.aliases, "canonical": m.canonical_name})
            for m in self.materials_catalog
        ]

    @property
    def steps(self) -> list[ProtocolStep]:
        """旧 schema 兼容：从 events 派生"""
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
        """旧 schema 兼容：events.observations 拍平"""
        return [obs for e in self.events for obs in e.observations]
```

### 2.5 PagePacket（小幅扩展，VLM 输出端）
现有字段保留。新增 8 个原料字段供 orchestrator 组装 events 用：
- `extracted_dates: list[str]` — `["5.20","5.21","6.10"]`
- `extracted_locations: list[str]`
- `extracted_batches: list[str]` — `["batch_1","①"]`
- `extracted_equations: list[str]`
- `extracted_target_phases: list[str]` — `["P-3m1"]`
- `extracted_failure_markers: list[dict]` — `[{"marker":"X","target":"...","reason":"..."}]`
- `extracted_recipe_ratios: list[dict]`
- `extracted_events: list[ExperimentEvent]` — VLM 直接拆的本页 events，含 local refs，orchestrator 后续做跨页归并

---

## 3. Pipeline 与 Prompt 改造

### 3.1 Prompt 策略：V1 单次默认 + V2 复杂页 fallback
**A/B 测试结论**（`reports/prompt_ab_test_2026-05-13.md`）：
- V1 单次输出新 schema 全部内容（prompt ~150-180 行）→ **默认路径**
- V2 两段式（pass 1: catalog only；pass 2: events with catalog 作 context）→ 仅在以下触发条件之一时启用：
  - V1 输出 reasoning_tokens / completion_tokens > 0.7（"模型疲劳"信号）
  - catalog 重复率 > 50%
  - events ≥ 6 条
- 预期 V2 触发率 10-20%，总成本 V1 × 1.16

### 3.2 V1 prompt JSON shape（单页输出）
```json
{
  "page_types": ["synthesis_note","calculation"],
  "sample_id": "Li2ZrCl6",
  "materials_catalog": [
    {"name":"LiCl","canonical_name":"LiCl","role":"precursor","aliases":[],"chemical_formula":"LiCl"}
  ],
  "instruments_catalog": [
    {"technique":"ball_mill","instrument_label":"707","model":"高能行星球磨"}
  ],
  "events": [
    {
      "sequence_index": 1,
      "date_label": "5.20", "date_iso": null,
      "instrument_ref_local": "高能行星球磨",
      "action_type": "mill",
      "description": "600rpm 15h 高能行星球磨",
      "inputs": [{"material_ref_local":"LiCl","amount":{"value":0.665,"unit":"g","confidence":0.9}}],
      "outputs": [{"material_ref_local":"Li2ZrCl6","amount":{"value":2.495,"unit":"g"},
                   "failure_marker":"没合成","target_phase":null}],
      "parameters": {"speed":{"value":600,"unit":"rpm","confidence":0.9},
                     "duration":{"value":15,"unit":"h","confidence":0.9}},
      "equation": "2LiCl + ZrCl4 = Li2ZrCl6",
      "recipe_ratio": null,
      "observations": [{"value":"没合成","confidence":0.9}],
      "confidence": 0.9
    }
  ],
  "extracted_dates": ["5.20","5.21","6.10"],
  "extracted_locations": [],
  "extracted_batches": ["batch_1","batch_2","batch_3"],
  "extracted_equations": ["2LiCl + ZrCl4 = Li2ZrCl6"],
  "extracted_target_phases": ["P-3m1"],
  "extracted_failure_markers": [{"marker":"X","target":"Li2.25Zr0.75In0.25Cl6","reason":"未合成"}],
  "extracted_recipe_ratios": [],
  "text_blocks": [...], "table_blocks": [...],
  "open_questions": [...], "warnings": [...], "review_required": true
}
```
**关键**：`material_ref_local` / `instrument_ref_local` 是 VLM 内部字符串（化学式或文本名）。Orchestrator 按 canonical_name 匹配到 catalog 项的真正 ID。

### 3.3 DocumentProcessor 改造
- 新增 `_catalog_materials_from_payload` / `_catalog_instruments_from_payload` / `_events_from_payload`
- 七个 `_extracted_<kind>_from_payload`
- 维持现有的 `_normalize_table_blocks` / review_required 补丁逻辑

### 3.4 ExperimentOrchestrator 跨页合并
```python
def create_draft(self, request):
    pages = [self.document_processor.analyze_page(p) for p in request.image_paths]
    materials_catalog = self._merge_materials_catalog(pages)
    instruments_catalog = self._merge_instruments_catalog(pages)
    events = self._resolve_and_merge_events(pages, materials_catalog, instruments_catalog)
    return ExperimentRecord(
        materials_catalog=materials_catalog,
        instruments_catalog=instruments_catalog,
        events=events,
        pages=pages,
        ...
    )
```
- `_merge_materials_catalog`：按 `canonical_name` 去重，aliases 合并
- `_merge_instruments_catalog`：按 `(technique, instrument_label)` 去重
- `_resolve_and_merge_events`：解析 ref 的优先级是 **(1) canonical_name 精确匹配 → (2) aliases 列表匹配 → (3) unicode normalize 后匹配（"Mn₂O₃" ↔ "Mn2O3"）→ (4) 找不到时自动新增 catalog + 报 ReviewIssue("Material reference '<ref>' unresolved, auto-created")**。这避免 VLM 在 events 里写 alias 但 catalog 写 canonical 时被误判为新物质。
- events 全局排序：`date_iso` 优先，无则按 `(page_index, sequence_index)`
- **date_iso 推断责任**：prompt 不强求 VLM 推断 date_iso（避免幻觉）。orchestrator 在 catalog 解析阶段做 best-effort heuristic：识别 `M.D` 形如 `5.20` 的 token，套 `experiment_id.metadata` 或当前年份补全为 `YYYY-MM-DD`；推断失败则保留 `date_iso=None`，仅靠 date_label 排序。

### 3.5 TermAliaser 角色不变
继续把 `煅烧 / 烘干 / 水热` 等中文动词映射到 `action_type` 枚举。group_templates.example.json 不改格式。

### 3.6 错误处理
- VLM 返回 events 但漏 catalog → orchestrator 从 event.inputs/outputs 反推补 catalog
- VLM 返回 catalog 但无 events → 退化到旧 schema 路径（保留 materials_catalog，events=[]），自动 `review_required=True`
- VLM 完全失败 → 现有 `_parse_error` 兜底
- material_ref_local 找不到 canonical → 自动 add catalog + ReviewIssue("Material reference unresolved")

---

## 4. 可视化（HTML 模板升级）

### 4.1 时间轴布局
3 区，响应式（< 1100px 单列堆叠）：

```
┌─────────────── Header ───────────────┐
│ experiment_id · status · operator     │
│ counts: events / materials / instr.    │
└───────────────────────────────────────┘
┌ Materials ┐┌──── Timeline ────┐┌ Right ─┐
│ filters   ││ event card #1    ││ 原图    │
│ 🟡 prec.  ││ #2               ││ Issues │
│ 🟢 target ││ ...              ││ Q's    │
└───────────┘└──────────────────┘└────────┘
```

### 4.2 Event 卡片元素
- Header：`#seq · date_label · action_type · instrument_label` + confidence badge
- Body：`inputs → outputs` 表（chip 化物质名）
- Parameters：缩进列表（`temperature = 850 °C · 0.9`）
- Observations：bullets
- Footer 徽章：`failure_marker`（红）/ `equation`（代码框）/ `recipe_ratio`（紫）/ `target_phase`（绿）

### 4.3 交互
- 物质 chip hover → 弹出 Material 详情（aliases / chemical_formula / 该物质参与事件列表）
- Event 卡片点击 → 右侧原图滚到对应 page_ref 区域（V0 按 page；V2 加 bbox）
- Materials 侧栏点击 → 过滤时间轴
- 顶部"导出"按钮 → 一键 dump paper-table（materials.csv + protocol.md）

### 4.4 复用 reports/demo_DEMO-001_record.html 的视觉语言
保留现有 CSS 主题（青色 / 深色文字 / 浅灰背景），改重型组件：
- 卡片化 events 列表（替换原 steps 区块）
- Materials 改成可折叠 catalog（按 role 分组）
- 加 Right Pane 容纳原图缩略 + Review

---

## 5. 测试策略

### 5.1 单元测试（新增）
| 文件 | 关注点 |
|---|---|
| `tests/test_schemas.py` | Material / Instrument / ExperimentEvent / EventIO 默认值；`record.materials` property 派生正确；`record.steps` property 正确 |
| `tests/test_document_processor.py` | catalog 解析、events 解析（含 local refs）、七大 extracted_* 字段、空/缺字段兜底 |
| `tests/test_orchestrator_event_merge.py`（新） | materials_catalog 跨页去重、instruments_catalog 去重、events ref 解析、未识别 ref 自动 add+issue、event 全局排序 |
| `tests/test_term_aliaser.py`（已有） | action_type 中→英映射不变 |

### 5.2 集成测试
- 使用 `/tmp/batch_results/` 全量 50 张图，每张图能通过 `DocumentProcessor + Orchestrator` 完整重建 ExperimentRecord 不抛异常
- 跑 V1 prompt 在全量上的覆盖率：events / catalog 填充率 ≥ 90%

### 5.3 回归测试
现有 21 个 pytest 通过，依赖 `.materials / .steps / .observations` 的断言走兼容 property。

### 5.4 快照测试
选 3 张代表图（合成 + 表征 + 计算），固定完整 `ExperimentRecord.model_dump_json()` 为 snapshot 文件。schema 演化时检测回归。

---

## 6. 可扩展性（响应用户"后续会增加更多的图片"）

| 新场景 | 不动 schema 的扩展方式 |
|---|---|
| 新增图片 | 不需改 schema，events.parameters / metadata / observations 都是开放 dict/list |
| 未见过的 action_type | prompt 枚举里加；未列出走 `"other"`，description 保真 |
| 新仪器类型 | technique 用 `"other"` 兜底，model 字段保留原文 |
| 新物质 | 自动入 materials_catalog |
| 课题组自定义术语 | 改 `configs/group_templates.example.json` 的 term_aliases |
| 新边缘语义类（未来发现） | 新增 PagePacket.extracted_<new_kind>: list；event 上挂 metadata |

---

## 7. 迁移路径

| Phase | 内容 | 影响 |
|---|---|---|
| **0** (本轮) | 实现新 schema + 兼容 property，pytest 21 不变 | 零破坏；现有 API/CLI 行为不变 |
| **1** (依赖 batch + A/B) | finalize V1 prompt，新增 V2 fallback 切换逻辑，全量验证 | 改 prompts.py + vlm/client.py |
| **2** (新可视化) | HTML 模板升级到时间轴 | 改 render 脚本；reports/demo_*.html 模板升级 |
| **3** (未来) | 废弃 .materials / .steps / .observations property，caller 全切 .events | 需要 caller 同步升级；可能涉及 API 版本 v2 |

---

## 8. 风险与回退

| 风险 | 概率 | 回退方案 |
|---|---|---|
| V1 单次大 prompt 输出末尾"疲劳"漏字段 | 中（A/B 报告显示部分页 reasoning ratio 75%） | V2 fallback 自动触发；保留 V1/V2 双版本 prompt 用 env switch |
| 跨页 event 合并 sequence_index 排序错乱（date_iso 缺失） | 低 | 退化到 `(page_index, sequence_index)` 物理顺序 |
| `.materials / .steps` property 派生有性能成本 | 低 | 高频 caller 加 `@cached_property`，或 V3 阶段废弃旧字段 |
| Pillow downscale 仍然挡不住特定大图 timeout（agent 1 那张 2.98MB） | 已知 | vlm/client.py 加 try/except APITimeoutError → 退化为空 PagePacket + warnings（这是 P1 TODO） |
| canonical_name 化学式归一不完美（Mn₂O₃ vs Mn2O3） | 中 | 本轮按 unicode normalization 处理；化学式专用 alias 引擎留到 V2 |

---

## 9. 关联文件 / 输入产物

- `reports/prompt_ab_test_2026-05-13.md` — Prompt A/B 测试结论
- `reports/batch_extraction_summary_2026-05-13.md` — schema 覆盖度实证（55 张全量，44 ok）
- `reports/demo_DEMO-001_record.html` — V1 schema 的可视化效果（升级前基准）
- `reports/report_2026-05-13_vlm_structured_extraction.html` — V1 schema 上线的修改报告
- `code_modification_plan.html` — V1 schema 的设计方案（已落地）
- `test_results.html` — agent 1 的 5 张图测试结果

---

## 10. 待办（design 之外）

- [ ] batch_extract 跑完后，补 Section 1.4 / Section 9 的覆盖度摘要数据
- [ ] writing-plans skill 制定 Phase 0 详细实施计划
- [ ] Phase 0 实施后，跑现有 e2e 验证 DEMO-001 在新 schema 下行为不变
- [ ] Phase 1 实施后，把 V2 fallback 触发条件加 unit test

---

## 11. 用户授权记录

| 决策 | 用户选择 | 时间 |
|---|---|---|
| 摸底范围 | 全量 50 张 | 2026-05-13 |
| 扩展深度 | 事件中心模型（方案 C 重构） | 2026-05-13 |
| 主视图 | 时间轴主导 | 2026-05-13 |
| Sub-方案 | B · 事件 + 单实验内 catalog | 2026-05-13 |
| Section 1 数据模型 | OK | 2026-05-13 |
| Section 2 Pipeline | 改为 "测试拍板"（A/B 测试驱动）| 2026-05-13 |
| Section 3 可视化 | OK | 2026-05-13 |
