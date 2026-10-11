# 实验复现

用 Agnes 修改复现稿，AGH 通过 MCP 调用工具。每份实验放在 `experiments/<名称>/`，自带协议、测量表、复现稿和验证器。运行、隔离、写入次数和证据目录不包含具体公式。

当前有两份实验：

| 实验 | 协议 | 失败稿 |
| --- | --- | --- |
| hydrolysis | 乙酸乙酯皂化速率的 Arrhenius 拟合 | celsius、leakage、minute_rate |
| phosphate | 磷酸盐标准曲线 | leakage、microgram |

`correct` 必须通过。其余稿必须被拒绝。验证器重算留出误差、标定划分和参数一致性，脚本自报的误差不算通过。

## 运行

在项目根目录：

```text
py -3 -m repro list
py -3 -m repro check
py -3 -m repro export-data
```

接入 Agnes 后指定实验和稿：

```text
set AGNES_API_KEY=你的密钥
py -3 -m repro run --experiment phosphate --case microgram
```

模型名默认 `agnes-2.5-flash`，可用 `AGNES_MODEL` 和 `AGNES_BASE_URL` 覆盖。证据写在 `evidence/`。

AGH 使用 `agh.mcp.json`。换实验时改其中的 `--experiment` 和 `--case`。任务方法在 `skills/reproduce-experiment/SKILL.md`。

新增一份实验时，在 `experiments/<名称>/` 放 `protocol.json`、`spec.py` 和 `cases/<稿>/analysis.py`。`spec.py` 提供 `measurements`、`verify`、`residuals`、`SEALED_TOKENS`、`INSTRUCTIONS`。名为 `correct` 的稿应能通过验收。
