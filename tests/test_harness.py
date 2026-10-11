import json
import unittest
from pathlib import Path

from repro.catalog import experiment_names, load
from repro.guard import GuardError, check_source
from repro.sandbox import execute
from repro.session import run_session
from repro.tools import Job, dispatch


class RepairClient:
    def __init__(self, source):
        self.source = source
        self.phase = 0

    def complete(self, messages, tools):
        self.phase += 1
        if self.phase == 1:
            return self._call("run_experiment", {})
        if self.phase == 2:
            return self._call("verify_run", {})
        if self.phase == 3:
            return self._call("write_analysis", {"source": self.source})
        if self.phase == 4:
            return self._call("run_experiment", {})
        if self.phase == 5:
            return self._call("verify_run", {})
        return {"content": "done", "tool_calls": []}

    def _call(self, name, arguments):
        return {
            "content": "",
            "tool_calls": [
                {"id": f"call_{self.phase}", "name": name, "arguments": arguments}
            ],
        }


class HarnessTest(unittest.TestCase):
    def test_two_experiments(self):
        self.assertEqual(experiment_names(), ["hydrolysis", "phosphate"])
        for name in experiment_names():
            experiment = load(name)
            self.assertIn("correct", experiment.case_names())
            for case in experiment.case_names():
                job = Job.open(name, case)
                dispatch(job, "run_experiment", {})
                result = dispatch(job, "verify_run", {})
                if case == "correct":
                    self.assertTrue(result["accepted"], (name, result))
                else:
                    self.assertFalse(result["accepted"], (name, result))
                    self.assertTrue(result["reasons"])

    def test_leakage_is_only_split(self):
        for name, rmse_key in (
            ("hydrolysis", "holdout_ln_rmse"),
            ("phosphate", "holdout_rmse"),
        ):
            job = Job.open(name, "leakage")
            dispatch(job, "run_experiment", {})
            result = dispatch(job, "verify_run", {})
            self.assertEqual(result["reasons"], ["split_mismatch"], (name, result))
            self.assertLess(result[rmse_key], 0.02)

    def test_protocol_hides_sealed_constants(self):
        hydrolysis = json.dumps(load("hydrolysis").protocol())
        phosphate = json.dumps(load("phosphate").protocol())
        self.assertNotIn("48500", hydrolysis)
        self.assertNotIn("0.0486", phosphate)

    def test_sealed_constants_belong_to_one_experiment(self):
        leaked = "def run(data_path, out_dir):\n    ea = 48500\n"
        hydrolysis = dispatch(
            Job.open("hydrolysis", "celsius"),
            "write_analysis",
            {"source": leaked},
        )
        phosphate = dispatch(
            Job.open("phosphate", "leakage"),
            "write_analysis",
            {"source": leaked},
        )
        self.assertFalse(hydrolysis["ok"])
        self.assertTrue(phosphate["ok"])

    def test_guard_blocks_import(self):
        with self.assertRaises(GuardError):
            check_source("import os\ndef run(data_path, out_dir):\n    pass\n")

    def test_sandbox_blocks_parent_read(self):
        source = (
            "def run(data_path, out_dir):\n"
            "    open('../outside.txt', encoding='utf-8').read()\n"
        )
        result = execute(source, [{"run_id": 1, "value": 1}])
        self.assertNotEqual(result["exit_code"], 0)

    def test_repair_loop_accepts_only_after_verifier(self):
        root = Path(__file__).resolve().parents[1]
        fixed = (
            root / "experiments" / "phosphate" / "cases" / "correct" / "analysis.py"
        ).read_text(encoding="utf-8")
        job = Job.open("phosphate", "microgram")
        session = run_session(job, RepairClient(fixed))
        self.assertEqual(session["experiment"], "phosphate")
        self.assertTrue(session["accepted"])
        verifies = [
            event
            for event in session["trace"]
            if event["type"] == "tool" and event["name"] == "verify_run"
        ]
        self.assertFalse(verifies[0]["result"]["accepted"])
        self.assertTrue(verifies[1]["result"]["accepted"])
        self.assertEqual(session["writes"], 1)


if __name__ == "__main__":
    unittest.main()
