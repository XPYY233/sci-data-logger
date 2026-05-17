# Phase 1 用户端使用教程：湿实验个性化

## 你现在能做什么

Phase 1 用来让系统逐步适应你的个人记录习惯，包括：

- 你常用的实验术语；
- 你习惯的样品编号方式；
- 某类实验必须出现哪些字段；
- 某台仪器需要重点关注哪些参数。

当前版本先在命令行中使用，不影响原有主项目。

---

## 1. 首次使用：创建你的个性化配置

如果已经有准备好的答案文件：

```bash
python -m extensions.personalization.cli wizard \
  --answers-json .local_data/extensions/personalization/fanjunran_phase1_answers.json
```

如果没有答案文件，也可以直接进入交互式向导：

```bash
python -m extensions.personalization.cli wizard
```

系统会依次询问：

1. 用户 ID 与显示名；
2. 你的术语别名；
3. 你的样品编号习惯；
4. 你的常写字段与必填字段；
5. 某类实验的模板信息；
6. 某台仪器的字段映射和关注参数。

### 配置会保存到哪里

本地个性化配置默认保存在：

```text
.local_data/extensions/personalization/
```

例如：

```text
.local_data/extensions/personalization/users/fanjunran.json
.local_data/extensions/personalization/experiments/solid_state_synthesis.json
.local_data/extensions/personalization/instruments/generic_xrd.json
```

这些是你的本地配置，不会污染团队公共模板。

---

## 2. 查看当前真正生效的配置

```bash
python -m extensions.personalization.cli show-effective \
  --user-id fanjunran \
  --experiment-template solid_state_synthesis \
  --instrument-template generic_xrd
```

你会看到系统最终采用的合并结果，包括：

- 必填字段；
- 偏好字段；
- 样品编号模式；
- 术语归一规则；
- 仪器字段映射。

当前合并逻辑是：

```text
默认规则 → 课题组模板 → 实验模板 → 仪器模板 → 用户配置
```

---

## 3. 用个性化规则分析一份湿实验记录

```bash
python -m extensions.personalization.cli parse \
  --input your_experiment_record.json \
  --user-id fanjunran \
  --experiment-template solid_state_synthesis \
  --instrument-template generic_xrd
```

输出结果会包含：

- 当前记录里已经出现了哪些字段；
- 你的个性化模板要求但当前缺失的字段；
- 步骤术语归一结果；
- 需要人工复核的问题。

例如，如果你的记录里写了：

```text
预烧
```

系统会按你的配置把它归一成：

```text
calcine
```

如果某份记录缺少你要求的 `duration`，系统会生成：

```text
个性化必填字段缺失：duration
```

---

## 4. 当前为你创建的第一版配置

我已经为你建立了一个可直接使用的首版配置：

### 用户
- 用户 ID：`fanjunran`
- 用户名：`范君然`

### 实验模板
- `solid_state_synthesis`
- 适用于材料固相合成记录

### 仪器模板
- `generic_xrd`
- 适用于基础 XRD 参数记录

### 已启用的个性化术语
- `预烧 -> calcine`
- `一烧 -> calcine_stage_1`
- `二烧 -> calcine_stage_2`
- `烧结 -> sinter`

### 当前重点字段
- `temperature`
- `duration`
- `heating_rate`
- `atmosphere`

---

## 5. 你后续最可能需要调整什么

首次配置只是起点。后续你最值得继续补充的是：

1. 你真正常用的样品编号格式；
2. 你个人常写但别人未必会写的字段；
3. 你常用的缩写、别称、中文俚语；
4. 你所在课题组真实使用的仪器字段；
5. 你容易混淆的手写习惯。

如果你想直接修改，可以编辑 `.local_data/extensions/personalization/` 下的本地 JSON 文件。

---

## 6. 你可以把它理解成什么

Phase 1 不是重新训练一个只懂你的模型，而是先让系统有一套明确、可保存、可迁移的“**如何理解你的实验记录**”规则。

这样后续即使多人共用同一个项目，也能在同一主干上保留各自的实验习惯。
