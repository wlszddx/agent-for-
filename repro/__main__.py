import argparse
import json
import sys

from repro.agnes import AgnesClient, AgnesError
from repro.catalog import experiment_names, load
from repro.mcp import serve
from repro.session import run_session, write_evidence
from repro.tools import Job, dispatch


def main(argv=None):
    parser = argparse.ArgumentParser(prog="repro")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check")
    check.add_argument("--experiment", default="all")
    check.add_argument("--case", default="all")

    run = commands.add_parser("run")
    run.add_argument("--experiment", required=True)
    run.add_argument("--case", required=True)

    mcp = commands.add_parser("mcp")
    mcp.add_argument("--experiment", required=True)
    mcp.add_argument("--case", required=True)

    export = commands.add_parser("export-data")
    export.add_argument("--experiment", default="all")

    commands.add_parser("list")

    args = parser.parse_args(argv)
    if args.command == "list":
        return _list()
    if args.command == "check":
        return _check(args.experiment, args.case)
    if args.command == "run":
        return _run(args.experiment, args.case)
    if args.command == "mcp":
        serve(Job.open(args.experiment, args.case))
        return 0
    if args.command == "export-data":
        return _export(args.experiment)
    return 2


def _list():
    for name in experiment_names():
        experiment = load(name)
        cases = ",".join(experiment.case_names())
        print(f"{name:12} {cases}")
    return 0


def _selected(name):
    if name == "all":
        return [load(item) for item in experiment_names()]
    return [load(name)]


def _check(experiment_name, case_name):
    failed = False
    try:
        selected = _selected(experiment_name)
    except KeyError:
        print(f"未知实验 {experiment_name}", file=sys.stderr)
        return 2
    for experiment in selected:
        cases = experiment.case_names() if case_name == "all" else [case_name]
        for case in cases:
            try:
                job = Job.open(experiment.name, case)
            except KeyError:
                print(f"未知案例 {experiment.name} {case}", file=sys.stderr)
                return 2
            dispatch(job, "run_experiment", {})
            result = dispatch(job, "verify_run", {})
            reasons = ",".join(result.get("reasons") or []) or "pass"
            print(f"{experiment.name:12} {case:12} {reasons}")
            if result["accepted"] != (case == "correct"):
                failed = True
    return 1 if failed else 0


def _run(experiment_name, case):
    try:
        client = AgnesClient.from_env()
    except AgnesError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        job = Job.open(experiment_name, case)
    except KeyError:
        print(f"未知实验或案例 {experiment_name} {case}", file=sys.stderr)
        return 2
    try:
        session = run_session(job, client)
    except AgnesError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    dest = write_evidence(session, job)
    print(
        json.dumps(
            {
                "experiment": experiment_name,
                "accepted": session["accepted"],
                "evidence": str(dest),
            },
            ensure_ascii=False,
        )
    )
    return 0 if session["accepted"] else 1


def _export(name):
    try:
        selected = _selected(name)
    except KeyError:
        print(f"未知实验 {name}", file=sys.stderr)
        return 2
    for experiment in selected:
        print(experiment.export_table())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
