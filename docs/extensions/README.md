# Extensions

当前扩展层用于在不改动核心湿实验主干的前提下，逐步增加个性化和干实验能力。

> **给后续 AI agent：开始任何 `extensions/` 相关工作前，先完整阅读 [`extension_contract.md`](extension_contract.md)。**

## 湿实验个性化

```bash
python -m extensions.personalization.cli wizard --answers-json answers.json
python -m extensions.personalization.cli show-effective \
  --user-id fanjunran \
  --experiment-template solid_state_synthesis \
  --instrument-template generic_xrd
python -m extensions.personalization.cli parse \
  --input experiment_record.json \
  --user-id fanjunran \
  --experiment-template solid_state_synthesis \
  --instrument-template generic_xrd
```

- 共享模板放在 `extensions/personalization/templates/`。
- 本地覆盖配置写入 `.local_data/extensions/personalization/`。
- 配置合并顺序为：默认规则 → 课题组模板 → 实验模板 → 仪器模板 → 用户覆盖。

## 干实验 / LAMMPS 记录

```bash
python -m extensions.drylab.cli create-case \
  --case-id HEA-CASCADE-001 \
  --title "MoNbTaVW irradiation study"
python -m extensions.drylab.cli link-experiment \
  --case-id HEA-CASCADE-001 \
  --experiment-id EXP-001
python -m extensions.drylab.cli import-lammps \
  --source-root /path/to/lammps/run \
  --case-id HEA-CASCADE-001
python -m extensions.drylab.cli query-runs \
  --material-system MoNbTaVW \
  --task-type cascade
```

- 第一版支持 LAMMPS 输入脚本、`log.lammps`、`folder_name.csv` 和 dump 资产索引。
- 扩展数据库位于 `.local_data/extensions/drylab/drylab.db`。
- 湿实验与干实验通过 `ResearchCase` / `ResearchLink` 关联，不修改现有 `ExperimentRecord`。

## 个性化工作台

```bash
python -m extensions.workbench.cli serve
```

- 独立网页入口，默认地址为 `http://127.0.0.1:8015/workbench`。
- 首版只覆盖湿实验 + 个性化，不接入 drylab。
- 网页负责用户切换、记录上传、结果展示和个人 profile 基础编辑。
- 工作台仍然复用 `extensions/personalization/` 的规则能力，不修改主干代码。
