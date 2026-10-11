import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from repro.table import read_rows, write_rows

DRIVER = r"""
import builtins
import pathlib

ROOT = pathlib.Path.cwd().resolve()
_open = builtins.open


def guarded(file, *args, **kwargs):
    path = pathlib.Path(file)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if path != ROOT and ROOT not in path.parents:
        raise PermissionError(str(path))
    return _open(path, *args, **kwargs)


builtins.open = guarded

from analysis import run

run(str(ROOT / "data.csv"), str(ROOT / "out"))
"""


def execute(source, rows):
    root = Path(tempfile.mkdtemp(prefix="repro-"))
    (root / "analysis.py").write_text(source, encoding="utf-8")
    (root / "driver.py").write_text(DRIVER, encoding="utf-8")
    (root / "out").mkdir()
    write_rows(root / "data.csv", rows)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "PATHEXT": os.environ.get("PATHEXT", ""),
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    try:
        completed = subprocess.run(
            [sys.executable, "driver.py"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": 124,
            "timed_out": True,
            "stdout": _text(exc.stdout),
            "stderr": _text(exc.stderr),
            "metrics": None,
            "predictions": None,
        }
    metrics = None
    predictions = None
    metrics_path = root / "out" / "metrics.json"
    predictions_path = root / "out" / "predictions.csv"
    if metrics_path.is_file() and predictions_path.is_file():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        predictions = read_rows(predictions_path)
    return {
        "exit_code": completed.returncode,
        "timed_out": False,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
        "metrics": metrics,
        "predictions": predictions,
    }


def _text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[-4000:]
    return str(value)[-4000:]
