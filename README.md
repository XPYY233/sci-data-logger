# Sci Data Logger · 材料科研实验记录智能处理框架

一个把**手写实验本图片 / 扫描 PDF / 仪器文件 / 用户补录信息**汇合成结构化、可审核、可入库实验记录的科研记录框架。

当前仓库已经在最初的湿实验主干之上，进一步演进出一层**外挂式扩展架构**：

- 主干继续负责湿实验解析、时间线重建、审核与入库；
- `extensions/personalization/` 负责不同用户、实验类型与仪器习惯的个性化规则；
- `extensions/drylab/` 负责 LAMMPS 等干实验记录、研究案例与湿实验关联；
- `extensions/workbench/` 提供独立网页入口，把个性化能力变成组员可直接使用的日常工作台。

这意味着项目当前的目标，已经从“处理一份湿实验记录”扩展为：

> **在保持核心稳定的前提下，逐步形成可服务不同研究者、不同实验范式的科研记录平台。**

> **给后续 AI agent 的必读入口**：进入仓库后先读 [`AGENTS.md`](AGENTS.md)；如果你要新增、修改或评审任何外挂能力，再继续阅读 [`docs/extensions/extension_contract.md`](docs/extensions/extension_contract.md)。

```
┌──────────────────┐    ┌──────────────────┐    ┌─────────────────────┐
│  Notebook image  │ ─► │ Qwen-VL (retry)  │ ─► │  PagePacket (JSON)  │
│  Scanned PDF     │    │ deskew/autocon-  │    │  text / tables /    │
│  Instrument file │    │ trast preproc.   │    │  materials / events │
└──────────────────┘    └──────────────────┘    └──────────┬──────────┘
                                                           ▼
                              ┌────────────────────────────────────┐
                              │   ExperimentOrchestrator           │
                              │   - 跨页 catalog 合并 + reconcile  │
                              │   - 事件本地引用解析 → 全局排序    │
                              │   - 日期推断（不再 fallback now()） │
                              └──────────────┬─────────────────────┘
                                             ▼
                              ┌────────────────────────────────────┐
                              │   SQLite (SQLModel hybrid)         │
                              │   CRUD + review API                │
                              └────────────────────────────────────┘
```

设计取向：**可配置 / 可扩展 / 可追溯 / 主干冻结、外挂优先**。每个抽取出的字段都带 `EvidenceRef`（指向原图位置 + 置信度），低置信度自动进入 `review_issues`，等待人工复核；新增能力优先以独立扩展交付，避免多人并行开发时互相干扰。完整分层说明见 [`docs/architecture.md`](docs/architecture.md)。

---

## 功能

### 当前扩展层（本轮新增重点）

| 扩展 | 作用 | 当前能力 |
|---|---|---|
| **湿实验个性化** | 让系统适配不同用户、实验类型与仪器习惯 | 用户 profile、实验模板、仪器模板、共享模板 + 本地覆盖、术语归一、个性化 review issues |
| **干实验 / LAMMPS** | 把模拟研究纳入统一科研记录体系 | `ResearchCase`、`SimulationRun`、LAMMPS 目录导入、湿干实验关联、查询与 CSV 导出 |
| **个性化工作台** | 把个性化能力变成可直接使用的网页入口 | 用户切换、记录上传、模板选择、结果解释、个人 profile 基础编辑 |

### 当前架构分层

```text
┌──────────────────────────────────────────────────────────────┐
│ extensions/workbench/                                        │
│ 面向用户的网页入口：用户切换、上传、结果解释、规则编辑        │
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────┐
│ extensions/personalization/   extensions/drylab/              │
│ 个性化规则层                  干实验记录与研究关联层          │
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────┐
│ src/sci_data_logger/                                         │
│ 冻结主干：湿实验解析、编排、审核、SQLite / API                │
└──────────────────────────────────────────────────────────────┘
```

### 识别（input → PagePacket）

| 能力 | 说明 |
|---|---|
| **Qwen-VL 视觉抽取** | 单次调用产出页面类型、样品号、materials、events（含输入/输出物料和参数）、observations、表格、公式、配方比例、日期、batch 标签等结构化字段；prompt 见 [`src/sci_data_logger/prompts.py`](src/sci_data_logger/prompts.py) |
| **PDF 自动拆页** | 通过 `pypdfium2` 渲染每页为图，独立解析，每页 source_path 标注 `#page=N` |
| **图像预处理** | 纯 Pillow 实现 autocontrast + 投影方差 deskew（角度网格搜索 ±8°, 0.5° 步长），不依赖 OpenCV |
| **VLM 调用容错** | `tenacity` 退避重试：仅对 `RateLimitError / APITimeoutError / APIConnectionError / InternalServerError` 重试；`BadRequestError / AuthenticationError` 直接抛出（属配置错） |
| **并发派发** | `ThreadPoolExecutor` 并发跑多文件，默认 4 worker，可调（`SCI_DATA_LOGGER_VLM_CONCURRENCY`），保持顺序 |
| **图片自动压缩** | 超过阈值的图先 Pillow 降到 max_side 1600 + JPEG quality 88 再 base64，避免命中 API 上限 |
| **仪器文件适配** | `generic_csv` / `generic_text_report` 两个内置适配器；新仪器只需在 `configs/instruments.example.json` 注册一条 profile（含 `file_patterns` / `field_mappings`） |
| **术语别名归一** | 课题组级 `term_aliases`（如「煅烧 → calcine」「水热 → hydrothermal」）+ `common_step_types`，配置在 `configs/group_templates.example.json` |
| **日期推断** | M/D 类标签（如 `5.20`）会在全文 YMD 标签里推断年份，而非默认 `datetime.now().year` —— 避免跨年份本子被误标 |
| **Evidence ref 全程留痕** | 每个 FieldValue / Material / Event 都附 source_path、locator、confidence，审核 UI 可点击回原图 |

### 入库（PagePacket → DB → API）

| 能力 | 说明 |
|---|---|
| **混合存储** | 单表 `experiments`：scalar 列（experiment_id / project / group / status / timestamps）+ `record_json` blob（完整 pydantic `ExperimentRecord`）。SQLite JSON1 足以应付当前查询 |
| **Schema 演化友好** | pydantic v2 model 是单一权威，DB 不预先 normalize，避免 Phase 0/1 阶段反复改表 |
| **CRUD + 审核 API** | `GET/PATCH/DELETE /experiments/{id}`、`GET /experiments?status=...`、`POST /experiments/{id}/review-issues/{issue_id}/resolve` |
| **审核状态机** | `ReviewStatus`：`draft → needs_review → reviewed → locked`（注意：当前 PATCH 还没强制状态迁移合法性，见下方“已知局限”） |
| **Material 跨页合并** | dedup key 仅用 `canonical_name`（不再带 role），同一物质多 role 累计到 `roles: list[str]`；event 解析中 auto-create 的 stub 会被 reconcile pass 合并回真实条目 |

---

## 快速开始

### 安装

```bash
git clone https://github.com/<your-org>/sci-data-logger.git
cd sci-data-logger
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 配置

复制 `.env.example` → `.env`，填入 DashScope key：

```bash
DASHSCOPE_API_KEY=sk-...
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_VLM_MODEL=qwen3-vl-plus      # 或者你账号可用的视觉模型 ID
```

可选 tuning（全部有合理默认值，详见 [`src/sci_data_logger/config.py`](src/sci_data_logger/config.py)）：

```bash
# 重试
QWEN_MAX_RETRIES=3
QWEN_RETRY_BASE_DELAY=1.0
QWEN_RETRY_MAX_DELAY=20.0

# 并发与预处理
SCI_DATA_LOGGER_VLM_CONCURRENCY=4
SCI_DATA_LOGGER_IMAGE_AUTOCONTRAST=true
SCI_DATA_LOGGER_IMAGE_DESKEW=true
SCI_DATA_LOGGER_PDF_RENDER_DPI=200

# 存储 / 配置文件路径
SCI_DATA_LOGGER_STORAGE_ROOT=.local_data
SCI_DATA_LOGGER_INSTRUMENT_REGISTRY=configs/instruments.example.json
SCI_DATA_LOGGER_GROUP_TEMPLATE=configs/group_templates.example.json
```

### 启动

```bash
uvicorn sci_data_logger.main:app --reload
curl http://127.0.0.1:8000/health
```

### 启动个性化工作台（外挂）

```bash
python -m extensions.workbench.cli serve
```

打开：

```text
http://127.0.0.1:8015/workbench
```

工作台首版支持：

- 共享电脑上的用户切换；
- 上传湿实验记录；
- 选择课题组 / 实验 / 仪器模板；
- 查看个性化术语归一、缺失字段和补充建议；
- 维护个人 profile 的基础规则。

### 扩展命令示例

```bash
# 1. 创建 / 更新湿实验个性化配置
python -m extensions.personalization.cli wizard \
  --answers-json .local_data/extensions/personalization/fanjunran_phase1_answers.json

# 2. 查看当前真正生效的个性化规则
python -m extensions.personalization.cli show-effective \
  --user-id fanjunran \
  --experiment-template solid_state_synthesis \
  --instrument-template generic_xrd

# 3. 导入一组 LAMMPS 模拟目录
python -m extensions.drylab.cli import-lammps \
  --source-root /path/to/lammps/run \
  --case-id HEA-CASCADE-001
```

### 一次完整调用

```bash
# 1. 上传图片 / PDF / 仪器文件 → 创建草稿（会自动持久化到 SQLite）
curl -X POST http://127.0.0.1:8000/experiments/draft/upload \
  -F experiment_id=EXP-001 \
  -F images=@/path/to/notebook-page1.jpg \
  -F images=@/path/to/scanned-notebook.pdf \
  -F instrument_files=@/path/to/xrd-report.txt \
  -F operator=yinliang \
  -F project_id=NaMnO-2026

# 2. 列出实验
curl 'http://127.0.0.1:8000/experiments?project_id=NaMnO-2026'

# 3. 取回完整草稿
curl http://127.0.0.1:8000/experiments/EXP-001

# 4. 解决某个 review issue
curl -X POST http://127.0.0.1:8000/experiments/EXP-001/review-issues/issue_xxx/resolve

# 5. 推进审核状态
curl -X PATCH http://127.0.0.1:8000/experiments/EXP-001/status \
  -H "Content-Type: application/json" \
  -d '{"status":"reviewed"}'
```

CLI 等价：

```bash
sci-data-logger draft \
  --experiment-id EXP-001 \
  --image /path/to/notebook-page1.jpg \
  --image /path/to/scanned-notebook.pdf \
  --instrument-file /path/to/xrd-report.txt \
  --operator yinliang \
  --project-id NaMnO-2026
```

---

## 目录结构

```
configs/
  instruments.example.json      仪器注册表（profile + 字段映射）
  group_templates.example.json  课题组术语别名 / 必填字段规则

docs/
  architecture.md               当前 core + extensions 分层架构说明
  extensions/                   外挂契约、协作规范 + Phase 1 / 1.5 / 2 用户指南
  superpowers/                  Phase 0/1 设计 spec & plan

AGENTS.md                       给后续 AI agent 的仓库级入口说明

src/sci_data_logger/
  api/routes.py                 FastAPI 路由：draft 创建 + CRUD + review
  cli.py                        Typer CLI（doctor / draft）
  config.py                     pydantic-settings；env 全部以 SCI_DATA_LOGGER_* / QWEN_* / DASHSCOPE_* 为前缀
  main.py                       FastAPI app 工厂（lifespan 启动建表）
  prompts.py                    Qwen-VL 抽取 prompt（含 JSON schema、示例、规则）
  schemas.py                    pydantic 模型：PagePacket / ExperimentRecord / Material / ExperimentEvent / EvidenceRef / FieldValue / ReviewIssue …
  adapters/                     仪器文件适配器（generic_csv, generic_text_report）+ Protocol
  db/                           SQLModel ORM + session + repository（hybrid JSON 存储）
  services/
    document.py                 DocumentProcessor：image/PDF/text → PagePacket（含 PDF 拆页、预处理）
    instrument.py               InstrumentService：profile 匹配 + adapter 选择
    normalizer.py               raw_parameters → normalized_parameters（按 profile.field_mappings）
    term_aliaser.py             课题组中文术语归一
    orchestrator.py             ExperimentOrchestrator：并发派发、catalog 合并、事件解析、reconcile
  utils/
    date_heuristics.py          label_to_iso / infer_default_year
    image_preprocessing.py      纯 Pillow autocontrast + deskew
    json_tools.py               从 VLM 自由文本里抠出第一个 JSON 对象
  vlm/client.py                 QwenVLMClient（tenacity 重试 + 图像降采样）

extensions/
  personalization/              湿实验个性化规则、模板、sidecar DB 与 CLI
  drylab/                       干实验 / LAMMPS 记录与研究案例关联
  workbench/                    独立网页工作台，不改主干即可运行

tests/                          96 个测试用例（pytest）
  test_data/                    实验本样本图（私库专用）
  ...
```

---

## 模型与数据流

### 核心 pydantic 模型

- **PagePacket**：单页解析结果。包含 `text_blocks`、`table_blocks`、`extracted_materials`、`extracted_events`、`extracted_facts`、`open_questions`、`warnings`、`review_required`、`evidence_refs`、`raw_model_output` 等。
- **ExperimentEvent**：实验时间线原子单元。`inputs/outputs: list[EventIO]`（引用 `material_id`）、`parameters: dict[str, FieldValue]`、`date_label/date_iso`、`instrument_ref`、`recipe_ratio`、`equation`、`observations`、`page_ref`、`evidence_refs`、`confidence`。
- **Material** (catalog) / **Instrument** (catalog)：跨页去重后的目录条目。
- **FieldValue**：`{value, unit, source_refs, confidence, reviewed}`，是所有可量化字段的统一容器。
- **EvidenceRef**：`{source_type, source_id, locator, text, confidence}`，每个字段都有来源指针。
- **ReviewIssue**：审核工单条目（severity / title / detail / evidence_refs）。
- **ExperimentRecord**：顶层草稿。聚合 `materials_catalog`、`instruments_catalog`、`events`、`pages`、`measurements`、`review_issues`、`source_assets`、`status`、`metadata`。

### Orchestrator 处理流程

```
DraftExperimentRequest
  │
  ├─► (并发) analyze_pages × N files            # PDF 拆页 + 图像预处理 + Qwen-VL
  │     └─ list[PagePacket]
  │
  ├─► InstrumentService.parse_file × M files    # 仪器文件适配
  │     └─ list[MeasurementPacket]
  │
  ├─► _merge_materials_catalog                  # 跨页 Material 去重，roles 累加
  ├─► _merge_instruments_catalog                # 跨页 Instrument 去重
  │
  ├─► _resolve_and_merge_events
  │     ├─ 推断 default_year（全文 YMD 标签）
  │     ├─ 逐事件解析 inputs/outputs ref → material_id（auto-create stub 若未匹配）
  │     ├─ instrument_ref 解析
  │     ├─ label_to_iso(date_label, default_year)
  │     ├─ 全局排序：date_iso → page_idx → page-local sequence_index
  │     └─ reconcile pass：stub 物料合并回真实条目，重写所有 event ref
  │
  ├─► _basic_review                             # 生成 review_issues
  │
  └─► repository.save_record                    # upsert to SQLite
        └─ ExperimentRecord 序列化为 record_json blob
```

### 仪器文件解析约定

1. `InstrumentService.match_profile(path)` 按 `display_name / aliases / file_patterns` 在 [`configs/instruments.example.json`](configs/instruments.example.json) 里挑 profile。
2. 选适配器：profile 指定 `parser_plugin`，缺省走 `GenericCSVAdapter` / `GenericTextReportAdapter`。
3. `adapter.parse` 抽出 `raw_parameters`；`Normalizer` 按 `profile.field_mappings` 转 `normalized_parameters: dict[str, FieldValue]`，附 evidence ref。
4. 新仪器：先在 profile 里加 `field_mappings`，无法解析时再写新 adapter（实现 `InstrumentAdapter` Protocol）。

---

## API 参考

| Method | Path | 说明 |
|---|---|---|
| GET | `/health` | 健康检查；返回模型 / DashScope 配置状态 |
| GET | `/runtime/config` | 当前运行时配置（不含 secret） |
| POST | `/experiments/draft` | 仅 JSON 元数据创建空草稿（用于先建实验再后续补传文件） |
| POST | `/experiments/draft/upload` | multipart：上传图片 + 仪器文件 + 字段，直接落库 |
| GET | `/experiments` | 列表，支持 `project_id / group_id / status / limit / offset` |
| GET | `/experiments/{id}` | 完整草稿 |
| PATCH | `/experiments/{id}/status` | 推进审核状态（`{"status": "..."}`） |
| POST | `/experiments/{id}/review-issues/{issue_id}/resolve` | 标记某个 issue 已解决 |
| DELETE | `/experiments/{id}` | 删除（私库内审慎使用） |

---

## 开发

### 运行测试

```bash
python -m pytest tests/ -q
# 96 passed
```

### 代码质量

```bash
ruff check src tests
```

### 加新仪器适配器

```python
# src/sci_data_logger/adapters/my_xrd.py
from sci_data_logger.adapters.base import AdapterResult, InstrumentAdapter

class MyXRDAdapter:
    plugin_name = "my_xrd"
    def supports(self, path, profile=None) -> bool: ...
    def parse(self, path, profile=None) -> AdapterResult: ...
```

注册到 `InstrumentService.adapters` 列表，profile 的 `parser_plugin` 指过来即可。

---

## 已知局限（路线图）

| 优先级 | 项 | 说明 |
|---|---|---|
| High | 审核状态机校验 | `PATCH /status` 当前只校验枚举值，未禁止 `locked → draft` 等回滚 |
| High | Retry × 线程池整体超时 | `tenacity` 仅按 attempt 数停，没整体 wallclock 上限；高错误率时单请求可能挂数分钟 |
| High | PDF 单页失败容错 | 当前一页 render 异常会拖垮整本 PDF，应改成 per-page try/except |
| Medium | 上传扩展名白名单 | `/experiments/draft/upload` 任何 mimetype 都会落盘 |
| Medium | Alembic 迁移 | 当前 `init_db` 用 `create_all`，schema 演进时需要正式迁移 |
| Medium | Engine dispose | `lru_cache` 持有 SQLite engine，生产路径无清理路径 |

详细 review 报告（私密）参见 `reports/`（已 gitignore）。

---

## 外挂协作策略

当前仓库采用：

> **主干冻结、外挂优先、兼容优先**

### 原则

- 默认不修改 `src/sci_data_logger/` 下的核心主干；
- 新功能优先放入 `extensions/<domain>/`；
- 每个扩展尽量自带：
  - 自己的 CLI / Web 入口；
  - 自己的模板与配置；
  - 自己的 sidecar 数据；
  - 自己的测试与文档；
- 与主项目交互时，优先通过已有对象 ID、公开服务或文件边界建立松耦合关系。

### 为什么这样做

这种方式让不同人、不同 AI agent 可以并行推进：

- 有人继续优化湿实验主干；
- 有人扩充个性化规则；
- 有人做干实验；
- 有人做更友好的 UI；

而不会因为频繁修改同一批核心文件产生高耦合冲突。

更多细节见：

- [`AGENTS.md`](AGENTS.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/extensions/extension_contract.md`](docs/extensions/extension_contract.md)
- [`docs/extensions/collaboration_guidelines.md`](docs/extensions/collaboration_guidelines.md)
- [`docs/extensions/README.md`](docs/extensions/README.md)
- [`docs/extensions/phase1_5_workbench_user_guide.md`](docs/extensions/phase1_5_workbench_user_guide.md)

---

## 许可

未指定 —— 这是一个内部研究项目。引用 / 公开使用前请联系作者。
