# 溶液反应动力学报告审核

用 Agnes 阅读溶液反应动力学实验报告，AGH 通过 MCP 调用本仓库的 `kinetics_audit` 工具。

**定位**：审**一类**溶液反应动力学报告——`frame_experiment` 先归入实验类（碱水解/皂化类、羟基自由基类、通用溶液动力学），再按**本报告课题**动态检索取证；具体反应（如乙酸乙酯皂化）只作举例，不写死。**不替代**动力学曲线拟合软件，也不做全科化学批改。

核对内容：速率常数、活化能、温度做法、稀释配制、等浓度假设。电导法 / 分光光度法 / 停流法共用条件规则。教学向碱水解类优先 `reference_cache/` 与网页；自由基类优先 NDRL/NIST；酶反应查 SABIO-RK。异类文献不可比。

报告可以是项目目录中的 txt、md、csv、docx、pdf，也可以是对话里的照片。读报告后先 `frame_experiment`，再枚举/采纳主张；检索词由实验名与物种生成。证据不足或文献不一致时不把报告判错；先验卡片不单独定罪。

## 运行

AGH 注册 `mcp_server.py`（见 `agh.mcp.json`）。任务方法在 `skills/kinetics-report-audit/SKILL.md`。判断结果由 `finish_review` 写入 `evidence/`，该目录不提交。

把报告 PDF 放在本仓库根目录，AGH 工作区指向本仓库；会话中让 Agnes 调用 `read_report`（`path` 用相对文件名，如 `报告.pdf`）。PDF 优先用 pdfplumber 抽正文与表格（表格会改写成连续句）；未安装时回退 pypdf。

本地自检：

```text
py -m unittest tests.test_harness tests.test_eval_metrics -v
```

主张级准确度（金标对照，输出 Claim Accuracy / False Conviction Rate / Missed Error Rate / Macro-F1）：

```text
py -m eval.run
```
