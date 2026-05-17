# Phase 2 用户端使用教程：干实验记录、查看与检索

## 你现在能做什么

Phase 2 用来把干实验数据从“散落在文件夹中的模拟文件”整理成可查看、可查询、可导出的结构化记录。

当前版本已经支持：

- 创建研究案例 `ResearchCase`；
- 导入 LAMMPS 模拟目录；
- 将湿实验记录与干实验记录关联；
- 查看案例、查看单次模拟；
- 按材料、任务类型、温度、PKA 能量、势函数等条件筛选；
- 导出查询结果为 CSV。

---

## 1. 数据到底存在哪里

### 系统内部存储位置

默认数据库位于：

```text
.local_data/extensions/drylab/drylab.db
```

这个文件是系统自己的 sidecar SQLite 数据库。

### 作为普通用户，你通常不需要直接打开数据库

你更应该使用命令行去查看和调用其中的数据：

- `list-cases`：看有哪些研究案例；
- `show-case`：看某个研究案例下面挂了什么；
- `query-runs`：按条件筛选模拟记录；
- `show-run`：查看某一次模拟的完整详情；
- `export-runs`：把筛选结果导出成 CSV。

---

## 2. 查看你当前已经保存的研究案例

```bash
python -m extensions.drylab.cli list-cases
```

你会看到类似：

```text
HEA-CASCADE-001   MoNbTaVW cascade study
W-CASCADE-001     W cascade study
HEA-TENSILE-001   NbTiZrMoV tensile study
```

并且还能看到每个案例下：

- 已关联多少条模拟记录；
- 已关联多少条湿实验记录。

---

## 3. 查看某个研究案例里到底有什么

```bash
python -m extensions.drylab.cli show-case \
  --case-id HEA-CASCADE-001
```

它会告诉你：

- 这个案例的标题和描述；
- 关联了哪些 `simulation_run`；
- 是否关联了某条 `wet_experiment`。

当前演示数据中，`HEA-CASCADE-001` 已经关联：

- 一个 HEA 位移级联模拟；
- 一个湿实验记录 `EXP-DEMO-001`。

这就是 Phase 2 中“湿实验 + 干实验统一记录”的体现。

---

## 4. 查看某一次模拟的完整详情

先通过查询找到 `run_id`：

```bash
python -m extensions.drylab.cli query-runs \
  --case-id HEA-CASCADE-001
```

然后查看完整详情：

```bash
python -m extensions.drylab.cli show-run \
  --run-id <你的 run_id>
```

你会看到：

- 模拟类型；
- 材料体系；
- 势函数；
- 温度；
- PKA 能量和方向；
- timestep；
- box size；
- 输入脚本、log、dump 等资产路径；
- 系统从输入文件中提取出的原始参数。

---

## 5. 按条件快速查找模拟数据

### 查所有位移级联模拟

```bash
python -m extensions.drylab.cli query-runs \
  --task-type cascade
```

### 查 300 K、150 keV 的级联模拟

```bash
python -m extensions.drylab.cli query-runs \
  --task-type cascade \
  --temperature-k 300 \
  --pka-energy-kev 150
```

### 查某个材料体系

```bash
python -m extensions.drylab.cli query-runs \
  --material-system MoNbTaVW
```

### 查某个研究案例下的所有模拟

```bash
python -m extensions.drylab.cli query-runs \
  --case-id HEA-CASCADE-001
```

---

## 6. 把已保存的数据拿出来继续用

如果你想把筛选结果拿去：

- Excel 汇总；
- 画图；
- 做参数对比；
- 后续分析脚本继续处理；

可以导出成 CSV：

```bash
python -m extensions.drylab.cli export-runs \
  --task-type cascade \
  --output .local_data/extensions/drylab/exports/cascade_runs.csv
```

导出的表格会包含：

- `run_id`
- `case_id`
- `task_type`
- `material_system`
- `potential_type`
- `temperature_k`
- `pka_energy_kev`
- `source_root`
- 等关键字段

这让 Phase 2 的数据不只是“被系统保存”，而是可以真正进入你的后续科研工作流。

---

## 7. 你现在已经保存了哪些真实数据

当前默认数据库中已经有三类真实示例：

| case_id | 含义 |
|---|---|
| `HEA-CASCADE-001` | `MoNbTaVW` 位移级联模拟 |
| `W-CASCADE-001` | 纯 W 位移级联模拟 |
| `HEA-TENSILE-001` | `NbTiZrMoV` 拉伸模拟 |

其中 `HEA-CASCADE-001` 已经能自动识别：

- `MoNbTaVW`
- `cascade`
- `mlip`
- `bcc`
- `300 K`
- `150 keV`
- `[0, 0, -1]`

---

## 8. 当前版本还需要你知道的边界

Phase 2 当前已经能很好支持典型 cascade 数据，但对不同风格脚本的识别还在第一版阶段：

- `include pot` 类型脚本暂时不会自动深入追读势函数文件；
- `read_data + pair_coeff` 风格暂时还不能总是自动识别材料体系；
- 晶界、拉伸等任务后续还值得增加更专门的模板。

这不影响你现在查看和使用已经存好的数据，但会影响未来自动导入的完整度。

---

## 9. 一句话理解 Phase 2

> Phase 2 的作用，是把原本散落在文件夹里的模拟数据，整理成可分类、可检索、可与湿实验关联、还能继续导出的结构化科研记录。
