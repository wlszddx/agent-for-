_RADICAL = (
    "·oh",
    "•oh",
    "∙oh",
    "羟基自由基",
    "hydroxyl radical",
    "oh radical",
    "pulse radiolysis",
    "pulseradiolysis",
    "flash photolysis",
    "radiolysis",
    "辐解",
    "脉冲辐解",
    "闪光光解",
    "eaq",
    "so4·",
    "h·",
    "h•",
)
_SAPONIFICATION = (
    "皂化",
    "saponification",
    "naoh",
    "氢氧化钠",
    "氢氧根",
    "hydroxide",
    "oh-",
    "oh−",
)


def is_radical(text):
    folded = _fold(text)
    return any(mark in folded for mark in _RADICAL)


def is_saponification(text):
    folded = _fold(text)
    return any(mark in folded for mark in _SAPONIFICATION)


def same_reaction(report, evidence, experiment=""):
    left = f"{experiment or ''} {report or ''}"
    right = evidence or ""
    left_radical = is_radical(left)
    right_radical = is_radical(right)
    left_saponification = is_saponification(left)
    right_saponification = is_saponification(right)
    if left_saponification and right_radical and not left_radical:
        return False
    if left_radical and right_saponification and not right_radical:
        return False
    return None


def keep_solution_record(text, family):
    if family == "saponification" and is_radical(text):
        return False
    return True


def _fold(text):
    return "".join((text or "").split()).casefold()
