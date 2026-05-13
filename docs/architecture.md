# 系统架构说明

本框架采用“采集、解析、语义归一、流程重建、审核”的分层结构。第一版重点是把模块边界搭清楚，让后续可以逐步接入真实实验本图片、仪器文件和课题组模板。

## 数据流

1. 用户上传实验记录本图片、文本页或仪器文件。
2. `DocumentProcessor` 将页面转换为 `PagePacket`。
3. `InstrumentService` 根据仪器注册表匹配设备，并选择适配器生成 `MeasurementPacket`。
4. `Normalizer` 将原始仪器字段映射为统一字段。
5. `ExperimentOrchestrator` 汇合页面、测量和用户补录信息，生成 `ExperimentRecord` 草稿。
6. 后续审核界面可以基于 `review_issues` 和 `evidence_refs` 做人工确认。

## 关键对象

- `PagePacket`：页面级解析结果，保留文本块、表格块、事实和不确定问题。
- `MeasurementPacket`：仪器文件级解析结果，保留原始参数和标准化参数。
- `ExperimentRecord`：实验草稿主对象，关联页面、测量、样品、步骤和审核问题。
- `InstrumentProfile`：仪器注册表条目，描述仪器别名、文件模式、解析器和字段映射。

## 扩展方式

新增仪器时，优先新增或修改 `configs/instruments.example.json`。如果现有通用 CSV 或文本报告适配器无法解析，再在 `src/sci_data_logger/adapters/` 中增加新的适配器。

新增课题组时，优先增加组级模板、术语别名和必填字段规则。业务逻辑保持统一，差异通过配置吸收。
