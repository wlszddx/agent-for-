_SPECIES = (
    ("hydroxylradical", "radical_oh"),
    ("ohradical", "radical_oh"),
    ("羟基自由基", "radical_oh"),
    ("·oh", "radical_oh"),
    ("•oh", "radical_oh"),
    ("∙oh", "radical_oh"),
    ("氢氧化钠", "naoh"),
    ("naoh", "naoh"),
    ("氢氧化钾", "koh"),
    ("koh", "koh"),
    ("氢氧根", "hydroxide"),
    ("hydroxide", "hydroxide"),
    ("oh-", "hydroxide"),
    ("oh−", "hydroxide"),
    ("乙酸乙酯", "ethyl_acetate"),
    ("ethylacetate", "ethyl_acetate"),
    ("ch3cooc2h5", "ethyl_acetate"),
    ("ch3co2c2h5", "ethyl_acetate"),
    ("ch3co2et", "ethyl_acetate"),
    ("etoac", "ethyl_acetate"),
    ("acoet", "ethyl_acetate"),
)

# Literature may name these even when the student report only says 皂化.
_IMPLIED = {
    "saponification": frozenset({"naoh", "koh", "hydroxide", "ethyl_acetate"}),
}

# If literature has these and the report side does not, never compare.
_HOSTILE = frozenset({"radical_oh"})

_FAMILIES = (
    (("皂化", "saponif", "碱催化水解", "碱性水解"), "saponification"),
    (
        (
            "羟基自由基",
            "hydroxylradical",
            "ohradical",
            "·oh",
            "•oh",
            "∙oh",
            "pulseradiolysis",
            "脉冲辐解",
        ),
        "radical_oh",
    ),
)


def same_reaction(report, evidence, experiment=""):
    left_text = f"{experiment or ''} {report or ''}"
    right_text = evidence or ""
    left = species(left_text)
    right = species(right_text)
    left_family = families(left_text)
    right_family = families(right_text)
    allowed = set(left)
    for name in left_family:
        allowed |= _IMPLIED.get(name, frozenset())

    if left_family and right_family and left_family.isdisjoint(right_family):
        return False
    if left and right and left.isdisjoint(right):
        return False
    extras = right - allowed
    if extras & _HOSTILE:
        return False
    if _states_reaction(right_text) and extras:
        return False
    return None


def species(text):
    folded = _fold(text)
    return {canon for alias, canon in _SPECIES if alias in folded}


def families(text):
    folded = _fold(text)
    return {canon for aliases, canon in _FAMILIES if any(alias in folded for alias in aliases)}


def _states_reaction(text):
    raw = text or ""
    if any(mark in raw for mark in ("→", "->", "+", "反应")):
        return True
    return " with " in f" {raw.casefold()} "


def _fold(text):
    return "".join((text or "").split()).casefold()
