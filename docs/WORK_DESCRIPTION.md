# 作品详细描述（表单粘贴稿，5000字以内）

以下整段可直接粘贴到「请详细描述作品内容、实现方案、核心功能与技术亮点」。

---

## 一、作品内容

本作品面向高校化学实验教学场景，解决溶液反应动力学实验报告“难核、易误判”的问题。作品名称：**溶液反应动力学报告智能审核**。运行底座为 Agnes Harness（AGH），智能模型为报名提供的 Agnes（首选 agnes-3.0-flash）。队伍通过 MCP 将自研能力包 `kinetics_audit` 接入 AGH，由 Agnes 按任务技能（Skill）编排工具调用，在同一会话内完成「读报告—抽主张—检索证据—条件对齐—判决—汇总」的可执行闭环。

作品明确边界：只审报告对错与实验条件（同一反应、同一测定方法、配制计量、温度做法），**不替代**动力学曲线拟合软件，也不做全科化学批改。核对对象包括速率常数、活化能、温度做法、稀释配制与等浓度假设；电导法、分光光度法、停流法共用同一套条件规则。溶液反应可查 NDRL/NIST，酶反应可查 SABIO-RK；公开网页检索失败时可回退本地 `reference_cache/`。

典型痛点与对策：学生常把稀释算错归因于“k 不准”，或用摄氏温度直接拟合 Arrhenius，或把羟基自由基与乙酸乙酯的文献速率拿来对比皂化结果。本作品用程序硬规则挡住不可比文献，用验算指出配制错误，用 Agnes 生成可读的说明与改进建议，避免“模型侃化学、无法复核”。

## 二、实现方案

### 2.1 总体架构

三层结构：

1. **AGH 宿主**：负责会话、Agnes 模型调用、工具编排与运行记录导出。比赛有效路径是 AGH 会话，而非仓库内直连模型 API。  
2. **Agnes 模型**：阅读工具返回结果，决定下一步调用；在程序给出的候选句内点选主张；撰写 explanation、improvement 与 summary。  
3. **MCP 能力包 `kinetics_audit`**：以 stdio 方式由 `mcp_server.py` 启动，进程内维护同一 `Job` 状态（报告正文、候选、主张、文献页、判决）。工具之间用 `claim_id` / `url` / `sentence_id` / `candidate_id` 衔接，保证上下文不断档。

任务方法写在 `skills/kinetics-report-audit/SKILL.md`，约束 Agnes：先 `propose_candidates`，再 `extract_claims`；`select_evidence` 若 abstain 不得硬判错；数值与 dilution/stoichiometry/arrhenius/rate 由程序验算；最后必须 `finish_review`。

### 2.2 一次有效运行闭环

在同一 AGH 会话中连续完成：

1. **任务规划**：读取 txt/md/csv/docx/pdf，或对照片走 `session-image://` 后 `record_report`；程序枚举候选原句，Agnes 点选 method/value/calculation 主张。  
2. **能力调用**：按主张检索动力学库或公开网页，打开页面建句向量；`select_evidence` 硬过滤后，Agnes 选定句子并给出 verdict 与说明，调用 `judge_claim`。  
3. **反馈与验证**：条件不对齐记为不可比或证据不足；文献冲突不把报告判错；不可比时可 `retry_claim` 一次。  
4. **结果落地**：`finish_review` 输出三栏——已证实错误、文献支持、证据不足；可选 `causal_notes`（配制与动力学同时出错时提示先查计量）；结果写入 `evidence/`，并保留在会话中供导出。

### 2.3 程序与 Agnes 的职责边界

- **程序决定**：候选是否来自原文；证据是否通过反应/方法/温度硬过滤；数值、稀释、化学计量、Arrhenius、按反应式算速率是否成立；电导法用量是否高于 0.20 mol/L 等设置不合理。  
- **Agnes 决定**：抽哪些候选主张、检索策略表述、方法主张在程序判错时是否降为证据不足、面向学生的说明与改进文案、总评 summary。  
- **安全原则**：证据不足是合格结果；Agnes 不能编造报告外原句，也不能引用未通过硬过滤的文献句；不能单独把方法主张“感觉判错”。

### 2.4 工程与评测

本地以单元测试与金标评测回归：`py -m unittest tests.test_harness tests.test_eval_metrics`；`py -m eval.run` 输出主张级 Claim Accuracy、False Conviction Rate（误定罪率）、Missed Error Rate（漏检错率）与 Macro-F1。

## 三、核心功能

1. **报告接入**：`read_report` / `record_report`，支持常见文档与对话照片转写。  
2. **候选枚举与主张抽取**：`propose_candidates` 扫描可核原句；`extract_claims` 要求 quote 落在候选内；字段不齐返回可执行 hint。  
3. **文献与数据库检索**：`search_references`、`search_solution_kinetics`、`search_enzyme_kinetics`、`read_reference`。  
4. **证据硬过滤与选取**：`select_evidence` 仅返回同一反应、测定方法、温度可对齐的句子；否则 abstain。  
5. **主张判决**：`judge_claim`——数值与计算由程序裁定；方法主张结合 Agnes 的 verdict 与 literature_span。  
6. **重试与汇总**：`retry_claim`；`finish_review` 分桶输出，并生成 summary / causal_notes。  
7. **离线缓存接口**：`reference_cache/` 可供部署方填入本地参考文献，联网失败时回退。

## 四、技术亮点

1. **Agnes 深度参与而非“旁路聊天”**：Agnes 是闭环中的规划与表达核心，通过 Skill 强制走工具链；说明与改进由模型生成，判决骨架由程序托住，二者分工清晰、可答辩。  
2. **条件对齐优先于数值比对**：先判反应族与测定方法，再比数字，从机制上降低“搜到乙酸乙酯就当成皂化文献”的误定罪。  
3. **配制与动力学因果提示**：稀释/等浓度错误与速率常数错误同时出现时给出 `causal_notes`，更贴近化学助教思路。  
4. **状态机式会话记忆**：MCP 侧 `Job` 持久化报告与判决状态，对话侧保留工具 JSON，双层衔接稳定。  
5. **可量化准确度**：不以整份报告对错一个数交差，而以主张级四态（supports / contradicts / not_enough / not_comparable）做金标对照，突出 False Conviction Rate 作为安全主指标。  
6. **赛道合规**：运行阶段仅使用 Agnes 模型；Key 只存 AGH 凭据；MCP 无密钥 stdio；不把 AGH 源码并入作品仓库。

## 五、使用摘要

用户给出实验名称与报告后，Agnes 按 Skill 自动调用 MCP 工具完成审核。输出可读、可导出、可复现自检，满足“任务规划—工具调用—执行反馈—结果验证—异常处理”的赛事闭环要求。

---

（全文低于 5000 字上限；可整段粘贴。）
