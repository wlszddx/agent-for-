import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ROOT / "experiments"


def experiment_names():
    return sorted(
        path.name
        for path in EXPERIMENTS.iterdir()
        if path.is_dir() and (path / "spec.py").is_file()
    )


def load(name):
    if name not in experiment_names():
        raise KeyError(name)
    module = importlib.import_module(f"experiments.{name}.spec")
    return Experiment(name, module)


class Experiment:
    def __init__(self, name, module):
        self.name = name
        self.module = module
        self.root = EXPERIMENTS / name

    def case_names(self):
        case_dir = self.root / "cases"
        return sorted(
            path.name for path in case_dir.iterdir() if (path / "analysis.py").is_file()
        )

    def case_source(self, case):
        path = self.root / "cases" / case / "analysis.py"
        if not path.is_file():
            raise KeyError(case)
        return path.read_text(encoding="utf-8")

    def protocol(self):
        import json

        return json.loads((self.root / "protocol.json").read_text(encoding="utf-8"))

    def measurements(self):
        return self.module.measurements()

    def verify(self, execution):
        return self.module.verify(execution, self.protocol(), self.measurements())

    def residuals(self, execution):
        return self.module.residuals(execution, self.measurements())

    def sealed_tokens(self):
        return tuple(self.module.SEALED_TOKENS)

    def instructions(self):
        return self.module.INSTRUCTIONS

    def export_table(self):
        from repro.table import write_rows

        path = self.root / "runs.csv"
        write_rows(path, self.measurements())
        return path
