# 溶液反应动力学报告审核

用 Agnes 阅读溶液反应动力学实验报告，AGH 通过 MCP 调用本仓库的 `kinetics_audit` 工具。

**定位**：审报告对错与实验条件（同一反应、同一测定方法、配制计量、温度做法），**不替代**动力学曲线拟合软件，也不做全科化学批改。

核对内容：速率常数、活化能、温度做法、稀释配制、等浓度假设。电导法 / 分光光度法 / 停流法共用同一套条件规则。溶液反应查 NDRL/NIST，酶反应查 SABIO-RK；联网失败时可回退到 `reference_cache/`（默认空，由部署方按需填入）。羟基自由基等干扰文献会判不可比，不误判皂化报告。

报告可以是项目目录中的 txt、md、csv、docx、pdf，也可以是对话里的照片。程序先枚举候选原句，模型点选主张；检索页面后先硬过滤同一反应/测定方法/温度，再句向量排序与验算。证据不足或文献彼此不一致时，不把报告判为错误。

## 运行

AGH 注册 `mcp_server.py`（见 `agh.mcp.json`）。任务方法在 `skills/kinetics-report-audit/SKILL.md`。判断结果由 `finish_review` 写入 `evidence/`，该目录不提交。

把报告 PDF 放在本仓库根目录，AGH 工作区指向本仓库；会话中让 Agnes 调用 `read_report`（`path` 用相对文件名，如 `报告.pdf`）。

本地自检：

```text
py -m unittest tests.test_harness tests.test_eval_metrics -v
```

主张级准确度（金标对照，输出 Claim Accuracy / False Conviction Rate / Missed Error Rate / Macro-F1）：

```text
py -m eval.run
```

申报材料：[`docs/SUBMISSION.md`](docs/SUBMISSION.md)。
