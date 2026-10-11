import csv
import json
import math
from pathlib import Path

R = 8.314462618


def run(data_path, out_dir):
    rows = _load(data_path)
    for row in rows:
        row["T"] = row["temperature_c"]
        row["lnk"] = math.log(row["k_per_s"])
    train = [row for row in rows if row["temperature_c"] <= 50]
    test = [row for row in rows if row["temperature_c"] > 50]
    _write(train, test, out_dir)


def _load(data_path):
    with open(data_path, newline="", encoding="utf-8") as handle:
        parsed = []
        for row in csv.DictReader(handle):
            parsed.append(
                {
                    "run_id": int(row["run_id"]),
                    "temperature_c": float(row["temperature_c"]),
                    "k_per_s": float(row["k_per_s"]),
                    "k_per_min": float(row["k_per_min"]),
                }
            )
    return parsed


def _fit(train):
    xs = [1.0 / row["T"] for row in train]
    ys = [row["lnk"] for row in train]
    count = float(len(xs))
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    det = count * sxx - sx * sx
    slope = (count * sxy - sx * sy) / det
    intercept = (sy - slope * sx) / count
    return slope, intercept


def _write(train, test, out_dir):
    slope, intercept = _fit(train)
    ea = -slope * R
    ln_a = intercept
    predictions = []
    error = 0.0
    for row in test:
        ln_hat = ln_a - ea / (R * row["T"])
        error += (ln_hat - row["lnk"]) ** 2
        predictions.append(
            {
                "run_id": row["run_id"],
                "temperature_c": row["temperature_c"],
                "k_hat_per_s": math.exp(ln_hat),
            }
        )
    rmse = math.sqrt(error / len(test))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(
        json.dumps(
            {
                "ea_j_mol": ea,
                "ln_a": ln_a,
                "train_ids": [row["run_id"] for row in train],
                "test_ids": [row["run_id"] for row in test],
                "holdout_ln_rmse": rmse,
            }
        ),
        encoding="utf-8",
    )
    with (out / "predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["run_id", "temperature_c", "k_hat_per_s"]
        )
        writer.writeheader()
        for row in predictions:
            writer.writerow(
                {
                    "run_id": row["run_id"],
                    "temperature_c": row["temperature_c"],
                    "k_hat_per_s": f"{row['k_hat_per_s']:.16g}",
                }
            )
