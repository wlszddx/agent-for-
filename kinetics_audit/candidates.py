import re

from kinetics_audit.numbers import measurements, number_tokens
from kinetics_audit.vectors import chunk_sentences

_EQUAL = ("等浓度", "等初浓度", "浓度相等", "等物质的量浓度", "[A]0=[B]0", "a0=b0")
_METHOD = ("摄氏", "热力学温度", "开尔文", "拟合", "代入")
_DILUTION = ("母液", "定容", "移取", "稀释", "工作浓度")
_ARITH = ("相加", "得到", "等于", "计算", "+", "×", "*", "/", "÷")
_RATE_MARK = ("速率常数", "活化能", "k(", "k（", "k=", "k＝", "ea(", "ea（", "e_a")
_K_ASSIGN = re.compile(
    r"k\s*[（(][^）)]{0,24}[）)]\s*[=＝:：]\s*\d+(?:\.\d+)?",
    re.I,
)
_C0_ASSIGN = re.compile(
    r"c\s*0\s*[（(][^）)]{0,16}[）)]\s*[=＝:：]\s*\d+(?:\.\d+)?",
    re.I,
)


def propose_from_report(text, experiment=""):
    pieces = chunk_sentences(text or "", limit=80)
    windows = list(pieces)
    for blob in _table_windows(text or ""):
        windows.append({"text": blob})
    for blob in _kinetics_spans(text or ""):
        windows.append({"text": blob})
    found = []
    seen = set()
    for index, piece in enumerate(windows):
        quote = piece["text"]
        key = _compact(quote)
        if key in seen:
            continue
        kinds = _kinds(quote)
        if not kinds:
            continue
        # PDF 全文糊成一块时，丢掉超长候选，避免模型无法点选
        if len(key) > 360 and "k(" not in key and "速率常数" not in quote and "活化能" not in quote:
            continue
        if len(key) > 360:
            continue
        seen.add(key)
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
                    "quote": blob[:500],
                    "kinds": kinds,
                    "numbers": [item["number"] for item in measurements(blob)] or number_tokens(blob),
                }
            )
    return found


_RECOMMENDED_VALUE = re.compile(
    r"^(?:文献报道)?在\s*(?P<dosage>\d+(?:\.\d+)?\s*mol/L)\s*[、,]\s*"
    r"(?P<temperature>\d+(?:\.\d+)?摄氏度)\s*[、,]\s*(?P<method>电导法|分光光度法|停流法)"
    r".{0,12}速率常数为\s*(?P<number>\d+(?:\.\d+)?)",
)


def recommended_claims(candidates):
    """从短候选自动生成可通过校验的 value 主张草稿，供模型直接 extract。"""
    drafts = []
    seen_k = set()
    for item in candidates or []:
        quote = (item.get("quote") or "").strip()
        if "速率常数" not in quote or len(quote) > 160:
            continue
        match = _RECOMMENDED_VALUE.search(quote.replace("\n", " "))
        if not match:
            continue
        number = match.group("number")
        if number in seen_k:
            continue
        seen_k.add(number)
        drafts.append(
            {
                "id": f"auto_k_{number.replace('.', '_')}",
                "kind": "value",
                "quote": quote,
                "candidate_id": item["id"],
                "quantity": "速率常数",
                "dosage": match.group("dosage").strip(),
                "temperature": match.group("temperature"),
                "method": match.group("method"),
            }
        )
    return drafts


def _table_windows(text):
    lines = [" ".join(line.split()) for line in (text or "").splitlines()]
    lines = [line for line in lines if len(_compact(line)) >= 4]
    windows = []
    for size in (2, 3, 4):
        for index in range(0, max(0, len(lines) - size + 1)):
            chunk = lines[index : index + size]
            if not any(mark in " ".join(chunk).casefold() for mark in ("k(", "k（", "k=", "速率", "活化", "c0", "mol")):
                continue
            blob = " ".join(chunk)
            if 8 <= len(_compact(blob)) <= 240:
                windows.append(blob)
    return windows


def _kinetics_spans(text):
    """PDF 常无换行：在 k(...)= / c0(...)= 附近切出短窗口。"""
    text = text or ""
    spans = []
    for match in _K_ASSIGN.finditer(text):
        start = max(0, match.start() - 120)
        end = min(len(text), match.end() + 40)
        # 尽量把前方的 c0 一并纳入
        head = text[start : match.start()]
        c0 = None
        for item in _C0_ASSIGN.finditer(head):
            c0 = item
        if c0 is not None:
            start = max(0, c0.start() - 20)
        blob = " ".join(text[start:end].split())
        if 8 <= len(_compact(blob)) <= 280:
            spans.append(blob)
    return spans


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
    folded = quote.casefold()
    if (
        "速率常数" in quote
        or "活化能" in quote
        or rates
        or energies
        or any(mark in folded for mark in _RATE_MARK)
    ):
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
    if ("→" in quote or "->" in quote) and ("速率" in quote or concentrations or rates):
        if "calculation" not in kinds:
            kinds.append("calculation")
    if number_tokens(quote) and any(mark in quote for mark in _ARITH):
        if "calculation" not in kinds:
            kinds.append("calculation")
    return kinds


def _compact(text):
    return "".join((text or "").split()).casefold()
