import json
from datetime import datetime
from pathlib import Path

from kinetics_audit.tools import TOOL_SPECS, dispatch

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = (
    "你是溶液反应动力学报告判断执行器。审报告对错与条件，不替代动力学拟合软件。"
    "先 propose_candidates，再在候选句内 extract_claims（带 candidate_id）；不要编候选外原句。"
    "有母液浓度、移取体积和定容体积时必须抽 dilution；有等浓度假设时必须抽 stoichiometry。"
    "select_evidence 只返回通过同一反应、测定方法与温度硬过滤的句子；若 abstain 不要硬判错。"
    "溶液速率常数用 search_solution_kinetics，酶动力学用 search_enzyme_kinetics；公开网页可用 search_references，失败时用 offline。"
    "同一反应的速率常数和活化能不随初始用量改变。电导法用量高于 0.20 mol/L 时条件不合理。"
    "judge_claim 必须给 verdict，并尽量写 explanation；有错时写 improvement。"
    "方法主张上，程序判错而你给 supports 或 not_enough 时记为证据不足。"
    "数值与 dilution、stoichiometry、arrhenius、rate 由程序验算，不要检索。"
    "证据不足是合格结果。最后 finish_review 并写 summary。"
)
USER = (
    "根据给出的实验报告判断错误，并提出改进方法。"
    "注意配制计量是否算错、测定方法是否对齐，以及是否因此导致动力学结果偏差。"
)


def run_session(job, client, max_steps=16):
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
