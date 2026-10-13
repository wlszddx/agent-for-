import math
import re

from repro.numbers import measurements, tolerance

R = 8.314462618
_INDEPENDENT = ("与用量无关", "与浓度无关", "不随浓度", "不随用量", "与反应物浓度无关")
_CONCENTRATION = {"molar_concentration", "mass_concentration"}
_METHOD_GROUPS = (
    ("电导", "电导率", "电导法", "conductivity", "conductance", "conductometric"),
    ("脉冲辐解", "pulse radiolysis", "pulseradiolysis"),
    ("闪光光解", "flash photolysis", "flashphotolysis"),
    ("停流", "stopped flow", "stopped-flow"),
    ("分光", "spectrophot", "分光光度"),
)
_RATE_DIMENSIONS = ("frequency", "second_order_rate")
_ENERGY_DIMENSIONS = ("energy",)


def quantity_kind(name):
    text = name or ""
    if "活化能" in text:
        return "activation_energy"
    if "速率常数" in text:
        return "rate"
    return None


def accepted_dimensions(kind):
    if kind == "rate":
        return _RATE_DIMENSIONS
    if kind == "activation_energy":
        return _ENERGY_DIMENSIONS
    return ()


def comparable(kind, claim, evidence):
    if kind == "activation_energy" and any(phrase in evidence for phrase in _INDEPENDENT):
        return True, "independent", ()
    missing = []
    if not _same_measurement(claim["temperature"], evidence, {"temperature"}):
        missing.append("温度")
    if not _same_method(claim["method"], evidence):
        missing.append("测定方法")
    if missing:
        return False, "conditions", tuple(missing)
    return True, "matched", ()


def setup_issue(claim):
    groups = _method_groups(claim.get("method") or "")
    if "电导" not in groups:
        return None
    amounts = [
        item
        for item in measurements(claim.get("dosage") or "")
        if item["dimension"] == "molar_concentration"
    ]
    if not amounts or amounts[0]["base"] <= 0.20:
        return None
    amount = amounts[0]
    return {
        "status": "contradicts",
        "reason": "setup",
        "quantity": claim["quantity"],
        "statement": (
            f"电导法把电导率近似看成与浓度成正比，只适用于稀溶液。"
            f"报告用量为 {amount['number']} {amount['unit']}，高于 0.20 mol/L，这一步的条件不合理。"
            f"报告写「{claim['quote']}」。"
        ),
        "kind": "value",
    }


def expected_rate(quote, equation, reported):
    if not isinstance(equation, str) or _compact(equation) not in _compact(quote):
        raise ValueError("equation_required")
    reactants = _reactants(equation)
    order = sum(coeff for coeff, _name in reactants)
    found = measurements(quote)
    constants = [item for item in found if item["dimension"] in {"frequency", "second_order_rate"}]
    concentrations = [item for item in found if item["dimension"] == "molar_concentration"]
    rates = [item for item in found if item["dimension"] == "reaction_rate" and item["number"] == reported]
    if len(constants) != 1 or not rates:
        raise ValueError("rate_law_data_required")
    constant = constants[0]
    if (constant["dimension"] == "frequency" and order != 1) or (constant["dimension"] == "second_order_rate" and order != 2):
        raise ValueError("rate_law_data_required")
    if len(concentrations) == len(reactants):
        values = [item["base"] for item in concentrations]
    elif len(concentrations) == 1:
        values = [concentrations[0]["base"]] * len(reactants)
    else:
        raise ValueError("rate_law_data_required")
    computed_base = constant["base"]
    for (coeff, _name), value in zip(reactants, values):
        computed_base *= value ** coeff
    target = rates[0]
    gap = abs(computed_base - target["base"]) / max(abs(computed_base), 1e-12)
    factor = target["base"] / float(target["number"])
    return {
        "status": "supports" if gap <= 0.01 else "contradicts",
        "computed": computed_base / factor,
        "computed_unit": target["unit"],
        "reported": reported,
        "relative_difference": gap,
    }


def _reactants(equation):
    left = re.split(r"→|->|=>|＝|=", equation, maxsplit=1)[0]
    reactants = []
    for term in left.split("+"):
        piece = " ".join(term.split())
        match = re.fullmatch(r"(\d+)\s*([A-Za-z].+)", piece)
        if match:
            reactants.append((int(match.group(1)), match.group(2)))
        elif piece:
            reactants.append((1, piece))
    if not reactants:
        raise ValueError("rate_law_data_required")
    return reactants


def dosage_differs(claim_text, evidence):
    return _same_measurement(claim_text, evidence, _CONCENTRATION) is False and bool(
        [item for item in measurements(claim_text) if item["dimension"] in _CONCENTRATION]
        and [item for item in measurements(evidence) if item["dimension"] in _CONCENTRATION]
    )


def arrhenius_ea(quote, reported):
    temperatures = sorted(
        (item for item in measurements(quote) if item["dimension"] == "temperature"),
        key=lambda item: item["start"],
    )
    rates = _rate_series(quote)
    reported_items = [
        item
        for item in measurements(quote)
        if item["dimension"] == "energy" and item["number"] == reported
    ]
    if len(temperatures) < 2 or len(temperatures) != len(rates) or not reported_items:
        raise ValueError("arrhenius_data_required")
    xs = []
    ys = []
    for temperature, rate in zip(temperatures, rates):
        if temperature["base"] <= 0 or rate["base"] <= 0:
            raise ValueError("arrhenius_data_required")
        xs.append(1.0 / temperature["base"])
        ys.append(math.log(rate["base"]))
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    variance = sum((item - mean_x) ** 2 for item in xs)
    if variance == 0:
        raise ValueError("arrhenius_data_required")
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / variance
    computed_base = -slope * R
    target = reported_items[0]
    gap = abs(computed_base - target["base"]) / max(abs(computed_base), 1e-12)
    factor = target["base"] / float(target["number"])
    return {
        "status": "supports" if gap <= 0.01 else "contradicts",
        "computed": computed_base / factor,
        "computed_unit": target["unit"],
        "reported": reported,
        "relative_difference": gap,
    }


def _rate_series(quote):
    found = measurements(quote)
    second = [item for item in found if item["dimension"] == "second_order_rate"]
    if len(second) >= 2:
        return sorted(second, key=lambda item: item["start"])
    return sorted((item for item in found if item["dimension"] == "frequency"), key=lambda item: item["start"])


def _compact(text):
    return "".join(text.split()).casefold()


def _same_measurement(claim_text, evidence, dimensions):
    claim_items = [item for item in measurements(claim_text) if item["dimension"] in dimensions]
    evidence_items = [item for item in measurements(evidence) if item["dimension"] in dimensions]
    if claim_items and evidence_items:
        for left in claim_items:
            same = [item for item in evidence_items if item["dimension"] == left["dimension"]]
            allowed = tolerance(left["dimension"], any(item["approximate"] for item in same))
            for right in same:
                gap = abs(left["base"] - right["base"]) / max(abs(right["base"]), 1e-12)
                if gap <= allowed:
                    return True
        return False
    return _compact(claim_text) in _compact(evidence)


def _method_groups(text):
    compact = _compact(text)
    return [group[0] for group in _METHOD_GROUPS if any(_compact(alias) in compact for alias in group)]


def _same_method(claim_text, evidence):
    claim_groups = _method_groups(claim_text)
    evidence_groups = _method_groups(evidence)
    if claim_groups and evidence_groups:
        return any(group in evidence_groups for group in claim_groups)
    if claim_groups:
        return False
    return _compact(claim_text) in _compact(evidence)
