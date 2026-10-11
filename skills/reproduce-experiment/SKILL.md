# 复现一份实验

## 目标

复现当前协议。验收只认 `verify_run` 的 `accepted=true`。

## 步骤

1. 调用 `read_protocol`、`read_measurements`、`read_analysis`。
2. 调用 `run_experiment`。
3. 调用 `verify_run`。
4. 未通过时，根据 `reasons`、指标和 `residuals` 替换分析脚本，再从步骤 2 重做。
5. 分析脚本最多替换 3 次。

## 约束

拟合规则、列名和标定划分以协议为准。不要把协议里没有给出的拟合常数写进源码。脚本只能使用 json、math、csv、pathlib。
