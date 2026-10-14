# AGH 现场演示脚本（约 6–8 分钟）

队伍智能鳄梨 · U348。一句话定位：**审溶液反应动力学报告对错与条件**，不替代拟合软件，也不做全科批改。

## 开场（30 秒）

> 学生报告里最容易错的不是“会不会算 Arrhenius”，而是**条件没对齐还硬比文献**，以及**稀释算错却怪动力学**。我们用 Agnes + MCP：程序枚举候选、硬过滤证据、验算数值；模型只点选主张并写说明。

屏幕上打开：AGH 已注册 `kinetics_audit`，skill 为 `kinetics-report-audit`。

## 演示顺序（严格按此三案）

材料在 [`eval/gold/reports/`](../eval/gold/reports/)。每案：粘贴全文 → 说实验名 → 等 `finish_review` → 指三栏。

### 案 A｜配制错 + 速率错（2 分钟）— 展示“会追因”

- 文件：`01-metering-and-rate.txt`
- 实验名：`乙酸乙酯皂化`
- **要指给评委看的**：
  1. `confirmed_errors` 里有 dilution（工作浓度算错）和速率常数偏差。
  2. 若出现 `causal_notes`：先查配制，再谈动力学。
- **口述**：纯 LLM 容易只骂 k 不对；我们把计量和动力学拆开判，并提示因果。

### 案 B｜羟基自由基文献陷阱（2 分钟）— 展示“不误定罪”

- 文件：`02-radical-trap.txt`
- 实验名：`乙酸乙酯皂化`
- **要指给评委看的**：
  1. 检索可能碰到 ·OH + 乙酸乙酯 的 NIST 类结果。
  2. 终态进 `insufficient`，`status` 为 `not_comparable`，**没有** `confirmed_errors`。
- **口述**：反应族不同就硬过滤；证据不足是合格结果，不会把皂化报告冤枉成错。

### 案 C｜摄氏度直接拟合（1.5 分钟）— 展示方法主张

- 文件：`03-method-celsius.txt`
- 实验名：`皂化反应`
- **要指给评委看的**：
  1. method 主张进 `confirmed_errors`。
  2. `improvement` 写清：拟合前换成热力学温度。
- **口述**：方法槽位必须对齐；模型不能单独“感觉判错”，程序核对后才落桶。

### 备用｜干净报告（超时或被问“会不会乱报错”时）

- 文件：`04-clean-supports.txt`
- 期望：`supported`，无 `confirmed_errors`。

## 收尾（1 分钟）

固定三句：

1. **主张级输出**：`confirmed_errors` / `supported` / `insufficient`，不是整卷打分。  
2. **安全主指标**：误定罪率优先；不可比绝不进已证实错误。  
3. **本地可复现**：`py -m unittest …` 与 `py -m eval.run`（金标主张级准确度）。

## 现场禁忌

- 不要演示通用聊天或让模型自由发挥化学百科。
- 不要打开 `evidence/` 里无关历史文件；只看当次 `finish_review` 路径。
- 联网失败时说明：可回退 `reference_cache/`（部署方可填）；案 B 仍应能讲清硬过滤逻辑。

## 赛前自检（5 分钟）

```text
py -m unittest tests.test_harness tests.test_eval_metrics -q
py -m eval.run
```

AGH：`mcp status` 能看到 `propose_candidates`、`extract_claims`、`select_evidence`、`judge_claim`、`finish_review`。
