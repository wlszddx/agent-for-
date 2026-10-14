# 判断溶液反应动力学报告

## 目标

这个 agent 审溶液反应动力学**报告对错与条件**，不替代动力学拟合软件，也不批改任意化学实验。核对速率常数、活化能、温度做法，以及配制计量与等浓度假设。程序负责枚举候选、硬过滤证据、条件对齐与验算；模型只在候选中点选、写说明与改进建议。

深度优先：同一套规则覆盖电导法、分光光度法、停流法等测定方法；反应族不同（如皂化对羟基自由基）不可比。

## 自动开审（少说话 / 只丢附件）

用户几乎不写字、只丢照片/文件名、或只说「审」「测」时：**不要追问实验名或说明**，立刻按下方步骤完整跑到 `finish_review`。

读取优先级：
1. 先 `read` `session-image://list`；若有图，读最新一张，再 `record_report`。
2. 否则：用户消息里的相对路径 / 工作区根目录常见报告名（如 `*.pdf`、`*.docx`、`*.txt`、`*.md`）→ `read_report`。
3. 仍没有报告才问一句「请附上报告或给出工作区内文件名」。

## 步骤

1. 读取实验报告。照片用 AGH 的 `read`：先读 `session-image://list`，再读 `session-image://消息序号/图片序号`，然后调用 `record_report`。项目目录里的 txt、md、csv、docx、pdf 调用 `read_report`。
2. 调用 `propose_candidates`。程序扫描报告，给出可核对的候选原句与建议种类。不要编造候选外的句子。
3. 调用 `extract_claims`。`quote` 必须落在候选句内，推荐带上 `candidate_id`。
   - `method`：`slot` 写被核对的温度做法，并且出现在原句里。
   - `value`：`quantity` 只能是速率常数或活化能。`dosage`、`temperature`、`method` 都要是原句里的短条件。
   - `calculation`（有数据就**必须**抽）：
     - `arrhenius` / `rate` / `dilution` / `stoichiometry` / 普通算式。
     - `dilution` 与 `stoichiometry` 字段不齐时会返回 `hint`。
4. 数值主张按报告里的反应去检索。溶液动力学用 `search_solution_kinetics`，酶反应用 `search_enzyme_kinetics`。公开网页用 `search_references`；联网失败时回退 `reference_cache/`。
5. 调用 `select_evidence`。程序先硬过滤：同一反应、同一测定方法、温度可对齐；不合格句不会出现在返回列表。可用 `focus`。若 `abstain`，不要硬判错。
6. 调用 `judge_claim`。`sentence_id` 只能来自上一步。给 `verdict`，尽量写 `explanation`；有错写 `improvement`。
   - 方法主张要给 `literature_span`。程序判错而你给 `supports`/`not_enough` 时记为证据不足。
   - 数值对错由程序决定。电导法用量高于 0.20 mol/L 时条件不合理。
   - 计算类主张不检索。
7. 不可比或证据不足时调用一次 `retry_claim`。
8. 调用 `finish_review` 并写 `summary`。计量与动力学数值同时出错时会有 `causal_notes`。

## 约束

不要编造报告里没有的句子，也不要引用未通过硬过滤的文献句。证据不足是合格结果。
