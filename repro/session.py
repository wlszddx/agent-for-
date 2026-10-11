import json
from datetime import datetime
from pathlib import Path

from repro.tools import TOOL_SPECS, dispatch

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = (
    "你是实验复现执行器。只通过工具读取协议、测量表和当前分析脚本，"
    "运行脚本，并调用 verify_run。只有 verify_run 返回 accepted=true 才算完成。"
    "未通过时根据 reasons、指标和残差修改分析脚本，然后重新运行并再次验收。"
    "分析脚本最多替换 3 次。"
)
USER = "复现当前协议。工作副本里的分析脚本是当前复现稿。"


def run_session(job, client, max_steps=8):
    messages = [
        {"role": "system", "content": SYSTEM + job.experiment.instructions()},
        {"role": "user", "content": USER},
    ]
    trace = []
    for step in range(1, max_steps + 1):
        reply = client.complete(messages, TOOL_SPECS)
        messages.append(_assistant(reply))
        trace.append(
            {
                "step": step,
                "type": "model",
                "content": reply.get("content"),
                "tool_calls": [
                    {"name": call["name"], "arguments": call["arguments"]}
                    for call in reply["tool_calls"]
                ],
            }
        )
        if not reply["tool_calls"]:
            break
        for call in reply["tool_calls"]:
            result = dispatch(job, call["name"], call["arguments"])
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
            trace.append(
                {
                    "step": step,
                    "type": "tool",
                    "name": call["name"],
                    "result": result,
                }
            )
        if job.accepted:
            break
    reasons = []
    if job.last_verify:
        reasons = list(job.last_verify.get("reasons") or [])
    return {
        "accepted": job.accepted,
        "experiment": job.experiment.name,
        "case": job.case,
        "steps": len({event["step"] for event in trace}),
        "writes": job.writes,
        "reasons": reasons,
        "trace": trace,
    }


def write_evidence(session, job):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = ROOT / "evidence" / f"{stamp}-{job.experiment.name}-{job.case}"
    dest.mkdir(parents=True, exist_ok=True)
    with (dest / "trace.jsonl").open("w", encoding="utf-8") as handle:
        for event in session["trace"]:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    summary = {
        "accepted": session["accepted"],
        "experiment": session["experiment"],
        "case": session["case"],
        "steps": session["steps"],
        "writes": session["writes"],
        "reasons": session["reasons"],
    }
    (dest / "result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (dest / "analysis.py").write_text(job.source, encoding="utf-8")
    execution = job.last_execution or {}
    if execution.get("metrics") is not None:
        (dest / "metrics.json").write_text(
            json.dumps(execution["metrics"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return dest


def _assistant(reply):
    message = {"role": "assistant", "content": reply.get("content") or ""}
    if reply["tool_calls"]:
        message["tool_calls"] = [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                },
            }
            for call in reply["tool_calls"]
        ]
    return message
