def failed_execution(execution):
    if execution.get("timed_out"):
        return {"accepted": False, "reasons": ["timeout"]}
    if execution.get("exit_code") != 0:
        return {
            "accepted": False,
            "reasons": ["exit_error"],
            "stderr": (execution.get("stderr") or "")[-4000:],
        }
    if not execution.get("metrics") or execution.get("predictions") is None:
        return {"accepted": False, "reasons": ["missing_output"]}
    return None


def id_list(values):
    if not values:
        return []
    return sorted(int(value) for value in values)
