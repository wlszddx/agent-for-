import csv
import json
import math
from pathlib import Path


def run(data_path, out_dir):
    rows = _load(data_path)
    for row in rows:
        row["x"] = row["concentration_ug_l"]
        row["y"] = row["absorbance_raw"] - row["blank"]
    train = [row for row in rows if row["concentration_mg_l"] <= 10]
    test = [row for row in rows if row["concentration_mg_l"] > 10]
    _write(train, test, out_dir)


def _load(data_path):
    with open(data_path, newline="", encoding="utf-8") as handle:
        parsed = []
        for row in csv.DictReader(handle):
            parsed.append(
                {
                    "run_id": int(row["run_id"]),
                    "concentration_mg_l": float(row["concentration_mg_l"]),
                    "concentration_ug_l": float(row["concentration_ug_l"]),
                    "blank": float(row["blank"]),
                    "absorbance_raw": float(row["absorbance_raw"]),
                }
            )
    return parsed


def _fit(train):
    xs = [row["x"] for row in train]
    ys = [row["y"] for row in train]
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
    predictions = []
    error = 0.0
    for row in test:
        hat = slope * row["x"] + intercept
        error += (hat - row["y"]) ** 2
        predictions.append(
            {
                "run_id": row["run_id"],
                "concentration_mg_l": row["concentration_mg_l"],
                "absorbance_hat": hat,
            }
        )
    rmse = math.sqrt(error / len(test))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(
        json.dumps(
            {
                "slope": slope,
                "intercept": intercept,
                "train_ids": [row["run_id"] for row in train],
                "test_ids": [row["run_id"] for row in test],
                "holdout_rmse": rmse,
            }
        ),
        encoding="utf-8",
    )
    with (out / "predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["run_id", "concentration_mg_l", "absorbance_hat"],
        )
        writer.writeheader()
        for row in predictions:
            writer.writerow(
                {
                    "run_id": row["run_id"],
                    "concentration_mg_l": row["concentration_mg_l"],
                    "absorbance_hat": f"{row['absorbance_hat']:.16g}",
                }
            )
