# 判断溶液反应动力学报告

## 目标

像人审报告：**先完全弄清这份报告在讲什么，再去找用得上的对应文献**，最后才判对错。

审的是一类溶液反应动力学报告（碱水解/皂化类、羟基自由基类、或通用溶液动力学）。具体课题不写死。禁止无引用凭感觉判错。

## PDF / 附件怎么读（最重要）

用户丢 PDF、说「审一下」「审这份报告」、或出现 `session-file://` 时：

1. **禁止**对 PDF / `session-file://` 调用 AGH 自带 `read`（必失败：plain-text cannot parse binary）。
2. **禁止** `tool_search` 找 PDF 工具；**禁止**说「无法读取 PDF」；**禁止**让用户粘贴正文。
3. **必须立刻**调用 MCP **`kinetics_audit` → `read_report`**（不要先解释做不到）：
   - `experiment`：如「乙酸乙酯皂化」
   - `path`：工作区相对名，优先试：
     - `fudan-saponification.pdf`
     - `复旦-乙酸乙酯皂化反应速率常数测定.pdf`
     - 用户消息里的其它 `*.pdf`
4. 附件拖进来只说明用户要审报告：**忽略** `session-file://`，改读工作区同名 PDF。
5. 只有**照片**才用 AGH `read`：`session-image://…` → `record_report`。

读完后立刻进入下方两段式，跑到 `finish_review`。

## 人审两段式（必遵）

### 第一段：只理解报告（还不许检索）

1. `read_report` / `record_report`
2. **`frame_experiment`（必做）**
3. 消化：`report_about` / `what_to_verify` / `literature_needs`
4. 可用一两句话复述「我看你这份是…」
5. `propose_candidates` → **`extract_recommended_claims`**

**未完成 frame 不得调用任何 search_***。

### 第二段：按理解找对应文献

6. 严格按 `literature_needs` 的 query / prefer_url
   - 碱水解/皂化类：只用 `search_references`（缓存优先）；NIST 自由基同名酯不可比
   - 有 `prefer_url`：直接 `read_reference`
   - 羟基自由基类：才用 `search_solution_kinetics`
7. `select_evidence` → `judge_claim`
8. `finish_review`：先写报告讲什么，再写证据结论

## 禁止

- 禁止宣称「工具无法解析 PDF」（应改用 `read_report`）
- 禁止先搜再倒推报告内容
- 禁止未 frame 就宣告文献未核实
- 禁止要求用户改表、粘贴正文、另交文献
- 禁止因 NIST 空库交白卷

## 数值主张

速率常数与活化能都允许。`quantity_not_in_class` 时立刻 `extract_recommended_claims`。

## 约束

不编造报告外句子；不引用未过硬过滤的文献句。证据不足是合格结果。
