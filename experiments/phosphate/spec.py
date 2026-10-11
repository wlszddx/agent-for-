from repro.checks import failed_execution, id_list

SLOPE = 0.0486
BLANK = 0.0135
CONCENTRATIONS = (1, 2, 4, 6, 8, 10, 12, 16, 20)
ABS_TOL = 1e-4
SEALED_TOKENS = ("0.0486", "0.0135")
INSTRUCTIONS = (
    "净吸光度等于 absorbance_raw 减去 blank。"
    "浓度使用 concentration_mg_l，"
    "标定行是 concentration_mg_l 不高于 10 的记录。"
    "不要在源码中写入猜测的斜率常数。"
)


def measurements():
    rows = []
    for index, concentration in enumerate(CONCENTRATIONS, start=1):
        rows.append(
            {
                "run_id": index,
                "concentration_mg_l": concentration,
                "concentration_ug_l": concentration * 1000,
                "blank": BLANK,
                "absorbance_raw": SLOPE * concentration + BLANK,
            }
        )
    return rows


def verify(execution, protocol, rows):
    failure = failed_execution(execution)
    if failure:
        return failure
    metrics = execution["metrics"]
    predictions = execution["predictions"]
    reasons = []
    expected_train = [row["run_id"] for row in rows if row["concentration_mg_l"] <= 10]
    expected_test = [row["run_id"] for row in rows if row["concentration_mg_l"] > 10]
    if id_list(metrics.get("train_ids")) != expected_train:
        reasons.append("split_mismatch")
    if id_list(row.get("run_id") for row in predictions) != expected_test:
        reasons.append("holdout_coverage")
    try:
        slope = float(metrics["slope"])
        intercept = float(metrics["intercept"])
    except (KeyError, TypeError, ValueError):
        reasons.append("missing_output")
        return _result(False, reasons, metrics, protocol, rows, None)
    limit = float(protocol["acceptance"]["holdout_rmse_max"])
    rmse = _holdout_rmse(predictions, rows)
    if rmse is None or rmse > limit:
        reasons.append("holdout_rmse")
    if not _parameters_match(predictions, slope, intercept):
        reasons.append("parameter_inconsistent")
    return _result(not reasons, reasons, metrics, protocol, rows, rmse)


def residuals(execution, rows):
    if not execution or not execution.get("predictions"):
        return []
    measured = {row["run_id"]: row for row in rows}
    values = []
    for row in execution["predictions"]:
        run_id = int(row["run_id"])
        observed = measured.get(run_id)
        if observed is None:
            continue
        net = observed["absorbance_raw"] - observed["blank"]
        values.append(
            {
                "run_id": run_id,
                "concentration_mg_l": observed["concentration_mg_l"],
                "abs_error": float(row["absorbance_hat"]) - net,
            }
        )
    return values


def _result(accepted, reasons, metrics, protocol, rows, rmse):
    return {
        "accepted": accepted,
        "reasons": reasons,
        "holdout_rmse": rmse,
        "holdout_rmse_max": protocol["acceptance"]["holdout_rmse_max"],
        "script_holdout_rmse": metrics.get("holdout_rmse") if metrics else None,
        "train_ids": id_list(metrics.get("train_ids")) if metrics else [],
        "expected_train_ids": [
            row["run_id"] for row in rows if row["concentration_mg_l"] <= 10
        ],
        "slope": metrics.get("slope") if metrics else None,
        "intercept": metrics.get("intercept") if metrics else None,
    }


def _holdout_rmse(predictions, rows):
    measured = {row["run_id"]: row for row in rows}
    total = 0.0
    count = 0
    for row in predictions:
        run_id = int(row["run_id"])
        observed = measured.get(run_id)
        if observed is None:
            return None
        net = observed["absorbance_raw"] - observed["blank"]
        total += (float(row["absorbance_hat"]) - net) ** 2
        count += 1
    if count == 0:
        return None
    return (total / count) ** 0.5


def _parameters_match(predictions, slope, intercept):
    for row in predictions:
        expected = slope * float(row["concentration_mg_l"]) + intercept
        if abs(float(row["absorbance_hat"]) - expected) > ABS_TOL:
            return False
    return True
