from repro.catalog import load
from repro.guard import GuardError, check_source
from repro.sandbox import execute
from repro.table import public_rows

MAX_WRITES = 3


class Job:
    def __init__(self, experiment, case, source):
        self.experiment = experiment
        self.case = case
        self.source = source
        self.writes = 0
        self.last_execution = None
        self.last_verify = None
        self.accepted = False

    @classmethod
    def open(cls, experiment, case):
        loaded = load(experiment)
        return cls(loaded, case, loaded.case_source(case))


def read_protocol(job, _args):
    return job.experiment.protocol()


def read_measurements(job, _args):
    return {"rows": public_rows(job.experiment.measurements())}


def read_analysis(job, _args):
    return {"source": job.source, "writes_remaining": MAX_WRITES - job.writes}


def write_analysis(job, args):
    if job.writes >= MAX_WRITES:
        return {"ok": False, "error": "write_budget_exhausted"}
    source = args.get("source")
    if not isinstance(source, str) or not source.strip():
        return {"ok": False, "error": "source_required"}
    try:
        check_source(source, job.experiment.sealed_tokens())
    except GuardError as exc:
        return {"ok": False, "error": str(exc)}
    job.source = source
    job.writes += 1
    job.last_execution = None
    job.accepted = False
    job.last_verify = None
    return {"ok": True, "writes": job.writes, "writes_remaining": MAX_WRITES - job.writes}


def run_experiment(job, _args):
    try:
        check_source(job.source, job.experiment.sealed_tokens())
    except GuardError as exc:
        return {"ok": False, "error": str(exc)}
    execution = execute(job.source, job.experiment.measurements())
    job.last_execution = execution
    job.accepted = False
    job.last_verify = None
    return {
        "ok": execution["exit_code"] == 0 and execution.get("metrics") is not None,
        "exit_code": execution["exit_code"],
        "stderr": execution.get("stderr") or "",
        "metrics": execution.get("metrics"),
        "residuals": job.experiment.residuals(execution),
    }


def verify_run(job, _args):
    if job.last_execution is None:
        result = {"accepted": False, "reasons": ["no_run"]}
        job.last_verify = result
        job.accepted = False
        return result
    result = job.experiment.verify(job.last_execution)
    job.last_verify = result
    job.accepted = bool(result["accepted"])
    return result


TOOLS = {
    "read_protocol": read_protocol,
    "read_measurements": read_measurements,
    "read_analysis": read_analysis,
    "write_analysis": write_analysis,
    "run_experiment": run_experiment,
    "verify_run": verify_run,
}

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "read_protocol",
            "description": "读取当前实验的协议、拟合规则和验收阈值。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_measurements",
            "description": "读取当前实验的测量表。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_analysis",
            "description": "读取当前复现脚本。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_analysis",
            "description": "替换当前复现脚本。写入后必须重新运行并验收。",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "完整的 analysis.py 源码"}
                },
                "required": ["source"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_experiment",
            "description": "在隔离目录运行当前脚本，返回指标和留出残差。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_run",
            "description": "用当前实验的规则验收最近一次运行。accepted 为 true 才算复现完成。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]


def dispatch(job, name, arguments):
    handler = TOOLS.get(name)
    if handler is None:
        return {"ok": False, "error": "unknown_tool", "name": name}
    if not isinstance(arguments, dict):
        return {"ok": False, "error": "arguments_must_be_object"}
    return handler(job, arguments)
