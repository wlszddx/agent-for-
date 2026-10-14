import ast
import re

_NUMBER = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?![\d.])")
_LABELED = re.compile(
    r"([A-Za-z](?:\s*[A-Za-z0-9₀₁₂₃])*)\s*[（(]([^）)]{1,32})[）)]\s*[=＝:：]\s*"
    r"(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
)
_CONDITION_SPLIT = re.compile(r"[，,、；;。\s]+")
_TOLERANCE = {
    "energy": 0.15,
    "mass_concentration": 0.05,
    "molar_concentration": 0.05,
    "frequency": 0.10,
    "second_order_rate": 0.10,
    "reaction_rate": 0.01,
    "temperature": 0.01,
    "fraction": 0.10,
}
_APPROX_FACTOR = 1.6
_UNITS = [
    ("kj/mol", "kJ/mol", "energy", ("factor", 1000.0)),
    ("kcal/mol", "kcal/mol", "energy", ("factor", 4184.0)),
    ("j/mol", "J/mol", "energy", ("factor", 1.0)),
    ("千焦每摩尔", "kJ/mol", "energy", ("factor", 1000.0)),
    ("千焦/摩尔", "kJ/mol", "energy", ("factor", 1000.0)),
    ("mg/l", "mg/L", "mass_concentration", ("factor", 1.0)),
    ("μg/l", "ug/L", "mass_concentration", ("factor", 0.001)),
    ("ug/l", "ug/L", "mass_concentration", ("factor", 0.001)),
    ("毫克每升", "mg/L", "mass_concentration", ("factor", 1.0)),
    ("mol/(l·s)", "mol/(L·s)", "reaction_rate", ("factor", 1.0)),
    ("mol/(l·min)", "mol/(L·min)", "reaction_rate", ("factor", 1.0 / 60.0)),
    ("mol/l/s", "mol/(L·s)", "reaction_rate", ("factor", 1.0)),
    ("mol/l/min", "mol/(L·min)", "reaction_rate", ("factor", 1.0 / 60.0)),
    ("mmol/l", "mmol/L", "molar_concentration", ("factor", 0.001)),
    ("mol/l", "mol/L", "molar_concentration", ("factor", 1.0)),
    ("摩尔每升", "mol/L", "molar_concentration", ("factor", 1.0)),
    ("l/(mol·s)", "L/(mol·s)", "second_order_rate", ("factor", 1.0)),
    ("l/(mol·min)", "L/(mol·min)", "second_order_rate", ("factor", 1.0 / 60.0)),
    ("l/mol/s", "L/(mol·s)", "second_order_rate", ("factor", 1.0)),
    ("l/mol/min", "L/(mol·min)", "second_order_rate", ("factor", 1.0 / 60.0)),
    ("l/mol·s", "L/(mol·s)", "second_order_rate", ("factor", 1.0)),
    ("l/mol·min", "L/(mol·min)", "second_order_rate", ("factor", 1.0 / 60.0)),
    ("l·mol^-1·s^-1", "L/(mol·s)", "second_order_rate", ("factor", 1.0)),
    ("l·mol^-1·min^-1", "L/(mol·min)", "second_order_rate", ("factor", 1.0 / 60.0)),
    ("min^-1", "min^-1", "frequency", ("factor", 1.0 / 60.0)),
    ("s^-1", "s^-1", "frequency", ("factor", 1.0)),
    ("毫升", "mL", "volume", ("factor", 0.001)),
    ("ml", "mL", "volume", ("factor", 0.001)),
    ("升", "L", "volume", ("factor", 1.0)),
    ("l", "L", "volume", ("factor", 1.0)),
    ("摄氏度", "°C", "temperature", ("affine", 1.0, 273.15)),
    ("℃", "°C", "temperature", ("affine", 1.0, 273.15)),
    ("°c", "°C", "temperature", ("affine", 1.0, 273.15)),
    ("开尔文", "K", "temperature", ("affine", 1.0, 0.0)),
    ("k", "K", "temperature", ("affine", 1.0, 0.0)),
    ("%", "%", "fraction", ("factor", 0.01)),
]
_RATE_ANCHOR = re.compile(r"速率常数|rate\s*constant|(?<![A-Za-z])k(?=\s*[（(=：:])", re.I)
_ENERGY_ANCHOR = re.compile(r"活化能|activation\s*energy|(?<![A-Za-z])e_?a(?=\s*[（(=：:])", re.I)


def number_tokens(text):
    return [match.group(1) for match in _NUMBER.finditer(text or "")]


def measurements(text):
    text = text or ""
    found = []
    seen = set()
    for match in _NUMBER.finditer(text):
        unit = _unit_at(text[match.end() :])
        if unit is None:
            continue
        item = _measurement(text, match.group(1), match.start(), match.end(), unit)
        key = (item["start"], item["end"], item["unit"])
        if key in seen:
            continue
        seen.add(key)
        found.append(item)
    for match in _LABELED.finditer(text):
        unit = _unit_lookup(match.group(2))
        if unit is None:
            continue
        number = match.group(3)
        start = match.start(3)
        end = match.end(3)
        item = _measurement(text, number, start, end, unit)
        key = (item["start"], item["end"], item["unit"])
        if key in seen:
            continue
        seen.add(key)
        found.append(item)
    found.sort(key=lambda item: item["start"])
    return found


def near_quantity(text, quantity, items, quantity_kind=None):
    places = quantity_places(text, quantity, quantity_kind)
    if not places:
        return []
    picked = []
    for item in items:
        after = min(item["start"] - place for place in places)
        before = min(place - item["end"] for place in places)
        if 0 <= after <= 40 or 0 <= before <= 24:
            picked.append(item)
    return picked


def closest(text, quantity, items, quantity_kind=None):
    places = quantity_places(text, quantity, quantity_kind)
    if not items or not places:
        return None

    def distance(item):
        return min(abs(item["start"] - place) for place in places)

    return min(items, key=distance)


def quantity_places(text, quantity, quantity_kind=None):
    text = text or ""
    places = []
    if quantity:
        places.extend(_find_all(text, quantity))
    pattern = None
    if quantity_kind == "rate":
        pattern = _RATE_ANCHOR
    elif quantity_kind == "activation_energy":
        pattern = _ENERGY_ANCHOR
    if pattern is not None:
        places.extend(match.start() for match in pattern.finditer(text))
    return sorted(set(places))


def tolerance(dimension, approximate):
    base = _TOLERANCE[dimension]
    if approximate:
        return base * _APPROX_FACTOR
    return base


def conditions_covered(conditions, evidence):
    tokens = [token for token in _CONDITION_SPLIT.split(conditions.strip()) if len(_compact(token)) >= 2]
    if not tokens:
        return False
    compact_evidence = _compact(evidence)
    return all(_compact(token) in compact_evidence for token in tokens)


def compare_quantity(
    report_text,
    evidence_text,
    quantity,
    conditions,
    enforce_conditions=True,
    accepted_dimensions=(),
    quantity_kind=None,
):
    reported_items = near_quantity(report_text, quantity, measurements(report_text), quantity_kind)
    evidence_items = near_quantity(evidence_text, quantity, measurements(evidence_text), quantity_kind)
    if not evidence_items and accepted_dimensions:
        evidence_items = [item for item in measurements(evidence_text) if item["dimension"] in accepted_dimensions]
    if not reported_items and accepted_dimensions:
        reported_items = [item for item in measurements(report_text) if item["dimension"] in accepted_dimensions]
    if not reported_items:
        return {"status": "not_enough", "reason": "reported_number_missing"}
    if not evidence_items:
        return {"status": "not_enough", "reason": "reference_number_missing"}
    if enforce_conditions and not conditions_covered(conditions, evidence_text):
        return {"status": "not_comparable", "reason": "conditions"}
    reported = closest(report_text, quantity, reported_items, quantity_kind)
    refs = [item for item in evidence_items if item["dimension"] == reported["dimension"]]
    if not refs:
        return {"status": "not_comparable", "reason": "incompatible_units"}
    approximate = any(item["approximate"] for item in refs)
    allowed = tolerance(reported["dimension"], approximate)
    bases = [item["base"] for item in refs]
    low, high = min(bases), max(bases)
    if low <= reported["base"] <= high:
        gap = 0.0
        reference = closest(evidence_text, quantity, refs, quantity_kind) or min(
            refs, key=lambda item: abs(item["base"] - reported["base"])
        )
        status = "supports"
    else:
        endpoint = low if reported["base"] < low else high
        reference = min(refs, key=lambda item: abs(item["base"] - endpoint))
        gap = abs(reported["base"] - endpoint) / max(abs(endpoint), 1e-12)
        status = "supports" if gap <= allowed else "contradicts"
    return {
        "status": status,
        "quantity": quantity,
        "reported": reported["number"],
        "reported_unit": reported["unit"],
        "reference": reference["number"],
        "reference_unit": reference["unit"],
        "reference_base": reference["base"],
        "relative_difference": gap,
        "tolerance": allowed,
        "approximate": approximate,
    }


def evaluate_expression(expression, quote):
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 200:
        raise ValueError("expression")
    tokens = set(number_tokens(quote))
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("expression") from exc
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd)):
            raise ValueError("expression")
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("expression")
            literal = ast.get_source_segment(expression, node)
            if literal not in tokens:
                raise ValueError("number_not_in_quote")
    try:
        value = eval(compile(tree, "<calc>", "eval"), {"__builtins__": {}}, {})
    except ZeroDivisionError as exc:
        raise ValueError("expression") from exc
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expression")
    return float(value)


def calculation_status(computed, reported):
    try:
        reported_value = float(reported)
    except ValueError as exc:
        raise ValueError("reported") from exc
    scale = max(abs(computed), abs(reported_value), 1e-12)
    gap = abs(computed - reported_value) / scale
    status = "supports" if gap <= 1e-4 else "contradicts"
    return {"status": status, "computed": computed, "reported": reported, "relative_difference": gap}


def _unit_at(rest):
    folded = (rest or "").lstrip().casefold()
    for prefix, canonical, dimension, spec in _UNITS:
        for needle in (prefix, prefix.replace("·", "/")):
            if not folded.startswith(needle):
                continue
            after = folded[len(needle) :]
            # 避免把 k(L/mol/min) 里的 k 误当成开尔文
            if needle == "k" and after[:1] in {"(", "（", "=", "＝", ":", "："}:
                continue
            if after[:1] and after[0].isascii() and after[0].isalnum():
                continue
            return canonical, dimension, spec
    return None


def _unit_lookup(token):
    folded = (token or "").strip().casefold().replace(" ", "")
    folded = folded.replace("·", "/").replace("•", "/").replace("⋅", "/")
    for prefix, canonical, dimension, spec in _UNITS:
        needle = prefix.replace("·", "/")
        if folded != needle and not folded.startswith(needle):
            continue
        if folded != needle:
            after = folded[len(needle) :]
            if after[:1] and after[0].isascii() and after[0].isalnum():
                continue
        return canonical, dimension, spec
    return None


def _measurement(text, number, start, end, unit):
    canonical, dimension, spec = unit
    return {
        "number": number,
        "start": start,
        "end": end,
        "unit": canonical,
        "dimension": dimension,
        "base": _to_base(float(number), spec),
        "approximate": _approximate(text, start),
    }


def _to_base(value, spec):
    if spec[0] == "factor":
        return value * spec[1]
    return value * spec[1] + spec[2]


def _approximate(text, start):
    window = text[max(0, start - 6) : start + 8]
    return any(mark in window for mark in ("约", "大约", "接近", "左右"))


def _find_all(text, piece):
    places = []
    start = 0
    while True:
        found = text.find(piece, start)
        if found < 0:
            return places
        places.append(found)
        start = found + len(piece)


def _compact(text):
    return "".join(text.split()).casefold()
