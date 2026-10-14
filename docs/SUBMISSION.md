# 申报材料（可直接粘贴）

队伍：智能鳄梨 · 参赛编号 U348 · 本科生组  
作品名：溶液反应动力学报告审核（kinetics_audit）

以下按官网表单常见字段整理。带「【】」处请按实填写后提交。

---

## 一、队伍信息

| 项 | 内容 |
|----|------|
| 组别 | 本科生组 |
| 队名 | 智能鳄梨 |
| 参赛编号 | U348 |
| 作品名称 | 溶液反应动力学报告审核 |
| 队员 | 【姓名1（学校/专业/年级）】；【姓名2】；【姓名3】 |
| 联系方式 | 【手机 / 邮箱】 |

---

## 二、作品简介 / 问题与闭环说明

### 2.1 一句话

用 Agnes + Agnes Harness（AGH）审溶液反应动力学**实验报告对错与条件**，不替代动力学曲线拟合软件，也不做全科化学批改。

### 2.2 要解决的问题

学生报告常见失误包括：稀释/等浓度计量算错却归咎于动力学结果、用摄氏温度直接做 Arrhenius 拟合、与羟基自由基等**不同反应族**或不同测定方法的文献硬比数值。现有通用对话难以稳定完成「条件对齐 → 可验证判决」。本作品把核对范围收窄为：速率常数、活化能、温度做法、配制稀释与等浓度假设；电导法 / 分光光度法 / 停流法共用同一套条件规则。

### 2.3 技术路线（程序 + 模型分工）

- **程序**：`propose_candidates` 枚举可核原句；`select_evidence` 按同一反应、测定方法、温度硬过滤；数值与 dilution / stoichiometry / Arrhenius / rate 由程序验算；不可比或证据不足时不把报告判为错误。
- **模型（Agnes）**：在候选内点选主张，写 explanation / improvement / summary；方法主张上可将程序判错降为证据不足，但不能单独升格为错。
- **输出**：`finish_review` 三栏——已证实错误 / 文献支持 / 证据不足；计量与动力学同时出错时给出 `causal_notes`。

### 2.4 完整闭环（一次有效运行）

在**同一个 AGH 会话**内连续完成：

1. **任务规划**：阅读实验报告，抽出 method / value / calculation 主张。  
2. **工具调用**：检索公开资料或动力学库 → `read_reference` → `select_evidence` → `judge_claim`（计算类不检索，直接验算）。  
3. **执行反馈与结果验证**：槽位或条件对不上则记为证据不足 / 不可比；文献冲突不误判；最后 `finish_review` 汇总。  
4. **异常处理**：联网失败可回退 `reference_cache/`；字段不齐返回可执行 hint；干扰文献（如 ·OH + 乙酸乙酯）硬过滤，避免误定罪。

使用方式：用户给出实验名称 + 报告（项目内 txt/md/csv/docx/pdf，或对话照片经 `session-image://` 再 `record_report`）。

---

## 三、仓库链接或代码包

| 项 | 内容 |
|----|------|
| 公开仓库链接 | 【粘贴 GitHub / Gitee / 赛方要求的仓库 URL】 |
| 或代码压缩包 | 【上传不含 Key、不含 evidence/ 的源码包，建议名：U348-智能鳄梨-kinetics_audit.zip】 |
| 入口说明 | 仓库根目录；MCP 入口 `mcp_server.py`；包名 `kinetics_audit` |
| 本地自检 | `py -m unittest tests.test_harness tests.test_eval_metrics -q`；`py -m eval.run` |

**打包前确认已排除：** Agnes Key、`.env`、`evidence/`、含密钥截图。AGH 源码不并入本仓库。

---

## 四、运行说明：注册 MCP 与加载 Skill

### 4.1 环境

- Python ≥ 3.10（命令可用 `py -3`）
- 已安装并可启动 AGH（本地页示例：`http://127.0.0.1:4177/`）
- 本仓库置于本地目录，下文称「项目根目录」

### 4.2 注册 MCP（stdio）

配置参考仓库内 `agh.mcp.json`：

```json
{
  "mcpServers": {
    "kinetics_audit": {
      "command": "py",
      "args": ["-3", "mcp_server.py"]
    }
  }
}
```

操作要点：

1. 在 AGH 中新增 stdio MCP：可执行文件为本机 Python，参数为项目根目录下的 `mcp_server.py`（或按 AGH 界面导入上述配置）。  
2. **工作目录**：AGH stdio 可能不带 cwd，入口脚本会自行切到项目根目录。  
3. 审核并启用服务。修改启动命令后需重新审核。  
4. 执行 `mcp status` / `mcp tools`，应能看到：  
   `read_report`、`record_report`、`propose_candidates`、`extract_claims`、`search_solution_kinetics`、`search_enzyme_kinetics`、`search_references`、`read_reference`、`select_evidence`、`judge_claim`、`retry_claim`、`finish_review` 等。

### 4.3 加载 Skill

1. 将任务方法指向仓库内：`skills/kinetics-report-audit/SKILL.md`。  
2. 在 AGH 会话中启用该 skill（按 AGH 界面「技能 / 方法」加载方式操作）。  
3. 新建会话，给出实验名称与报告正文，按 skill 步骤跑至 `finish_review`。  
4. 结果写入项目 `evidence/`（已 gitignore）；比赛运行证据从 AGH 会话导出后按赛方要求单独上传。

### 4.4 模型账号（AGH 内）

1. 模型提供方选择 **Agnes AI**，地址：`https://api.agnes-ai.cn/v1`。  
2. Key **仅**粘贴在 AGH 密码框，不写入仓库或截图。  
3. 测试连接后选择运行模型（见第五节）。

---

## 五、模型声明

| 项 | 声明 |
|----|------|
| 运行阶段所用模型 | **仅使用报名提供的 Agnes 模型** |
| 首选模型 | `agnes-3.0-flash` |
| 备选（首选不可用时） | `agnes-2.5-flash` |
| API | `https://api.agnes-ai.cn/v1`（经 AGH 调用，不在本仓库内直连） |
| 开发期辅助 | 编写代码可使用其他编程助手；**与作品运行时调用的模型无关**，运行评测/演示不接入其他厂商模型 |
| 若实际改用其他模型 | 由队伍自费，并在材料中写明名称、版本、使用阶段与调用方式（本队提交运行**不打算**改用非 Agnes 模型） |

**密钥安全：** Key 只保存在 AGH 本机凭据；不出现在源码、`README`、本文件、`agh.mcp.json`、截图或提交压缩包中。

---

## 六、建议一并上传的附件清单

1. 本说明（或官网表单中对应字段原文）  
2. 代码仓库链接或源码包  
3. AGH 完整会话导出（含抽主张、检索、判断与汇总）  
4. 对应 `finish_review` 的 `*-review.json`（脱敏，不含 Key）  
5. （可选）`py -m eval.run` 输出：主张级 Claim Accuracy / False Conviction Rate / Missed Error Rate  

填写【】并确认仓库链接后即可提交。

官网「详细描述作品内容…」长文见 [`WORK_DESCRIPTION.md`](WORK_DESCRIPTION.md)（约 3300 字，5000 字以内）。
