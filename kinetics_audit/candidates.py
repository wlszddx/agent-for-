from kinetics_audit.numbers import measurements, number_tokens
from kinetics_audit.vectors import chunk_sentences

_EQUAL = ("等浓度", "等初浓度", "浓度相等", "等物质的量浓度", "[A]0=[B]0", "a0=b0")
_METHOD = ("摄氏", "热力学温度", "开尔文", "拟合", "代入")
_DILUTION = ("母液", "定容", "移取", "稀释", "工作浓度")
_ARITH = ("相加", "得到", "等于", "计算", "+", "×", "*", "/", "÷")


def propose_from_report(text, experiment=""):
    pieces = chunk_sentences(text or "", limit=80)
    found = []
    for index, piece in enumerate(pieces):
        quote = piece["text"]
        kinds = _kinds(quote)
        if not kinds:
            continue
        found.append(
            {
                "id": f"c{index}",
                "quote": quote,
                "kinds": kinds,
                "numbers": [item["number"] for item in measurements(quote)] or number_tokens(quote),
            }
        )
    if not found and (text or "").strip():
        blob = " ".join((text or "").split())
        if len(_compact(blob)) >= 8:
            kinds = _kinds(blob) or ["value"]
            found.append(
                {
                    "id": "c0",
                    "quote": blob,
                    "kinds": kinds,
                    "numbers": [item["number"] for item in measurements(blob)] or number_tokens(blob),
                }
            )
    return found


def match_candidate(candidates, candidate_id=None, quote=None):
    if candidate_id is not None:
        if not isinstance(candidate_id, str):
            return None
        hit = next((item for item in candidates if item["id"] == candidate_id), None)
        if hit is not None:
            return hit
    if not isinstance(quote, str) or not quote.strip():
        return None
    needle = _compact(quote)
    for item in candidates:
        window = _compact(item["quote"])
        if not window:
            continue
        if needle == window or needle in window or window in needle:
            return item
    return None


def _kinds(quote):
    kinds = []
    found = measurements(quote)
    concentrations = [item for item in found if item["dimension"] == "molar_concentration"]
    volumes = [item for item in found if item["dimension"] == "volume"]
    temperatures = [item for item in found if item["dimension"] == "temperature"]
    rates = [item for item in found if item["dimension"] in {"frequency", "second_order_rate"}]
    energies = [item for item in found if item["dimension"] == "energy"]
    if "速率常数" in quote or "活化能" in quote:
        kinds.append("value")
    if any(mark in quote for mark in _METHOD):
        kinds.append("method")
    if len(concentrations) >= 2 and len(volumes) >= 2:
        kinds.append("calculation")
    elif any(mark in quote for mark in _DILUTION) and concentrations and volumes:
        kinds.append("calculation")
    if any(mark in quote for mark in _EQUAL) and len(concentrations) >= 2:
        if "calculation" not in kinds:
            kinds.append("calculation")
    if len(temperatures) >= 2 and len(rates) >= 2 and energies:
        if "calculation" not in kinds:
            kinds.append("calculation")
    if ("→" in quote or "->" in quote) and ("速率" in quote or concentrations):
        if "calculation" not in kinds:
            kinds.append("calculation")
    if number_tokens(quote) and any(mark in quote for mark in _ARITH):
        if "calculation" not in kinds:
            kinds.append("calculation")
    return kinds


def _compact(text):
    return "".join((text or "").split()).casefold()
