# 材料科研实验记录智能处理框架

这个项目是一个面向材料科研实验记录的初始代码框架，用来承接：

- 实验记录本图片解析
- 用户补录信息结构化
- 仪器文件与导出报告解析
- 样品、步骤、仪器和表征结果对齐
- 课题组、仪器和实验流程的配置化定制

框架当前重点是把工程边界搭清楚：业务模型、VLM 客户端、解析流水线、仪器适配器、API 和 CLI 都已经预留好，后续可以逐步填充真实 OCR、仪器解析和审核界面。

## 快速开始

安装依赖：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

你的 `~/.zshrc` 中已经有 `DASHSCOPE_API_KEY`，新终端会自动读取。当前默认 VLM 模型配置为：

```bash
QWEN_VLM_MODEL=qwen3.6-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

启动 API：

```bash
uvicorn sci_data_logger.main:app --reload
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

API 创建草稿时，JSON 请求只接收实验元数据；实验记录图片和仪器文件需要走受控上传接口，服务会先把文件保存到 `SCI_DATA_LOGGER_STORAGE_ROOT` 下再交给流水线处理：

```bash
curl -X POST http://127.0.0.1:8000/experiments/draft/upload \
  -F experiment_id=EXP-001 \
  -F images=@/path/to/notebook-page.jpg \
  -F instrument_files=@/path/to/xrd-report.txt
```

CLI 生成草稿：

```bash
sci-data-logger draft \
  --experiment-id EXP-001 \
  --image /path/to/notebook-page.jpg \
  --instrument-file /path/to/xrd-report.txt
```

## 目录结构

```text
configs/                  # 仪器注册表、课题组模板示例
docs/                     # 架构说明
src/sci_data_logger/      # 核心代码
tests/                    # 基础测试
```

## 核心设计

系统把实验记录处理拆成几个独立能力：

- `DocumentProcessor`：把记录本图片或页面文本转成页面级结构化片段。
- `InstrumentService`：按仪器注册表选择适配器，抽取仪器参数和原始字段。
- `Normalizer`：做单位、术语和字段归一化。
- `ExperimentOrchestrator`：把页面、仪器文件和用户补录信息汇合成实验草稿。
- `QwenVLMClient`：封装 Qwen VLM 调用，业务代码不直接关心 API 细节。

第一版以“可配置、可扩展、可追溯”为优先目标，后续再逐步增强具体仪器和实验体系的解析能力。
