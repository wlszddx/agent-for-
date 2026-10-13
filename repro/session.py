import json
from datetime import datetime
from pathlib import Path

from repro.tools import TOOL_SPECS, dispatch

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = (
    "你是溶液反应动力学报告判断执行器。只判断速率常数、活化能和温度做法。"
    "先抽出主张。溶液速率常数用 search_solution_kinetics，酶动力学用 search_enzyme_kinetics，再用 select_evidence。"
    "公开网页仍可用 search_references，同一主张只查一次。不可比或证据不足时调用 retry_claim，程序会带上用量、温度和测定方法再查一轮。"
    "同一反应的速率常数和活化能不随初始用量改变，用量不同仍可比较。电导法用量高于 0.20 mol/L 时条件不合理。"
    "方法判断要给出文献句中的做法 literature_span。文献句没有讨论报告里的这一步时，不记为错误。"
    "计算主张 expression 用 arrhenius 重算活化能，用 rate 时按反应式和报告里的速率常数、浓度计算应有速率。反应式推不出速率常数。这两种计算不要检索。"
    "证据不足是合格结果。最后调用 finish_review。"
)
USER = "根据给出的实验报告判断错误，并提出改进方法。"


def run_session(job, client, max_steps=12):
    messages = [
        {"role": "system", "content": SYSTEM},
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
        "experiment": job.experiment_name,
        "case": job.case,
        "steps": len({event["step"] for event in trace}),
        "writes": job.writes,
        "reasons": reasons,
        "trace": trace,
    }


class EvidenceLog:
    def __init__(self, job, root=None):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = Path(root) if root is not None else ROOT / "evidence"
        experiment = job.experiment.name if job.experiment else "unopened"
        case = job.case or "none"
        self.dest = base / f"{stamp}-mcp-{experiment}-{case}"
        self.dest.mkdir(parents=True, exist_ok=True)
        self.job = job
        self.calls = []

    def record(self, name, arguments, result):
        shown = {}
        if isinstance(arguments, dict):
            shown = {key: value for key, value in arguments.items() if key != "source"}
            source = arguments.get("source")
            if isinstance(source, str):
                shown["source_chars"] = len(source)
        event = {
            "name": name,
            "experiment": self.job.experiment.name if self.job.experiment else None,
            "case": self.job.case,
            "arguments": shown,
            "result": result,
        }
        with (self.dest / "trace.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.calls.append(name)
        verify = self.job.last_verify or {}
        summary = {
            "accepted": self.job.accepted,
            "experiment": self.job.experiment.name if self.job.experiment else None,
            "case": self.job.case,
            "writes": self.job.writes,
            "reasons": list(verify.get("reasons") or []),
            "calls": self.calls,
        }
        (self.dest / "result.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if self.job.source:
            (self.dest / "analysis.py").write_text(self.job.source, encoding="utf-8")
        execution = self.job.last_execution or {}
        if execution.get("metrics") is not None:
            (self.dest / "metrics.json").write_text(
                json.dumps(execution["metrics"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


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
