# 材料科研实验记录结构化与仪器异构接入调研报告

日期：2026-04-08  
面向对象：材料科研数据记录、实验记录本解析、仪器数据统一接入  
结论先行：如果目标是把“用户输入 + 实验记录本照片 + 多种仪器产出的文件/参数”统一沉淀为可检索、可分析、可追溯的结构化科研数据，最可行的路线不是单一 OCR，也不是单一 ELN，而是“文档智能 + 仪器适配器 + 统一语义模型 + 人工校核 + RDM/ELN 平台”的混合架构。

## 1. 执行摘要

这类系统真正的难点不在“把字识别出来”，而在以下五个层面同时成立：

1. 实验记录来源异构：手写记录本、拍照图片、Word/PDF、Excel、聊天式补录。
2. 仪器来源异构：XRD、SEM/TEM、XPS、Raman、FTIR、TGA/DSC、电化学工作站、BET 等设备各自输出不同文件和参数。
3. 术语表达异构：同一个参数会出现“升温速率/Heating rate/5 C min-1/5℃·min^-1”等多种写法。
4. 流程语义异构：材料实验往往不是单一步骤，而是“称量-混合-搅拌-干燥-煅烧-表征”的链式过程。
5. 证据链要求：需要保留原图、原始仪器文件、解析结果、修订历史和责任人，不能只有最后一份 JSON。

因此，推荐把系统拆成五层：

- 采集层：用户输入、OCR/手写识别、仪器文件上传、文件夹监控、API 接入。
- 解析层：版面分析、文字识别、文件解析、参数抽取、步骤抽取。
- 语义层：统一 schema、单位换算、术语映射、仪器注册表、样品/批次/步骤关系。
- 治理层：置信度、人工审核、审计追踪、版本管理、权限。
- 存储与服务层：对象存储保存原始文件，数据库保存结构化数据，搜索/统计/API 提供查询。

## 2. 用户问题的核心：不同仪器信息如何克服

### 2.1 “不同仪器”到底难在哪里

不同仪器带来的问题通常分成四类：

- 通信协议不同：有的仪器能远程控制，有的只能本地软件导出，有的只能导出截图或 PDF。
- 文件格式不同：CSV、TXT、XLSX、XML、HDF5、专有二进制、图片、PDF 混杂。
- 参数命名不同：同样是加速电压，可能写成 `Voltage`、`EHT`、`HV`、`Accelerating Voltage`。
- 语义粒度不同：有的仪器输出“完整采集方法 + 全部通道”，有的只给最终图谱图片。

这意味着不能指望“一个通用解析器”吃掉所有仪器。正确做法是：

1. 对每类仪器定义一个“最小可接受结构化模板”。
2. 每种设备或文件格式实现一个适配器。
3. 统一映射到实验平台内部的 canonical schema。
4. 永远保存原始文件，不以解析结果替代原始证据。

### 2.2 建议采用的统一建模策略

不要直接以“某台仪器导出的字段”作为数据库主结构，而要建立四层模型：

- `Technique`：技术类别，如 XRD、SEM、Raman、TGA。
- `Instrument`：具体设备，如厂家、型号、序列号、所在房间、负责人。
- `MeasurementRun`：某一次实际采集，包含样品、操作者、时间、方法快照。
- `DataAsset`：该次采集产生的原始文件、导出图、处理结果、解析元数据。

其中 `MeasurementRun` 建议至少包含：

- `run_id`
- `sample_id`
- `instrument_id`
- `technique`
- `operator`
- `start_time`
- `end_time`
- `method_name`
- `raw_parameters`
- `normalized_parameters`
- `raw_files`
- `derived_files`
- `provenance`

这里最关键的是同时保留两套参数：

- `raw_parameters`：按原始仪器字段原样保存。
- `normalized_parameters`：映射成统一字段，供检索、统计和跨仪器比较。

这样即使映射有误，也不会丢失原始证据。

## 3. 当前主流技术路线

### 3.1 路线 A：仅做 OCR/文档解析

适合：

- 实验记录主要依赖纸本、照片、扫描件。
- 仪器文件暂时拿不到。

优点：

- 起步最快。
- 对历史数据友好。

缺点：

- 很难稳定拿到完整仪器参数。
- 对手写、缩写、箭头批注、跨页信息很脆弱。
- 结果通常需要人工确认。

结论：
只能作为入口之一，不能成为整个科研数据平台的唯一数据来源。

### 3.2 路线 B：仅做 ELN/LIMS 表单化录入

适合：

- 新实验从零开始规范化。
- 团队愿意改变记录习惯。

优点：

- 数据质量高。
- 字段更稳定，后续统计和复现更容易。

缺点：

- 历史纸本数据无法解决。
- 用户录入负担重，容易降低使用意愿。

结论：
适合作为长期目标，但不适合单独解决现有纸本与图片问题。

### 3.3 路线 C：OCR/文件解析/人工输入混合

这是本报告推荐路线。

做法：

- 用户直接录入关键字段。
- 系统解析笔记照片补全步骤、观察现象、边角备注。
- 系统接收仪器原始文件或导出文件，自动提取测量参数。
- 最终通过审核界面统一校核入库。

优点：

- 兼容历史数据和新数据。
- 能逐步演进，不要求全组立刻改变工作方式。
- 最适合材料实验的复杂流程与多源数据形态。

### 3.4 路线 D：端到端视觉语言模型直接出 JSON

代表方向包括 Donut、PaddleOCR-VL、Chandra 一类模型。

优点：

- 对复杂页面有潜力。
- 可以减少传统 OCR + 规则的工程拼接。

缺点：

- 对真实实验本仍然需要领域标注与微调。
- 难以天然保证审计性和字段级置信度。
- 在术语、单位、仪器参数归一化上仍要靠后处理。

结论：
适合做增强模块，不适合第一版直接“一把梭”。

## 4. 文档智能与实验记录解析项目调研

### 4.1 PaddleOCR

官方仓库说明其目标是把 PDF/图片转为适合 AI 使用的结构化数据，并提供 `PP-StructureV3`、`PP-ChatOCRv4`、`PaddleOCR-VL` 等组件，覆盖文档解析、信息抽取与复杂元素识别。  
来源：[PaddleOCR GitHub](https://github.com/PaddlePaddle/PaddleOCR)

适用判断：

- 中文友好。
- 工程成熟度高。
- 适合作为第一版 OCR/结构化解析基线。

特别价值：

- 可以输出 JSON/Markdown。
- 有文档解析能力，不只是纯文本 OCR。
- 适合做“图片/PDF -> 初步结构块”的基础设施。

### 4.2 Surya

官方仓库说明其支持 OCR、版面分析、阅读顺序、表格识别和 LaTeX OCR。  
来源：[Surya GitHub](https://github.com/datalab-to/surya)

适用判断：

- 适合处理复杂版面。
- 可直接输出 bbox、标签、阅读顺序与置信度。

特别价值：

- 很适合作为“页面理解层”，把一页实验本切成文本块、表格块、公式块、手写块。

注意事项：

- 仓库说明其更偏文档 OCR，对真实拍照照片不一定是最佳起点，需要图像预处理。

### 4.3 Marker

官方仓库说明其可以把 PDF、图片等转为 Markdown/JSON/HTML，并支持基于 JSON schema 的结构化抽取，必要时可结合 LLM 提升质量。  
来源：[Marker GitHub](https://github.com/datalab-to/marker)

适用判断：

- 非常适合做“文档转结构化中间表示”。
- 如果你后面想做“按 schema 自动抽字段”，Marker 很值得试。

注意事项：

- 代码 GPL，模型权重也有额外许可条款，若未来考虑商业化需提前评估。

### 4.4 Chandra

官方仓库明确强调其支持复杂表格、表单、手写和完整版面输出，可导出 HTML/Markdown/JSON。  
来源：[Chandra GitHub](https://github.com/datalab-to/chandra)

适用判断：

- 对实验记录本这种“手写 + 表格 + 表单 + 勾选框 + 图示”的页面更贴近。
- 如果你的重点是“纸本照片解析”，它比很多纯 OCR 项目更值得优先测试。

### 4.5 Donut

Donut 是 OCR-free 文档理解模型，官方仓库说明它把任务统一成“图像到 JSON”的预测问题。  
来源：[Donut GitHub](https://github.com/clovaai/donut)

适用判断：

- 很适合研究“端到端图像转结构化”的思路。
- 如果你后面有自己实验本标注集，可以尝试微调。

现实判断：

- 第一版不建议直接押宝 Donut。
- 更适合第二阶段作为对照实验或增强模型。

## 5. 仪器控制、采集与异构接入项目调研

### 5.1 Bluesky + Ophyd

Bluesky 官方仓库强调“rich metadata”“procedure reuse on completely different hardware”“pluggable I/O”，非常适合做实验编排和元数据采集。  
来源：[Bluesky GitHub](https://github.com/bluesky/bluesky)

Ophyd 官方文档说明其提供硬件抽象层，把底层控制系统细节隐藏在 `trigger()`、`read()`、`set()` 这类高层接口之后。  
来源：[Ophyd 文档](https://blueskyproject.io/ophyd)

对你的价值：

- 如果未来要从“事后记录”升级到“实验执行时自动记数据”，这是极强的参考架构。
- 核心思想不是支持某个品牌，而是先抽象设备接口，再让不同硬件都实现同一语义接口。

这正是“克服不同仪器”的关键工程思想。

### 5.2 event-model

Bluesky 的 `event-model` 文档强调，目标是在采集数据的同时记录丰富元数据，并把数据组织为带 schema 的文档流。  
来源：[event-model 文档](https://blueskyproject.io/event-model/main/explanations/data-model.html)

对你的价值：

- 适合借鉴“实验运行是事件流，不是单个文件”的建模方式。
- 对多步骤实验、在线监测、参数变化过程记录特别有用。

### 5.3 QCoDeS

官方仓库将其定义为“modular data acquisition framework”，并指出它不是只能用于量子实验，而是适用于任何可由计算机控制、参数较多的系统。  
来源：[QCoDeS GitHub](https://github.com/microsoft/Qcodes)

对你的价值：

- 适合做可编程仪器驱动与测量脚本管理。
- 如果实验室里有大量 GPIB/串口/VISA 风格设备，它很有参考价值。

### 5.4 PyMeasure

官方文档说明其通过面向对象方式隐藏 SCPI/GPIB 等底层命令，并支持大量仪器类。  
来源：[PyMeasure 文档](https://pymeasure.readthedocs.io/en/latest/introduction.html)

对你的价值：

- 适合作为“遗留仪器 + Python 控制”的低门槛方案。
- 比较适合自建一些轻量采集与自动保存脚本。

## 6. 数据标准与语义互操作调研

### 6.1 SiLA 2：解决“设备通信”

SiLA 官方说明，SiLA 2 是实验室自动化通信标准，核心是让仪器、LIMS、ELN 等系统按统一方式通信；其架构基于 HTTP/2，并以“功能特征”而不是“设备类型”组织标准。  
来源：[SiLA 标准页](https://sila-standard.com/standards/)  
来源：[SiLA FAQ](https://sila-standard.com/faq/)

对你的价值：

- 它解决的是“怎么连设备、怎么调用服务”，不是“怎么存材料实验结果”。
- 如果你未来要对接机器人、自动进样器、条码枪、移液工作站等，SiLA 很重要。
- 但对现有大量老旧材料仪器，不一定能直接落地，因为很多设备本身并不支持。

判断：

- 适合做长期兼容目标。
- 不适合作为第一版统一所有仪器的唯一方案。

### 6.2 AnIML：解决“分析化学数据交换”

AnIML 官网说明它是 ASTM 的分析数据 XML 标准，由 core schema、technique schema 和 technique definition 组成，并允许厂商/机构扩展。  
来源：[AnIML 官网](https://www.animl.org/)

对你的价值：

- 适合存放分析仪器结果与上下文元数据。
- 思想上很值得借鉴：核心通用层 + 技术专用层 + 可扩展字段。

判断：

- 若你的仪器主要是分析化学类，AnIML 值得作为映射目标之一。
- 但生态没有 SiLA 和通用 Python 工具那么容易直接上手。

### 6.3 Allotrope：解决“企业级科学数据互联”

Allotrope 官方说明其数据格式建立在 HDF5 上，并用 RDF/linked data 表达过程、材料、仪器和结果元数据。  
来源：[Allotrope Framework](https://www.allotrope.org/allotrope-framework)

对你的价值：

- 它代表的是高成熟度工业方案思路：原始数据 + 仪器设置 + 过程上下文 + 语义链接一起存。
- 对你最值得借鉴的是“语义层和证据链”的设计思路。

判断：

- 非常适合作为架构理念参考。
- 但开源可实施性和社区易用性不如开源科研栈。

### 6.4 NeXus：解决“大型表征数据封装与交换”

NeXus 官网和论文说明，NeXus 建立在 HDF5 上，并附加领域特定规则与字典，用于中子、X 射线、μ 子等实验数据的组织和交换。  
来源：[NeXus 官网](https://www.nexusformat.org/)  
来源：[NeXus 论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC4453170/)

对你的价值：

- 如果你涉及衍射、同步辐射、散射、成像等大体量表征数据，NeXus 很重要。
- 它很适合作为“高维原始数据和复杂元数据”的长期容器标准。

### 6.5 JCAMP-DX：解决“谱图类数据交换”

IUPAC 维护的 JCAMP-DX 被官方仓库描述为光谱数据交换标准；相关综述指出它是最广泛使用的厂商无关光谱交换标准。  
来源：[IUPAC/JCAMP-DX GitHub](https://github.com/IUPAC/JCAMP-DX)  
来源：[JCAMP-DX 概述论文](https://pure.southwales.ac.uk/en/publications/an-overview-of-the-jcamp-dx-format/)

对你的价值：

- 对 FTIR、Raman、UV-Vis、NMR、MS 等谱图类数据尤其有用。
- 如果仪器能导出 JCAMP-DX，优先保存这类开放格式副本。

### 6.6 EMMO 与 QUDT：解决“术语和单位标准化”

EMMO 是材料科学本体，目标是支撑材料、过程、性质和数据的语义互操作。  
来源：[EMMO 官网](https://emmc.eu/emmo/)

QUDT 提供数量、单位、量纲和数据类型的统一建模。  
来源：[QUDT 官网](https://www.qudt.org/)

对你的价值：

- EMMO 适合做材料领域概念层。
- QUDT 适合做单位标准化和量纲约束。

判断：

- 第一版未必需要完整引入 RDF/OWL，但建议在字段设计时预留和这些本体对齐的能力。

## 7. RDM/ELN 平台调研

### 7.1 openBIS

ETH Zurich 官方页面将 openBIS 描述为集成式 ELN/LIMS/RDM 平台，可把实验、材料、方法和数据放在一个可追溯系统中。  
来源：[ETH Research Data Management Services](https://ethz.ch/staffnet/en/service/a-to-z/research-data/active-data-management/resources-for-ardm1.html)

Single Cell Facility 的官方页面说明 openBIS 可连接处理流水线，并通过 oBIT 从采集工作站半自动注册数据与元数据。  
来源：[Data Management – Single Cell Facility](https://bsse.ethz.ch/scf/data-management.html)  
来源：[openBIS Importer Toolset](https://bsse.ethz.ch/scf/data-management/obit.html)

对你的价值：

- openBIS 是当前最值得参考的“科研数据中台”之一。
- 它真正回答了“多仪器、多数据类型如何统一入库”的问题。

关键启发：

- 在采集工作站上做半自动注释与搬运。
- 服务端用插件注册数据。
- 元数据与原始文件分层管理。

### 7.2 NOMAD / NOMAD Oasis / FAIRmat

NOMAD 官方仓库将其定位为材料科学研究数据管理平台；NOMAD Oasis 官方页面明确写到：它支持自定义 schema、扩展 parsers，并可通过 API 或 NeXus 文件与仪器集成。  
来源：[NOMAD GitHub](https://github.com/nomad-coe/nomad)  
来源：[NOMAD Oasis 官方说明](https://fairmat-nfdi.eu/oasis-nomad-lab)  
来源：[NOMAD 官方站](https://nomad-lab.eu/nomad.html)

对你的价值：

- 如果你最终目标是材料领域 FAIR 数据、后续分析和共享，NOMAD 很强。
- 它特别适合“材料表征 + 合成 + 计算”一起管理。

关键启发：

- 使用可扩展 schema，而不是把所有东西硬编码进固定表结构。
- 支持 parsers，说明“按仪器/格式写适配器”是成熟路线。

### 7.3 eLabFTW

官方仓库说明 eLabFTW 提供实验记录、资源数据库、时间戳、导入导出和 REST API。  
来源：[eLabFTW GitHub](https://github.com/elabftw/elabftw)

对你的价值：

- 更像成熟的 ELN 前端和实验管理系统。
- 可以参考其审计、附件、REST API 和团队协作设计。

### 7.4 Chemotion 与 AI4Green

Chemotion 官方仓库定位为面向化学家的 ELN。  
来源：[Chemotion GitHub](https://github.com/ComPlat/chemotion_ELN)

AI4Green 官方仓库定位为强调绿色化学的 ELN。  
来源：[AI4Green GitHub](https://github.com/AI4Green/AI4Green)

对你的价值：

- 它们证明“实验步骤、化学对象、资源、反应/表征上下文”可以在 ELN 中结构化。
- 虽然偏化学，但对材料合成流程建模很有借鉴意义。

## 8. 材料实验场景下的推荐总体架构

### 8.1 核心原则

- 不是先做“大模型”，而是先做“统一 schema + 插件架构”。
- 不是只存结构化结果，而是“原始证据 + 解析结果 + 修订历史”同时保存。
- 不是要求所有仪器立刻统一，而是“先接入最常用的 3 到 5 类设备”。
- 不是只做 OCR，而是“用户输入、照片解析、仪器文件解析”三路合并。

### 8.2 推荐模块

1. `Experiment Intake`
   用户表单、图片上传、文件上传、样品绑定。

2. `Document Intelligence`
   页面预处理、版面分析、OCR/手写识别、文本块定位。

3. `Instrument Adapter Layer`
   每类仪器一个 adapter：
   - 文件观察器
   - 格式解析器
   - 原始参数提取
   - 标准字段映射

4. `Semantic Normalizer`
   做术语映射、单位换算、字段校验、材料名/仪器名对齐。

5. `Protocol/Step Extractor`
   把笔记文本变成步骤链：
   `weigh -> dissolve -> stir -> heat -> dry -> calcine -> characterize`

6. `Review UI`
   左边原图/原文件，右边解析字段，中间高亮证据，支持人工修订。

7. `RDM Core`
   对象存储存原始文件；关系型数据库存元数据与关系；检索索引做全文和结构化搜索。

### 8.3 建议的 canonical schema

建议至少有以下对象：

- `Project`
- `Experiment`
- `Sample`
- `MaterialInput`
- `ProtocolStep`
- `Instrument`
- `MeasurementRun`
- `DataAsset`
- `Observation`
- `DerivedResult`
- `AuditLog`

### 8.4 仪器异构的具体技术解法

#### 解法一：仪器注册表

为每台设备建立注册表，而不是让解析器直接面向“文件名猜测”。

建议字段：

- `instrument_id`
- `manufacturer`
- `model`
- `serial_number`
- `technique`
- `lab_location`
- `owner`
- `file_patterns`
- `parser_plugin`
- `normalization_profile`

#### 解法二：按“技术族”建标准模板

不要按单台设备定义数据库主表，而应先按技术类别定义模板。

例如：

- XRD 模板：
  `radiation`, `tube_voltage_kv`, `tube_current_ma`, `two_theta_start`, `two_theta_end`, `step_size_deg`, `scan_rate`

- SEM 模板：
  `accelerating_voltage_kv`, `magnification`, `working_distance_mm`, `detector`, `vacuum_mode`

- Raman 模板：
  `laser_wavelength_nm`, `laser_power`, `integration_time_s`, `accumulations`, `spectral_range_cm-1`

- TGA/DSC 模板：
  `sample_mass_mg`, `heating_rate_c_per_min`, `atmosphere`, `flow_rate`, `temperature_range`

通过“设备适配器 -> 技术模板”的映射，降低异构复杂度。

#### 解法三：保留原始字段与标准字段并存

示例：

- 原始字段：`EHT = 5.00 kV`
- 标准字段：`accelerating_voltage_kv = 5.0`

这样后续既能做统一查询，也能回溯原始仪器上下文。

#### 解法四：多级置信度

每个字段应记录来源和置信度：

- `source = user_input`
- `source = notebook_ocr`
- `source = instrument_file`
- `source = manual_review`

以及：

- `confidence_model`
- `confidence_rule`
- `review_status`

仪器文件直接解析得到的参数置信度通常最高；OCR 从照片推断的仪器参数只能作为候选。

#### 解法五：建立术语与单位映射表

建议建立以下字典：

- 仪器别名表：`Rigaku SmartLab = SmartLab = XRD-1`
- 技术别名表：`X-ray diffraction = XRD = powder XRD`
- 单位字典：`C/min`, `°C/min`, `K/min` 的归一规则
- 材料词典：化学式、中文名、英文名、缩写、多孔材料/氧化物/前驱体词汇

#### 解法六：优先接“可控格式”，不要一开始攻克所有专有文件

现实里很多仪器文件是私有二进制。第一阶段建议优先接以下几类：

- CSV/TXT/XLSX 导出
- XML/JSON 导出
- JCAMP-DX
- HDF5/NeXus
- 设备软件自动导出的 PDF 报告

对于专有二进制：

- 先原样保存
- 再要求导出开放格式副本
- 实在无法解析时，只抽取侧边 metadata 文件或报告文件

## 8.5 常见材料仪器的接入优先级与字段建议

这一节给出更落地的“第一版怎么接”的建议。原则是：

- 先接高频仪器。
- 先吃开放导出格式。
- 先提取最能支撑复现与比较的关键参数。

### XRD

推荐优先接入的数据来源：

- CSV/TXT 导出曲线
- PDF 报告
- 厂商软件导出的参数文件
- 若能得到 HDF5/NeXus 更好

建议提取的标准字段：

- `radiation`
- `tube_voltage_kv`
- `tube_current_ma`
- `two_theta_start_deg`
- `two_theta_end_deg`
- `step_size_deg`
- `scan_speed`
- `sample_stage`
- `scan_mode`

第一版策略：

- 先确保能绑定样品与曲线文件。
- 参数提取不足时，允许人工补录。
- PDF 报告中的参数可作为兜底来源，但置信度低于原始导出文件。

### SEM / TEM

推荐优先接入的数据来源：

- 图像文件及其 sidecar metadata
- 厂商软件导出的 CSV/TXT/XML
- PDF 报告

建议提取的标准字段：

- `accelerating_voltage_kv`
- `magnification`
- `working_distance_mm`
- `detector`
- `vacuum_mode`
- `beam_current`
- `spot_size`
- `image_resolution`

第一版策略：

- 先提图像级元数据和采集参数。
- 对图像上的嵌入式标尺和电压角标做 OCR，仅作为补充，不作为唯一来源。

### Raman / FTIR / UV-Vis

推荐优先接入的数据来源：

- JCAMP-DX
- CSV/TXT 导出
- PDF 报告

建议提取的标准字段：

- `laser_wavelength_nm`
- `laser_power`
- `integration_time_s`
- `accumulations`
- `spectral_range`
- `resolution`
- `background_correction`

第一版策略：

- 如果能导出 JCAMP-DX，优先保存。
- 谱图本身与采集参数要分开存，但通过同一个 `MeasurementRun` 关联。

### XPS

推荐优先接入的数据来源：

- 导出表格
- 峰拟合结果文件
- PDF 报告

建议提取的标准字段：

- `xray_source`
- `pass_energy`
- `spot_size`
- `charge_neutralization`
- `binding_energy_reference`
- `survey_or_high_resolution`

第一版策略：

- 先抓 survey scan 与 high-resolution scan 的区分。
- 峰拟合结果与原始谱图分开记录，避免把处理结果误当原始数据。

### TGA / DSC

推荐优先接入的数据来源：

- CSV/TXT 导出
- PDF 报告

建议提取的标准字段：

- `sample_mass_mg`
- `temperature_start_c`
- `temperature_end_c`
- `heating_rate_c_per_min`
- `atmosphere`
- `gas_flow_rate`
- `crucible_type`

第一版策略：

- 温度程序和气氛是最关键字段，必须标准化。
- 对“多段程序”要支持数组结构，而不是只有单一升温段。

### 电化学工作站

推荐优先接入的数据来源：

- CSV/TXT 导出
- 方法文件
- PDF 报告

建议提取的标准字段：

- `measurement_mode`
- `electrode_setup`
- `electrolyte`
- `scan_rate`
- `potential_window`
- `current_range`
- `cycle_count`
- `temperature`

第一版策略：

- 必须记录测试模式，如 CV、GCD、EIS、CA、CP。
- 同一设备下不同模式的字段差异很大，建议“模式子模板”而不是只有一个总模板。

### BET / 吸脱附

推荐优先接入的数据来源：

- 文本导出
- PDF 报告

建议提取的标准字段：

- `adsorbate`
- `degas_temperature_c`
- `degas_time_h`
- `analysis_temperature`
- `surface_area_m2_per_g`
- `pore_volume_cm3_per_g`
- `pore_size_nm`

第一版策略：

- 首先把前处理条件和最终比表面积抓出来。
- 对孔径分布曲线先保存原始文件，不急于第一版做深度语义解析。

### 这一节的实际含义

所谓“克服不同仪器”，在工程上并不是要把所有设备变成一个样子，而是做到：

- 同类技术有统一查询字段。
- 异类技术保留各自特有参数。
- 所有解析结果都能追溯到原始文件。
- 后续增加新仪器时，只需新增 adapter，不需要重写整套数据库。

## 9. 推荐实施路线

### 阶段 0：定义 schema 与词表

先不写模型，先把以下东西定下来：

- 你们实验最常见的 20 到 40 个字段
- 最常见的 5 到 10 类仪器
- 最常见的 30 到 50 个动作词
- 最常见的单位与术语别名

### 阶段 1：最小可用 POC

目标：

- 用户可上传实验本照片和仪器文件
- 系统能抽出步骤链和基础参数
- 支持人工校改后保存

技术建议：

- OCR/文档：PaddleOCR 或 Chandra
- 页面理解：Surya
- 结构化抽取：LLM + 固定 JSON schema
- 存储：PostgreSQL + 对象存储

### 阶段 2：接入 3 到 5 类高频仪器

优先顺序建议：

1. XRD
2. SEM/TEM
3. Raman/FTIR
4. TGA/DSC
5. 电化学工作站

理由：

- 这些设备在材料实验中最常见。
- 参数结构比较典型，足够验证统一模板方法。

### 阶段 3：构建审核与质量控制

加入：

- 字段高亮证据
- 单位异常告警
- 参数缺失提醒
- 样品-表征关联检查
- 原始文件与实验步骤一致性检查

### 阶段 4：走向自动化采集

如果实验室具备条件，再逐步引入：

- 文件夹监控
- 采集站自动上传
- 仪器 API/SDK
- Bluesky/QCoDeS/PyMeasure 控制脚本
- SiLA 2 兼容服务

## 10. 风险与现实判断

### 10.1 不要高估 OCR 对仪器参数的可靠性

从实验本照片中推断“用了哪台仪器、什么参数”很容易错，尤其是：

- 只写缩写
- 只写“同上”
- 参数跨页
- 后补手写修改

所以：

- 笔记解析适合补充流程信息和观察信息。
- 仪器参数应尽量来自原始文件或导出文件。

### 10.2 不要一开始就追求全自动

真实可行目标应是：

- 结构化自动抽取覆盖 70% 到 85%
- 剩余由人工 1 到 3 分钟完成审核

这比追求端到端 100% 自动更能落地。

### 10.3 不要把数据库设计成“只适合当前三台仪器”

如果把表写死成：

- `xrd_start_angle`
- `sem_voltage`
- `raman_laser`

后面系统会越来越难扩展。

正确方法是：

- 通用实体 + 技术模板 + JSON 扩展字段 + 标准映射。

## 11. 最终建议

对你这个项目，最合理的路线不是“先做一个强 OCR”，而是：

1. 先定材料实验 canonical schema。
2. 搭一个混合采集系统：
   - 用户表单
   - 实验本照片解析
   - 仪器文件上传
3. 按技术类别做适配器，不按单台仪器写死。
4. 优先把原始文件和标准化字段同时入库。
5. 通过审核界面闭环，不追求第一版全自动。
6. 后续再逐步接采集站自动上传、Bluesky/QCoDeS/PyMeasure、SiLA 2 等更深层自动化。

如果只给一个最核心的判断：

> 克服不同仪器的关键，不是找到一个万能模型，而是建立“统一语义模型 + 仪器注册表 + 适配器插件 + 原始证据保留 + 人工审核”的体系。

## 12. 本次调研参考来源

- PaddleOCR: https://github.com/PaddlePaddle/PaddleOCR
- Marker: https://github.com/datalab-to/marker
- Chandra: https://github.com/datalab-to/chandra
- Surya: https://github.com/datalab-to/surya
- Donut: https://github.com/clovaai/donut
- Bluesky: https://github.com/bluesky/bluesky
- Ophyd: https://blueskyproject.io/ophyd
- event-model: https://blueskyproject.io/event-model/main/explanations/data-model.html
- QCoDeS: https://github.com/microsoft/Qcodes
- PyMeasure: https://pymeasure.readthedocs.io/en/latest/introduction.html
- LabOP: https://bioprotocols.github.io/labop/
- SiLA 2: https://sila-standard.com/standards/
- AnIML: https://www.animl.org/
- Allotrope Framework: https://www.allotrope.org/allotrope-framework
- NeXus: https://www.nexusformat.org/
- JCAMP-DX: https://github.com/IUPAC/JCAMP-DX
- openBIS / ETH RDM: https://ethz.ch/staffnet/en/service/a-to-z/research-data/active-data-management/resources-for-ardm1.html
- openBIS Importer Toolset: https://bsse.ethz.ch/scf/data-management/obit.html
- NOMAD GitHub: https://github.com/nomad-coe/nomad
- NOMAD Oasis: https://fairmat-nfdi.eu/oasis-nomad-lab
- eLabFTW: https://github.com/elabftw/elabftw
- Chemotion ELN: https://github.com/ComPlat/chemotion_ELN
- AI4Green: https://github.com/AI4Green/AI4Green
- EMMO: https://emmc.eu/emmo/
- QUDT: https://www.qudt.org/
- ChemDataExtractor 2: https://github.com/CambridgeMolecularEngineering/chemdataextractor2
- 材料领域 LLM 信息抽取论文: https://www.nature.com/articles/s41467-024-45563-x
