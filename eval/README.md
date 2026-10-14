# 主张级准确度评测

对照金标主张的最终 `status`（`supports` / `contradicts` / `not_enough` / `not_comparable`），量化审核准确程度。

## 主指标

| 指标 | 含义 |
|------|------|
| Claim Accuracy | 四态判决正确率 |
| False Conviction Rate | 金标非错误却判为 `contradicts` 的比例（越低越好） |
| Missed Error Rate | 金标为 `contradicts` 却未判错的比例（越低越好） |
| Macro-F1 | 四态宏平均 F1 |

另报告候选召回均值与按 `kind` 拆分的子表。

## 运行

```text
py -m eval.run
py -m eval.run --json
py -m eval.run --gold path/to/cases.json
```

金标格式见 [`gold/cases.json`](gold/cases.json)。扩展时为每条主张填写 `gold_status`，并给出 `report`（或 `report_file`）、`claim`，以及检索类主张的 `evidence` / `judge`（或 `expect_abstain`）。

完整报告文本在 [`gold/reports/`](gold/reports/)，现场演示顺序见 [`../docs/DEMO.md`](../docs/DEMO.md)。
