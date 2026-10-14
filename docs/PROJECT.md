# 溶液动力学报告审核项目文档

本科生组，队伍智能鳄梨，参赛编号 U348。

本文说明作品要解决的问题、怎样开发和接入 Agnes Harness（AGH），以及开发和运行时必须遵守的安全要求。

## 目的

作品用 Agnes 和 AGH **审溶液反应动力学报告对错与条件**，不替代动力学曲线拟合软件，也不做全科批改。核对速率常数、活化能、温度做法，以及配制稀释与等浓度计量；电导法、分光光度法、停流法共用同一套规则。程序先 `propose_candidates` 枚举候选原句，模型只在候选内点选主张；选证据时先按同一反应、测定方法与温度硬过滤，再向量排序。联网失败可回退 `reference_cache/`（默认空）。模型写 explanation、improvement 与 summary。稀释核对写出应得工作浓度；缺字段时返回可执行 hint。程序做句向量检索与条件核对。比较数字前先核对反应物与测定方法；对不上则不可比，不误判。数值对错由程序决定；方法主张上模型可将程序判错降为证据不足，但不能单独判错。计量与动力学数值同时出错时给出 `causal_notes`，提示优先排查配制。速率常数和活化能不随初始用量改变。电导法用量高于 0.20 mol/L 时条件不合理。温度差出容差或测定方法不同类仍不可比。Arrhenius 与按反应式算速率用报告自有数据重算。`finish_review` 分已证实错误、文献支持、证据不足。没有内置原始测量表拟合。

一次有效运行要在同一个 AGH 会话里连续完成这些步骤：

1. 任务规划：阅读输入的实验报告，抽出方法、数值和计算主张。
2. 能力调用：按主张检索公开资料，打开页面，用 `select_evidence` 取出相关原句，再调用 `judge_claim`。
3. 反馈与结果验证：槽位、条件或原文对不上时改为证据不足或不可比。多个文献冲突时不把报告判错。最后汇总三栏结果。

使用时给出实验名称和一份实验报告。照片附在 AGH 对话里，由模型通过 `read` 查看 `session-image://` 原图，再调用 `record_report`。项目目录中的 txt、md、csv、docx、pdf 由 `read_report` 抽出正文。

## 开发方式

AGH 是运行宿主，本仓库是它调用的 MCP 能力。不要把 AGH 源码合并进本仓库。比赛运行记录从 AGH 会话导出。本地只跑单元测试，不把直接请求模型接口当作比赛运行路径。

开发分三层：

1. 报告读取。`read_report` 和 `record_report` 接收用户给出的文件或照片正文。
2. 判断。`kinetics_audit/vectors.py` 做当次页面的句向量检索，`kinetics_audit/kinetics.py` 核对用量条件和 Arrhenius 拟合，`kinetics_audit/numbers.py` 解析数字、单位和算式，`judge_claim` 给出程序结论。
3. AGH 接入。`mcp_server.py` 从项目根目录启动 MCP。AGH 的 stdio 配置没有工作目录，所以入口脚本自己切到项目根目录。

本地检查在项目根目录执行：

```text
py -3 -m unittest tests.test_harness tests.test_eval_metrics
py -3 -m eval.run
```

单元测试使用固定的报告正文和检索结果，不调用在线模型。`eval/run` 用 `eval/gold/cases.json` 做主张级金标对照，报告 Claim Accuracy、False Conviction Rate（误定罪）、Missed Error Rate（漏检错）与 Macro-F1；不替代 AGH 在线评测，但用于量化程序判决准确度。现场演示按 `docs/DEMO.md`，粘贴材料在 `eval/gold/reports/`。

接入 AGH 的顺序：

1. 用源码构建 AGH，并在仓库根目录执行 `node .\packages\cli\dist\local\agnes.mjs serve`。本地页面是 `http://127.0.0.1:4177/`。
2. 在模型账号中选择 Agnes AI，地址使用 `https://api.agnes-ai.cn/v1`。Key 只粘贴在 AGH 的密码框里。测试连接后选择 `agnes-3.0-flash`；若不可用，再改用 `agnes-2.5-flash`，并在提交材料里如实写明模型名称、版本和使用阶段。
3. 注册并启用 stdio MCP。可执行文件是本机 Python，参数是 `mcp_server.py`（见 `agh.mcp.json` 中的 `kinetics_audit`）。启用后用 `mcp status` 和 `mcp tools` 确认能看到 `read_report`、`record_report`、`propose_candidates`、`extract_claims`、`search_references`、`read_reference`、`select_evidence`、`judge_claim`、`finish_review`。
4. 在一个 AGH 会话中给出实验报告。会话记录要留下抽主张、检索、判断和被拒绝的引用。`finish_review` 把汇总写入 `evidence/`。该目录已忽略，不进入公开仓库。

模型在提交运行中只使用报名提供的 Agnes 模型。用其他编程助手编写本仓库代码，和作品运行时调用的模型是两件事。若运行阶段改用其他模型，必须由队伍自行承担费用，并在材料中写明名称、版本、使用阶段和调用方式。

## 安全要求

### 密钥和仓库

- Agnes Key 只保存在 AGH 的本机凭据里。不要写入源代码、`README`、`项目文档`、`agh.mcp.json`、截图、聊天记录或提交压缩包。
- 不要把 Key 发到队伍群、Issue 或公开仓库。本仓库是公开仓库，推送前确认没有密钥、`.env` 和 `evidence/`。
- `evidence/` 已在 `.gitignore` 中。运行证据按比赛要求单独整理，不把含有会话内容的目录直接提交。
- 页面上的 Key 输入框关闭设置后不再显示明文。需要更换时重新粘贴，不要从聊天记录里找回。

### 模型能接触的内容

- 模型通过工具读取用户给出的报告，联网检索公开页面，并引用原文判断。检索只访问公开 HTTPS 地址，不携带密钥。
- 判断引用的文献句必须来自当次向量检索返回的句子。数值和计算由程序比较，模型不能改写差值和计算结果。

### 运行隔离

- 报告文件只从项目目录读取，不能通过相对路径读到目录外的文件。
- 检索只请求公开 HTTPS 地址，不携带密钥，也不打开检索结果以外的地址。

### AGH 接入

- MCP 使用无密钥的 stdio。不要在启动参数、环境变量或聊天里附带 Key。
- 新的 MCP 服务先审核再启用。修改启动命令后，原来的本地启动批准失效，需要重新审核并启用。
- 同一台机器上的 AGH 命令和网页必须使用同一套 `AGH_HOME` 与配置档，否则网页里看不到已经注册的服务。
