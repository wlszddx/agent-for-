"""一类溶液动力学实验的先验框：具体反应名只作举例，检索与锚点由报告内容动态生成。"""

import re

from kinetics_audit.reactions import families, species
from kinetics_audit.reference_store import pages_matching

_K_SEEN = re.compile(
    r"(?:测得|文献报道.{0,6})?速率常数为\s*(\d+(?:\.\d+)?)\s*L\s*/\s*\(?\s*mol\s*[·･.]?\s*min",
    re.I,
)
_TEMP_SEEN = re.compile(r"(\d+(?:\.\d+)?)\s*摄氏度")
_METHOD_MARKS = ("电导法", "分光光度法", "停流法", "线性回归", "积分", "脉冲辐解")

_SPECIES_LABEL = {
    "naoh": "氢氧化钠",
    "koh": "氢氧化钾",
    "hydroxide": "氢氧根",
    "ethyl_acetate": "乙酸乙酯",
    "radical_oh": "羟基自由基",
}

# 实验「类」模板：不含写死的具体课题名/文献数值；examples 仅供理解
_CLASS_TEMPLATES = {
    "alkaline_hydrolysis": {
        "family": "alkaline_hydrolysis",
        "class_label": "碱催化水解 / 皂化类溶液反应",
        "aliases": ["saponification"],
        "examples": [
            "乙酸乙酯与 NaOH 皂化（电导法测 k）——仅作举例，不是唯一可审课题",
            "其他羧酸酯碱性水解，只要同属皂化/碱催化水解类，同一套关系与取证规则适用",
        ],
        "incomparable_with": ["radical_oh", "羟基自由基脉冲辐解类"],
        "method_links": [
            {
                "method": "电导法",
                "observes": "溶液电导率随时间变化",
                "to_quantity": "二级（或准二级）速率常数 k",
                "bridge": "离子浓度变化反映在电导上；等初浓度时常用二级积分式，电导相关量对时间线性回归得 k",
            },
            {
                "method": "分光光度法",
                "observes": "吸光度随时间变化",
                "to_quantity": "速率常数 k",
                "bridge": "浓度与吸光度成正比时，用积分速率式求 k",
            },
            {
                "method": "停流法",
                "observes": "快速混合后的瞬态信号",
                "to_quantity": "较快反应的速率常数",
                "bridge": "与慢反应电导法不可互换条件与文献",
            },
        ],
        "expected_relations": [
            "同一反应、同一测定方法、相近浓度下，较高温度的表观 k 应大于较低温度的 k",
            "Arrhenius / 活化能拟合必须使用热力学温度（开尔文），不能直接代入摄氏度",
            "真速率常数不随初始用量改变；报告用量与文献不同仍可在同温同方法下比 k",
            "等初浓度假设不成立时，不能直接套用等浓度二级直线斜率公式",
            "电导法工作浓度通常不宜过高（约 >0.20 mol/L 时条件可疑）",
            "只与同一反应类、同一测定方法的文献比较；不可用羟基自由基等异类数据定罪",
        ],
        "search_plan_defaults": {
            "prefer_cache": True,
            "skip_nist_if_empty": True,
            "nist_note": (
                "教学向皂化/碱水解记录在 NDRL/NIST 中常缺失，空结果正常；"
                "按本报告实验名与物种检索 reference_cache / 网页，勿反复空撞 NIST 后交白卷"
            ),
            "prefer_nist": False,
            "cache_tag_hints": ["皂化", "碱催化水解", "碱性水解", "电导法", "速率常数"],
        },
    },
    "radical_oh": {
        "family": "radical_oh",
        "class_label": "羟基自由基溶液反应类",
        "aliases": [],
        "examples": [
            "脉冲辐解产生 ·OH 与底物反应测 k——仅作举例",
        ],
        "incomparable_with": ["alkaline_hydrolysis", "saponification", "皂化/碱水解类"],
        "method_links": [
            {
                "method": "脉冲辐解 / 瞬态吸收",
                "observes": "瞬态物种浓度随时间衰减",
                "to_quantity": "二级或准一级速率常数",
                "bridge": "与皂化/电导法教学实验类不可互换证据",
            }
        ],
        "expected_relations": [
            "不得用皂化/碱水解类教学参考值核对羟基自由基报告，反之亦然",
            "优先查 NDRL/NIST 溶液动力学库中的 ·OH 记录",
            "Arrhenius 拟合使用开尔文",
        ],
        "search_plan_defaults": {
            "prefer_cache": False,
            "skip_nist_if_empty": False,
            "nist_note": "本类优先 search_solution_kinetics（NIST），再辅以网页",
            "prefer_nist": True,
            "cache_tag_hints": ["羟基自由基", "radical", "脉冲辐解"],
        },
    },
}

_SOLUTION_KINETICS = {
    "family": "solution_kinetics",
    "class_label": "溶液反应动力学（未细分类）",
    "aliases": [],
    "examples": [
        "任意溶液相测 k / Ea 的教学或研究实验——用报告中的实验名与物种动态组检索词",
    ],
    "incomparable_with": [],
    "method_links": [
        {
            "method": "报告中的测定方法",
            "observes": "与方法对应的物理量随时间变化",
            "to_quantity": "速率常数或活化能",
            "bridge": "先确认反应物、测定方法与可观测量，再检索同反应同方法文献",
        },
        {
            "method": "电导法",
            "observes": "电导率随时间变化",
            "to_quantity": "速率常数 k",
            "bridge": "适用于有明显电导变化的离子型反应进程",
        },
        {
            "method": "分光光度法",
            "observes": "吸光度随时间变化",
            "to_quantity": "速率常数 k",
            "bridge": "吸光度可换算浓度时用积分或微分速率式",
        },
    ],
    "expected_relations": [
        "只与同一反应、同一测定方法、温度可对齐的文献比较",
        "同条件下升温通常使表观 k 增大",
        "Arrhenius 拟合使用开尔文",
        "真 k 不随初始用量改变",
    ],
    "search_plan_defaults": {
        "prefer_cache": True,
        "skip_nist_if_empty": True,
        "nist_note": "先按实验名+测定方法+速率常数检索缓存与网页；NIST 无命中再换词，勿空撞",
        "prefer_nist": False,
        "cache_tag_hints": ["速率常数", "活化能", "电导法", "分光光度法"],
    },
}


def frame_report(experiment="", report_text=""):
    """按实验「类」生成思维卡片；具体课题名来自报告，不写死。"""
    blob = f"{experiment or ''}\n{report_text or ''}"
    found_families = sorted(families(blob))
    found_species = sorted(species(blob))
    class_id = _pick_class(found_families, blob)
    template = _CLASS_TEMPLATES.get(class_id, _SOLUTION_KINETICS)
    conclusions = _conclusions_seen(report_text or "")
    subject = _subject_phrase(experiment, found_species, conclusions, class_id)
    search_plan = _build_search_plan(template, subject, conclusions, experiment)
    anchors = _anchor_hints(template, conclusions, found_families, class_id)
    card = {
        "family": template["family"],
        # 兼容旧字段名 saponification：碱水解类仍可被下游认作皂化类
        "legacy_family": "saponification" if class_id == "alkaline_hydrolysis" else class_id,
        "class_label": template["class_label"],
        "label": template["class_label"],
        "examples": list(template.get("examples") or []),
        "subject": subject,
        "species_expected": "由本报告物种与实验名确定，不预设某一固定反应式",
        "species_found": [_SPECIES_LABEL.get(s, s) for s in found_species],
        "families_found": found_families,
        "incomparable_with": list(template.get("incomparable_with") or []),
        "method_links": list(template.get("method_links") or []),
        "expected_relations": list(template.get("expected_relations") or []),
        "search_plan": search_plan,
        "anchor_hints": anchors,
        "conclusions_seen": conclusions,
    }
    card["understanding"] = _understanding(card, experiment)
    card["report_about"] = _report_about(card)
    card["what_to_verify"] = _what_to_verify(card)
    card["literature_needs"] = _literature_needs(card)
    return card


def _pick_class(found, blob):
    if "radical_oh" in found:
        return "radical_oh"
    if "saponification" in found:
        return "alkaline_hydrolysis"
    folded = "".join((blob or "").split()).casefold()
    if any(
        mark in folded
        for mark in ("皂化", "saponif", "碱催化水解", "碱性水解", "酯", "乙酸乙酯", "ethylacetate")
    ):
        return "alkaline_hydrolysis"
    if any(mark in folded for mark in ("羟基自由基", "·oh", "•oh", "pulseradiolysis", "脉冲辐解")):
        return "radical_oh"
    return "solution_kinetics"


def _subject_phrase(experiment, found_species, conclusions, class_id):
    """本报告课题短语：优先实验名，其次物种，再次标题提示。"""
    name = (experiment or "").strip()
    if name:
        return name
    labels = [_SPECIES_LABEL.get(s, s) for s in found_species]
    if labels:
        return "、".join(labels) + (" 碱水解/皂化" if class_id == "alkaline_hydrolysis" else " 溶液反应")
    hint = (conclusions.get("title_hint") or "").strip()
    if hint:
        return hint[:60]
    return {
        "alkaline_hydrolysis": "碱催化水解/皂化类反应",
        "radical_oh": "羟基自由基溶液反应",
    }.get(class_id, "溶液反应动力学实验")


def _build_search_plan(template, subject, conclusions, experiment):
    defaults = dict(template.get("search_plan_defaults") or {})
    methods = conclusions.get("methods_mentioned") or []
    method = next((m for m in methods if m in {"电导法", "分光光度法", "停流法"}), methods[0] if methods else "电导法")
    temps = conclusions.get("temperatures_C") or []
    temp = f"{temps[0]}摄氏度" if temps else "25摄氏度"
    queries = [
        f"{subject} {method} 速率常数 {temp}",
        f"{subject} {method} 二级反应 线性回归",
        f"{subject} 阿伦尼乌斯 热力学温度",
        f"{subject} 速率常数",
        f"{subject} 活化能",
    ]
    # 去重保序
    seen = set()
    unique = []
    for q in queries:
        key = "".join(q.split())
        if key in seen:
            continue
        seen.add(key)
        unique.append(q)
    return {
        "prefer_cache": defaults.get("prefer_cache", True),
        "skip_nist_if_empty": defaults.get("skip_nist_if_empty", True),
        "nist_note": defaults.get("nist_note", ""),
        "prefer_nist": defaults.get("prefer_nist", False),
        "cache_tag_hints": list(defaults.get("cache_tag_hints") or []),
        "queries": unique[:6],
        "quantity_query_template": "{subject} {method} 速率常数 {temperature}",
        "subject": subject,
        "note": "查询词由本报告实验名/物种动态生成；examples 中的具体反应不可当作唯一课题",
    }


def _anchor_hints(template, conclusions, found_families, class_id):
    """从 reference_cache 按类标签+方法动态挂锚，不写死某一文献数值页。"""
    tags = list(template.get("search_plan_defaults", {}).get("cache_tag_hints") or [])
    for method in conclusions.get("methods_mentioned") or []:
        tags.append(method)
    if class_id == "alkaline_hydrolysis" or "saponification" in (found_families or []):
        tags.extend(["皂化", "saponification", "碱性水解"])
    if class_id == "radical_oh":
        tags.extend(["羟基自由基", "radical_oh"])
    pages = pages_matching(tags, limit=6)
    hints = []
    for page in pages:
        hints.append(
            {
                "url": page.get("url"),
                "title": page.get("title"),
                "use_for": "与本报告同类/同方法时可供对照（缓存页，非写死唯一真值）",
                "tags": page.get("tags") or [],
            }
        )
    return hints


def _conclusions_seen(text):
    rates = []
    for match in _K_SEEN.finditer(text or ""):
        rates.append({"k": match.group(1), "unit": "L/(mol·min)"})
    temps = list(dict.fromkeys(_TEMP_SEEN.findall(text or "")))
    methods = [mark for mark in _METHOD_MARKS if mark in (text or "")]
    title = ""
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith("在 ") and "速率常数" not in line[:8]:
            title = line[:80]
            break
    return {
        "title_hint": title,
        "rate_constants": rates[:8],
        "temperatures_C": temps[:8],
        "methods_mentioned": methods,
    }


def _understanding(card, experiment):
    class_label = card.get("class_label") or "溶液反应动力学"
    subject = card.get("subject") or (experiment or "").strip() or class_label
    species_bits = "、".join(card.get("species_found") or []) or "（正文未点名物种，按实验类推断）"
    links = card.get("method_links") or []
    methods = (card.get("conclusions_seen") or {}).get("methods_mentioned") or []
    bridge = links[0]["bridge"] if links else "先确认测定方法与可观测量的关系"
    if methods:
        for link in links:
            if link.get("method") in methods:
                bridge = link["bridge"]
                break
    example = (card.get("examples") or ["（无）"])[0]
    return (
        f"本报告课题「{subject}」归入实验类「{class_label}」"
        f"（举例：{example}）。"
        f"物种线索：{species_bits}。"
        f"人审思路：{bridge}；"
        f"必须先读完 report_about / what_to_verify，再按 literature_needs 找文献。"
    )


def _report_about(card):
    """用人话完整概括：这份报告在讲什么（检索前必读）。"""
    seen = card.get("conclusions_seen") or {}
    methods = seen.get("methods_mentioned") or []
    rates = seen.get("rate_constants") or []
    temps = seen.get("temperatures_C") or []
    species = card.get("species_found") or []
    method_text = "、".join(methods) if methods else "未点名测定方法"
    rate_text = "、".join(f"{item['k']} {item['unit']}" for item in rates) if rates else "正文未抽出明确 k"
    temp_text = "、".join(f"{t}℃" for t in temps) if temps else "温度未抽出"
    species_text = "、".join(species) if species else "物种未点名"
    return (
        f"这份报告讲的是「{card.get('subject')}」，属于「{card.get('class_label')}」。"
        f"涉及物种：{species_text}；测定/做法线索：{method_text}；"
        f"出现的温度：{temp_text}；写出的速率常数值：{rate_text}。"
        f"接下来只找「同一反应类 + 同一测定方法 + 温度可对齐」的文献，"
        f"不要拿自由基等同名酯条目滥竽充数。"
    )


def _what_to_verify(card):
    """报告里需要核实的事项清单（先判断报告，再找文献）。"""
    items = []
    seen = card.get("conclusions_seen") or {}
    subject = card.get("subject") or ""
    methods = seen.get("methods_mentioned") or []
    for item in seen.get("rate_constants") or []:
        items.append(
            {
                "kind": "value",
                "focus": "速率常数",
                "detail": f"报告给出 k = {item['k']} {item['unit']}，需同反应同方法同温文献对照",
            }
        )
    if any(m in methods for m in ("电导法", "分光光度法", "停流法", "线性回归", "积分")):
        items.append(
            {
                "kind": "method",
                "focus": methods[0] if methods else "测定方法",
                "detail": f"报告采用 { '、'.join(methods) or '某种测定做法' }，需同类实验方法文献支持",
            }
        )
    if "摄氏" in str(card.get("conclusions_seen")) or "阿伦尼乌斯" in subject:
        items.append(
            {
                "kind": "method",
                "focus": "温度做法",
                "detail": "若报告做 Arrhenius/活化能，需核对是否使用热力学温度（开尔文）",
            }
        )
    if not items:
        items.append(
            {
                "kind": "general",
                "focus": "报告主题",
                "detail": f"先确认「{subject}」的测定方法与主要结论数字，再检索",
            }
        )
    return items


def _literature_needs(card):
    """按已理解的报告内容列出「用得上的文献」检索目标。"""
    needs = []
    plan = card.get("search_plan") or {}
    queries = list(plan.get("queries") or [])
    seen = card.get("conclusions_seen") or {}
    methods = seen.get("methods_mentioned") or []
    method = next((m for m in methods if m in {"电导法", "分光光度法", "停流法"}), "电导法")
    temps = seen.get("temperatures_C") or ["25"]
    subject = card.get("subject") or ""

    if seen.get("rate_constants"):
        needs.append(
            {
                "purpose": "核对报告中的速率常数数值",
                "must_match": ["同一反应类", method, f"{temps[0]}℃或可对齐温度"],
                "query": queries[0] if queries else f"{subject} {method} 速率常数",
                "reject_if": ["羟基自由基", "脉冲辐解", "·CH", "百科释义"],
            }
        )
    if any(m in methods for m in ("电导法", "线性回归", "积分", "分光光度法")):
        q = next((item for item in queries if "线性回归" in item or "二级" in item), None)
        needs.append(
            {
                "purpose": "核对测定方法与求 k 的做法是否文献支持",
                "must_match": ["同一反应类", method],
                "query": q or f"{subject} {method} 二级反应 线性回归",
                "reject_if": ["自由基", "百科"],
            }
        )
    needs.append(
        {
            "purpose": "核对 Arrhenius/温度用法（若报告涉及活化能或变温）",
            "must_match": ["热力学温度", "开尔文"],
            "query": next((item for item in queries if "阿伦尼乌斯" in item), f"{subject} 阿伦尼乌斯 热力学温度"),
            "reject_if": [],
        }
    )
    # 挂上缓存锚点作为「已理解后优先打开」的页
    for hint in (card.get("anchor_hints") or [])[:3]:
        needs.append(
            {
                "purpose": f"优先阅读缓存对照：{hint.get('title')}",
                "must_match": ["与本报告同类同方法"],
                "query": subject,
                "prefer_url": hint.get("url"),
                "reject_if": [],
            }
        )
    return needs[:8]
