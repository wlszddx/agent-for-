import math

from repro.checks import failed_execution, id_list

R = 8.314462618
EA_J_MOL = 48500.0
A_PER_S = 1.2e6
TEMPERATURES_C = (20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70)
LN_TOL = 1e-4
SEALED_TOKENS = ("48500", "1.2e6", "1200000")
INSTRUCTIONS = (
    "温度拟合使用开尔文，速率使用 k_per_s，"
    "标定行是 temperature_c 不高于 50 的记录。"
    "不要在源码中写入猜测的活化能常数。"
)


def measurements():
    rows = []
    for index, celsius in enumerate(TEMPERATURES_C, start=1):
        kelvin = celsius + 273.15
        k_per_s = A_PER_S * math.exp(-EA_J_MOL / (R * kelvin))
        rows.append(
            {
                "run_id": index,
                "temperature_c": celsius,
                "k_per_s": k_per_s,
                "k_per_min": k_per_s * 60.0,
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
    expected_train = [row["run_id"] for row in rows if row["temperature_c"] <= 50]
    expected_test = [row["run_id"] for row in rows if row["temperature_c"] > 50]
    if id_list(metrics.get("train_ids")) != expected_train:
        reasons.append("split_mismatch")
    if id_list(row.get("run_id") for row in predictions) != expected_test:
        reasons.append("holdout_coverage")
    try:
        ea = float(metrics["ea_j_mol"])
        ln_a = float(metrics["ln_a"])
    except (KeyError, TypeError, ValueError):
        reasons.append("missing_output")
        return _result(False, reasons, metrics, protocol, rows, None)
    gas = float(protocol["R_J_per_mol_K"])
    limit = float(protocol["acceptance"]["holdout_ln_rmse_max"])
    rmse = _holdout_rmse(predictions, rows)
    if rmse is None or rmse > limit:
        reasons.append("holdout_ln_rmse")
    if not _parameters_match(predictions, ea, ln_a, gas):
        reasons.append("parameter_inconsistent")
    return _result(not reasons, reasons, metrics, protocol, rows, rmse)


def residuals(execution, rows):
    if not execution or not execution.get("predictions"):
        return []
    measured = {row["run_id"]: row["k_per_s"] for row in rows}
    values = []
    for row in execution["predictions"]:
        run_id = int(row["run_id"])
        predicted = float(row["k_hat_per_s"])
        observed = measured.get(run_id)
        if predicted <= 0 or not observed:
            continue
        values.append(
            {
                "run_id": run_id,
                "temperature_c": row["temperature_c"],
                "ln_error": math.log(predicted) - math.log(observed),
            }
        )
    return values


def _result(accepted, reasons, metrics, protocol, rows, rmse):
    return {
        "accepted": accepted,
        "reasons": reasons,
        "holdout_ln_rmse": rmse,
        "holdout_ln_rmse_max": protocol["acceptance"]["holdout_ln_rmse_max"],
        "script_holdout_ln_rmse": metrics.get("holdout_ln_rmse") if metrics else None,
        "train_ids": id_list(metrics.get("train_ids")) if metrics else [],
        "expected_train_ids": [row["run_id"] for row in rows if row["temperature_c"] <= 50],
        "ea_j_mol": metrics.get("ea_j_mol") if metrics else None,
        "ln_a": metrics.get("ln_a") if metrics else None,
    }


def _holdout_rmse(predictions, rows):
    measured = {row["run_id"]: row["k_per_s"] for row in rows}
    total = 0.0
    count = 0
    for row in predictions:
        run_id = int(row["run_id"])
        if run_id not in measured:
            return None
        predicted = float(row["k_hat_per_s"])
        observed = measured[run_id]
        if predicted <= 0 or observed <= 0:
            return None
        total += (math.log(predicted) - math.log(observed)) ** 2
        count += 1
    if count == 0:
        return None
    return math.sqrt(total / count)


def _parameters_match(predictions, ea, ln_a, gas):
    for row in predictions:
        predicted = float(row["k_hat_per_s"])
        if predicted <= 0:
            return False
        kelvin = float(row["temperature_c"]) + 273.15
        expected = math.exp(ln_a - ea / (gas * kelvin))
        if abs(math.log(predicted) - math.log(expected)) > LN_TOL:
            return False
    return True
