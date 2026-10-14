import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from kinetics_audit.candidates import match_candidate, propose_from_report, recommended_claims
from kinetics_audit.priors import frame_report
from kinetics_audit.databases import remember, search_enzyme, search_solution
from kinetics_audit.kinetics import (
    accepted_dimensions,
    arrhenius_ea,
    canonical_quantity,
    comparable,
    dilution_concentration,
    dosage_differs,
    equal_initial_check,
    expected_rate,
    quantity_kind,
    setup_issue,
)
from kinetics_audit.reactions import same_reaction
from kinetics_audit.numbers import (
    calculation_status,
    compare_quantity,
    evaluate_expression,
    measurements,
    near_quantity,
    number_tokens,
    quantity_places,
)
from kinetics_audit.report_file import extract_report, locate_report
from kinetics_audit.search import fetch_page, search_web
from kinetics_audit.vectors import chunk_sentences, rank


class Job:
    def __init__(self, experiment, case, source):
        self.experiment = experiment
        self.case = case
        self.source = source
        self.writes = 0
        self.last_execution = None
        self.last_verify = None
        self.accepted = False
        self.references = {}
        self.report_text = ""
        self.experiment_name = ""
        self.claims = []
        self.judgments = []
        self.rejections = []
        self.searches = []
        self.selected = {}
        self.review = None
        self.retries = set()
        self.candidates = []
        self.frame = None

    @classmethod
    def closed(cls):
        return cls(None, None, "")


def _bind_report(job, experiment, text):
    name = experiment.strip()
    job.experiment_name = name
    job.report_text = text.strip()
    job.claims = []
    job.judgments = []
    job.rejections = []
    job.searches = []
    job.selected = {}
    job.review = None
    job.retries = set()
    job.candidates = []
    job.frame = None
    return {"ok": True, "experiment": name, "chars": len(job.report_text)}


def frame_experiment(job, _args):
    """像人一样：先完整判断报告在讲什么，再给出用得上的文献需求（不直接判错）。"""
    if not job.report_text:
        return {"ok": False, "error": "report_required"}
    card = frame_report(job.experiment_name, job.report_text)
    job.frame = card
    return {
        "ok": True,
        "report_about": card.get("report_about"),
        "what_to_verify": card.get("what_to_verify"),
        "literature_needs": card.get("literature_needs"),
        "frame": card,
        "note": (
            "第一步只理解报告：向用户用 report_about 说明「这份报告讲什么」。"
            "第二步再抽主张。第三步严格按 literature_needs 的 query / prefer_url 找文献，"
            "不得先撞 NIST 再倒推报告内容。"
        ),
    }


def _require_frame(job):
    if job.frame:
        return None
    if not job.report_text:
        return {"ok": False, "error": "report_required"}
    return {
        "ok": False,
        "error": "frame_required",
        "hint": "请先调用 frame_experiment，完整判断报告在讲什么，再检索文献。",
    }


def read_report(job, args):
    path = args.get("path")
    experiment = args.get("experiment")
    if not isinstance(path, str) or not path.strip():
        return {"ok": False, "error": "path_required"}
    if not isinstance(experiment, str) or not experiment.strip():
        return {"ok": False, "error": "experiment_required"}
    try:
        located = locate_report(path)
        text = extract_report(located)
    except ValueError as exc:
        code = str(exc)
        if code == "image":
            return {
                "ok": False,
                "error": "image_use_session_image",
                "hint": "对照片使用 AGH 的 read。先读 session-image://list，再读 session-image://消息序号/图片序号。",
            }
        return {"ok": False, "error": code}
    except OSError:
        return {"ok": False, "error": "unreadable"}
    bound = _bind_report(job, experiment, text)
    bound["path"] = str(located)
    bound["text"] = text
    return bound


def record_report(job, args):
    experiment = args.get("experiment")
    text = args.get("text")
    if not isinstance(experiment, str) or not experiment.strip():
        return {"ok": False, "error": "experiment_required"}
    if not isinstance(text, str) or len("".join(text.split())) < 8:
        return {"ok": False, "error": "text_required"}
    return _bind_report(job, experiment, text)


def propose_candidates(job, _args):
    if not job.report_text:
        return {"ok": False, "error": "report_required"}
    job.candidates = propose_from_report(job.report_text, job.experiment_name)
    recommended = recommended_claims(job.candidates)
    return {
        "ok": True,
        "count": len(job.candidates),
        "candidates": job.candidates,
        "recommended_claims": recommended,
        "note": "若有 recommended_claims，请立刻用 extract_claims 原样提交它们，不要改 quote。",
    }


def extract_recommended_claims(job, _args):
    """一键采纳程序生成的速率常数主张，避免模型点选表格长行失败。"""
    if not job.report_text:
        return {"ok": False, "error": "report_required"}
    if not job.candidates:
        job.candidates = propose_from_report(job.report_text, job.experiment_name)
    drafts = recommended_claims(job.candidates)
    if not drafts:
        return {"ok": False, "error": "no_recommended_claims", "hint": "报告中没有可自动抽取的速率常数短句。"}
    return extract_claims(job, {"claims": drafts})


def extract_claims(job, args):
    if not job.report_text:
        return {"ok": False, "error": "report_required"}
    if not job.candidates:
        job.candidates = propose_from_report(job.report_text, job.experiment_name)
    claims = args.get("claims")
    auto = bool(args.get("_auto_recommended"))
    if not isinstance(claims, list) or not claims:
        # 空列表时自动走推荐主张，避免模型交白卷
        drafts = recommended_claims(job.candidates)
        if drafts:
            claims = drafts
            auto = True
        else:
            return {"ok": False, "error": "claims_required"}
    accepted = []
    rejected = []
    seen = set()
    for item in claims:
        claim, failure = _parse_claim(job, item, seen)
        if failure:
            rejected.append(failure)
            continue
        seen.add(claim["id"])
        accepted.append(claim)
    if rejected or not accepted:
        # 手工点选全失败时，回退到推荐主张（只回退一次）
        if not auto:
            drafts = recommended_claims(job.candidates)
            if drafts:
                return extract_claims(job, {"claims": drafts, "_auto_recommended": True})
        job.rejections.append({"tool": "extract_claims", "items": rejected or [{"error": "claims_required"}]})
        return {"ok": False, "claims": accepted, "rejected": rejected or [{"error": "claims_required"}]}
    job.claims = accepted
    job.judgments = []
    job.selected = {}
    job.retries = set()
    return {"ok": True, "claims": accepted}


def search_references(job, args):
    blocked = _require_frame(job)
    if blocked:
        return blocked
    query = args.get("query")
    claim_id = args.get("claim_id")
    # 若未给 query，自动用 literature_needs 第一条
    if (not isinstance(query, str) or not query.strip()) and job.frame:
        needs = job.frame.get("literature_needs") or []
        if needs and needs[0].get("query"):
            query = needs[0]["query"]
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        return {"ok": False, "error": "query_required", "hint": "请使用 frame.literature_needs[].query"}
    if claim_id is not None and not any(claim["id"] == claim_id for claim in job.claims):
        return {"ok": False, "error": "unknown_claim", "id": claim_id}
    if any(item.get("claim_id") == claim_id and item.get("kind") == "web" for item in job.searches):
        return {"ok": False, "error": "search_limit", "id": claim_id}
    try:
        found = search_web(query.strip())
    except (OSError, ET.ParseError, ValueError):
        job.rejections.append({"tool": "search_references", "error": "search_failed", "query": query.strip(), "claim_id": claim_id})
        return {"ok": False, "error": "search_failed"}
    if not found:
        job.rejections.append({"tool": "search_references", "error": "no_results", "query": query.strip(), "claim_id": claim_id})
        return {"ok": False, "error": "no_results"}
    _store_web_hits(job, claim_id, query.strip(), found, "web")
    return {"ok": True, "claim_id": claim_id, "results": found}


def retry_claim(job, args):
    claim_id = args.get("claim_id")
    claim = _find_claim(job, claim_id)
    if claim is None:
        return {"ok": False, "error": "unknown_claim", "id": claim_id}
    if claim["kind"] == "calculation":
        return {"ok": False, "error": "calculation_skips_search", "id": claim_id}
    if claim_id in job.retries:
        return {"ok": False, "error": "retry_exhausted", "id": claim_id}
    items = [item for item in job.judgments if item["claim_id"] == claim_id]
    if not items:
        return {"ok": False, "error": "judgment_required", "id": claim_id}
    if items[-1]["status"] not in {"not_comparable", "not_enough"}:
        return {"ok": False, "error": "retry_not_applicable", "id": claim_id, "status": items[-1]["status"]}
    query = _retry_query(claim, job.experiment_name, job.frame)
    job.retries.add(claim_id)
    try:
        found = search_web(query)
    except (OSError, ET.ParseError, ValueError):
        job.rejections.append({"tool": "retry_claim", "error": "search_failed", "query": query, "claim_id": claim_id})
        return {"ok": False, "error": "search_failed", "query": query}
    if not found:
        job.rejections.append({"tool": "retry_claim", "error": "no_results", "query": query, "claim_id": claim_id})
        return {"ok": False, "error": "no_results", "query": query}
    _store_web_hits(job, claim_id, query, found, "retry")
    return {
        "ok": True,
        "claim_id": claim_id,
        "query": query,
        "results": found,
        "note": "用返回的 url 调用 read_reference 和 select_evidence，再 judge_claim。已有判断保留。",
    }


def _store_web_hits(job, claim_id, query, found, kind):
    for item in found:
        page = job.references.setdefault(item["url"], {"title": item["title"], "text": "", "sentences": []})
        page["title"] = item["title"]
        if not page["sentences"]:
            page["text"] = f"{page['text']} {item['excerpt']}".strip()
    job.searches.append({"claim_id": claim_id, "query": query, "urls": [item["url"] for item in found], "kind": kind})


def _retry_query(claim, experiment="", frame=None):
    parts = []
    subject = ((frame or {}).get("subject") or experiment or "").strip()
    if subject:
        parts.append(subject)
    blob = f"{experiment} {claim.get('quote') or ''}"
    for word in ("皂化", "碱催化水解", "电导法", "NaOH", "氢氧化钠"):
        if word in blob and word not in parts:
            parts.append(word)
    if claim["kind"] == "method":
        parts.extend([claim["slot"], "测定方法", "溶液反应动力学"])
    else:
        parts.extend([claim["quantity"], claim.get("dosage"), claim["temperature"], claim["method"]])
    return (" ".join(part for part in parts if part) + " -百科 -词典")[:200]


def search_solution_kinetics(job, args):
    blocked = _require_frame(job)
    if blocked:
        return blocked
    plan = (job.frame or {}).get("search_plan") or {}
    family = (job.frame or {}).get("family") or (job.frame or {}).get("legacy_family")
    # 教学向碱水解/皂化类：NIST 常只有自由基等同名酯条目，会误导检索目的
    if plan.get("prefer_nist") is False or family in {"alkaline_hydrolysis", "saponification"}:
        return {
            "ok": False,
            "error": "wrong_database_for_class",
            "hint": (
                "当前实验类不优先 NIST。请改用 search_references，"
                "查询词用 frame.search_plan.queries（含皂化/电导法/速率常数）；"
                "本地 reference_cache 会优先返回可比教学文献。"
            ),
            "queries": plan.get("queries") or [],
        }
    return _search_database(
        job,
        args,
        "NDRL/NIST solution kinetics",
        lambda: search_solution(args.get("reactant"), args.get("solvent") or ""),
    )


def search_enzyme_kinetics(job, args):
    return _search_database(
        job,
        args,
        "SABIO-RK",
        lambda: search_enzyme(args.get("substrate"), args.get("enzyme") or "", args.get("organism") or ""),
    )


def _search_database(job, args, database, fetch):
    claim_id = args.get("claim_id")
    if not any(claim["id"] == claim_id for claim in job.claims):
        return {"ok": False, "error": "unknown_claim", "id": claim_id}
    try:
        found = fetch()
    except ValueError as exc:
        if str(exc) == "query_required":
            return {"ok": False, "error": "query_required"}
        job.rejections.append({"tool": database, "error": "database_unavailable", "claim_id": claim_id})
        return {"ok": False, "error": "database_unavailable", "database": database}
    except (OSError, json.JSONDecodeError):
        job.rejections.append({"tool": database, "error": "database_unavailable", "claim_id": claim_id})
        return {"ok": False, "error": "database_unavailable", "database": database}
    if not found:
        job.rejections.append({"tool": database, "error": "no_results", "claim_id": claim_id})
        return {"ok": False, "error": "no_results", "database": database}
    remember(job, claim_id, database, found)
    return {"ok": True, "claim_id": claim_id, "database": database, "results": found}


def read_reference(job, args):
    url = args.get("url")
    if not isinstance(url, str) or url not in job.references:
        return {"ok": False, "error": "unknown_source"}
    page = job.references[url]
    if page.get("local") and page.get("sentences"):
        return {
            "ok": True,
            "url": url,
            "title": page["title"],
            "sentence_count": len(page["sentences"]),
            "text": page["text"],
        }
    try:
        text = fetch_page(url)
    except (OSError, ValueError):
        return {"ok": False, "error": "fetch_failed"}
    sentences = chunk_sentences(text)
    if not sentences:
        return {"ok": False, "error": "empty_page"}
    job.references[url]["text"] = text
    job.references[url]["sentences"] = sentences
    return {
        "ok": True,
        "url": url,
        "title": job.references[url]["title"],
        "sentence_count": len(sentences),
        "text": text,
    }


def select_evidence(job, args):
    claim_id = args.get("claim_id")
    url = args.get("url")
    claim = _find_claim(job, claim_id)
    if claim is None:
        return {"ok": False, "error": "unknown_claim", "id": claim_id}
    if claim["kind"] == "calculation":
        return {"ok": False, "error": "calculation_skips_search", "id": claim_id}
    page = job.references.get(url) if isinstance(url, str) else None
    if page is None or not page.get("sentences"):
        return {"ok": False, "error": "page_required", "url": url}
    required = _required_phrases(claim)
    focus = _model_text(args.get("focus"), 120)
    query = " ".join(part for part in (focus, claim["quote"], *required) if part)
    eligible = []
    filtered_out = []
    for sentence in page["sentences"]:
        ok, reason = _evidence_eligible(claim, sentence["text"], job.experiment_name)
        if ok:
            eligible.append(sentence)
        else:
            filtered_out.append({"id": sentence["id"], "reason": reason})
    chosen = rank(query, eligible, required=required) if eligible else []
    for item in chosen:
        item["same_reaction"] = True
        item["eligible"] = True
    job.selected.setdefault(claim_id, {})[url] = {item["id"]: item["text"] for item in chosen}
    abstain = not chosen or (not any(item["covered"] for item in chosen) and chosen[0]["score"] < 0.05)
    result = {
        "ok": True,
        "claim_id": claim_id,
        "url": url,
        "abstain": abstain,
        "sentences": chosen,
        "filtered_out": len(filtered_out),
        "filter": "reaction_method_temperature",
    }
    if focus:
        result["focus"] = focus
    if abstain and not chosen:
        reasons = sorted({item["reason"] for item in filtered_out})
        reason = reasons[0] if len(reasons) == 1 else "conditions"
        note = "没有通过同一反应、测定方法与温度硬过滤的句子，不能据此判断。"
        result["note"] = note
        page = job.references[url]
        _store_judgment(
            job,
            {
                "claim_id": claim_id,
                "kind": claim["kind"],
                "status": "not_comparable",
                "reason": reason,
                "statement": note + (f"文献页「{page.get('title') or url}」。" if url else ""),
                "url": url,
                "title": page.get("title"),
                "quantity": claim.get("quantity"),
            },
        )
    return result


def _evidence_eligible(claim, sentence, experiment=""):
    if same_reaction(claim["quote"], sentence, experiment) is False:
        return False, "reaction"
    if claim["kind"] == "value":
        allowed, reason, _missing = comparable(claim["quantity_kind"], claim, sentence)
        if not allowed:
            return False, reason
    return True, "ok"


def judge_claim(job, args):
    claim_id = args.get("claim_id")
    verdict = args.get("verdict")
    claim = _find_claim(job, claim_id)
    if claim is None:
        return {"ok": False, "error": "unknown_claim", "id": claim_id}
    if verdict not in {"supports", "contradicts", "not_enough"}:
        return {"ok": False, "error": "invalid_verdict"}
    if claim["kind"] == "calculation":
        judgment = _judge_calculation(claim, verdict)
    else:
        judgment = _judge_against_sentence(job, claim, args, verdict)
        if judgment.get("ok") is False:
            job.rejections.append({"tool": "judge_claim", "item": judgment})
            return judgment
    _attach_model_notes(judgment, args)
    _store_judgment(job, judgment)
    return {"ok": True, "judgment": judgment}


def finish_review(job, args):
    if not job.report_text:
        return {"ok": False, "error": "report_required"}
    if not job.claims:
        return {"ok": False, "error": "claims_required"}
    if job.frame is None and job.report_text:
        job.frame = frame_report(job.experiment_name, job.report_text)
    confirmed = []
    supported = []
    insufficient = []
    for claim in job.claims:
        items = [item for item in job.judgments if item["claim_id"] == claim["id"]]
        bucket, payload = _resolve_claim(claim, items)
        {"confirmed_errors": confirmed, "supported": supported, "insufficient": insufficient}[bucket].append(payload)
    review = {
        "experiment": job.experiment_name,
        "claims": job.claims,
        "searches": job.searches,
        "confirmed_errors": confirmed,
        "supported": supported,
        "insufficient": insufficient,
        "rejected": job.rejections,
    }
    if job.frame:
        review["frame"] = {
            "family": job.frame.get("family"),
            "label": job.frame.get("label"),
            "report_about": job.frame.get("report_about"),
            "what_to_verify": job.frame.get("what_to_verify"),
            "literature_needs": job.frame.get("literature_needs"),
            "understanding": job.frame.get("understanding"),
            "expected_relations": job.frame.get("expected_relations"),
            "conclusions_seen": job.frame.get("conclusions_seen"),
            "search_plan": job.frame.get("search_plan"),
        }
    summary = _model_text(args.get("summary"), 800)
    if summary:
        review["summary"] = summary
    notes = _causal_notes(confirmed, job.claims, job.judgments)
    relation_notes = _relation_notes(job.frame, job.claims, job.judgments)
    if relation_notes:
        notes = list(notes) + relation_notes
    if notes:
        review["causal_notes"] = notes
    job.review = review
    dest = Path(__file__).resolve().parents[1] / "evidence"
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = dest / f"{stamp}-review.json"
    path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(path), "review": review}


def _parse_claim(job, item, seen):
    if not isinstance(item, dict):
        return None, {"error": "incomplete"}
    claim_id = item.get("id")
    kind = item.get("kind")
    quote = item.get("quote")
    if not all(isinstance(value, str) and value.strip() for value in (claim_id, kind, quote)):
        return None, {"error": "incomplete"}
    if kind not in {"method", "value", "calculation"}:
        return None, {"error": "claim_kind", "id": claim_id}
    if claim_id in seen:
        return None, {"error": "duplicate_claim", "id": claim_id}
    quote = quote.strip()
    if len(_compact(quote)) < 6 or _compact(quote) not in _compact(job.report_text):
        return None, {"error": "quote_not_in_report", "id": claim_id}
    candidate = match_candidate(job.candidates, item.get("candidate_id"), quote)
    if candidate is None:
        return _claim_error("candidate_required", claim_id)
    claim = {"id": claim_id.strip(), "kind": kind, "quote": quote, "candidate_id": candidate["id"]}
    if kind == "method":
        slot = item.get("slot")
        if not isinstance(slot, str) or len(_compact(slot)) < 2 or _compact(slot) not in _compact(quote):
            return None, {"error": "slot_required", "id": claim_id}
        claim["slot"] = slot.strip()
    elif kind == "value":
        quantity = item.get("quantity")
        dosage = item.get("dosage")
        temperature = item.get("temperature")
        method = item.get("method")
        qkind = quantity_kind(quantity) if isinstance(quantity, str) else None
        if qkind is None or not quantity_places(quote, quantity.strip(), qkind):
            return _claim_error("quantity_not_in_class", claim_id)
        fields = {"dosage": dosage, "temperature": temperature, "method": method}
        quote_compact = _compact(quote)
        report_compact = _compact(job.report_text)
        for key, value in fields.items():
            if not isinstance(value, str) or len(_compact(value)) < 2:
                return _claim_error("kinetic_conditions_required", claim_id)
            compact_value = _compact(value)
            # 表格行常不含测定方法：dosage/temperature 必须落在 quote，method 可在全文或别名
            if key == "method":
                if not _condition_in_text(compact_value, quote_compact, report_compact, method=True):
                    return _claim_error("kinetic_conditions_required", claim_id)
            elif compact_value not in quote_compact:
                # PDF 常见「25 C」无℃：温度数字落在 quote 即可
                if key == "temperature" and any(ch.isdigit() for ch in value) and _compact(
                    "".join(ch for ch in value if ch.isdigit() or ch == ".")
                ) in quote_compact:
                    continue
                return _claim_error("kinetic_conditions_required", claim_id)
        if not near_quantity(quote, quantity.strip(), measurements(quote), qkind):
            return _claim_error("quantity_number_required", claim_id)
        claim["quantity"] = canonical_quantity(quantity)
        claim["quantity_kind"] = qkind
        claim.update({key: value.strip() for key, value in fields.items()})
        claim["conditions"] = "、".join(claim[key] for key in ("dosage", "temperature", "method"))
    else:
        expression = item.get("expression")
        reported = item.get("reported")
        if not isinstance(reported, str) or reported not in number_tokens(quote):
            return _claim_error("reported_required", claim_id)
        if isinstance(expression, str) and expression.strip().casefold() == "arrhenius":
            try:
                fitted = arrhenius_ea(quote, reported)
            except ValueError as exc:
                return _claim_error(str(exc), claim_id)
            claim["expression"] = "arrhenius"
            claim["reported"] = reported
            claim["computed"] = fitted["computed"]
            claim["computed_unit"] = fitted["computed_unit"]
            claim["relative_difference"] = fitted["relative_difference"]
            claim["fit_status"] = fitted["status"]
        elif isinstance(expression, str) and expression.strip().casefold() == "rate":
            equation = item.get("equation")
            try:
                fitted = expected_rate(quote, equation, reported)
            except ValueError as exc:
                return _claim_error(str(exc), claim_id)
            claim["expression"] = "rate"
            claim["equation"] = equation.strip()
            claim["reported"] = reported
            claim["computed"] = fitted["computed"]
            claim["computed_unit"] = fitted["computed_unit"]
            claim["relative_difference"] = fitted["relative_difference"]
            claim["fit_status"] = fitted["status"]
        elif isinstance(expression, str) and expression.strip().casefold() == "dilution":
            try:
                fitted = dilution_concentration(quote, reported)
            except ValueError as exc:
                return _claim_error(str(exc), claim_id)
            claim["expression"] = "dilution"
            claim["reported"] = reported
            claim["computed"] = fitted["computed"]
            claim["computed_unit"] = fitted["computed_unit"]
            claim["relative_difference"] = fitted["relative_difference"]
            claim["fit_status"] = fitted["status"]
            claim["expected_working_concentration"] = fitted["expected_working_concentration"]
            claim["metering"] = {
                "stock": fitted["stock"],
                "aliquot": fitted["aliquot"],
                "aliquot_unit": fitted["aliquot_unit"],
                "total": fitted["total"],
                "total_unit": fitted["total_unit"],
                "tolerance": fitted["tolerance"],
                "expected_working_concentration": fitted["expected_working_concentration"],
                "expected_unit": fitted["expected_unit"],
                "reported_working_concentration": reported,
            }
        elif isinstance(expression, str) and expression.strip().casefold() == "stoichiometry":
            equation = item.get("equation")
            try:
                fitted = equal_initial_check(quote, equation)
            except ValueError as exc:
                return _claim_error(str(exc), claim_id)
            claim["expression"] = "stoichiometry"
            claim["equation"] = equation.strip()
            claim["reported"] = reported
            claim["computed"] = fitted["computed"]
            claim["computed_unit"] = fitted["computed_unit"]
            claim["relative_difference"] = fitted["relative_difference"]
            claim["fit_status"] = fitted["status"]
            claim["metering"] = {
                "left": fitted["left"],
                "left_unit": fitted["left_unit"],
                "right": fitted["right"],
                "right_unit": fitted["right_unit"],
                "tolerance": fitted["tolerance"],
                "claimed_equal": fitted["claimed_equal"],
            }
        else:
            try:
                computed = evaluate_expression(expression, quote)
            except ValueError as exc:
                return None, {"error": str(exc), "id": claim_id}
            claim["expression"] = expression.strip()
            claim["reported"] = reported
            claim["computed"] = computed
    return claim, None


def _judge_against_sentence(job, claim, args, verdict):
    url = args.get("url")
    sentence_id = args.get("sentence_id")
    chosen = job.selected.get(claim["id"], {}).get(url) if isinstance(url, str) else None
    if not chosen or sentence_id not in chosen:
        return {"ok": False, "error": "evidence_required", "id": claim["id"]}
    sentence = chosen[sentence_id]
    page = job.references[url]
    if claim["kind"] == "method":
        judgment = _judge_method(claim, sentence, args.get("literature_span"), job.experiment_name)
        judgment = _apply_model_method_verdict(judgment, verdict)
    else:
        judgment = _judge_value(claim, sentence, job.experiment_name)
    judgment.update(
        {
            "claim_id": claim["id"],
            "kind": claim["kind"],
            "url": url,
            "title": page["title"],
            "sentence_id": sentence_id,
            "sentence": sentence,
            "model_verdict": verdict,
        }
    )
    return judgment


def _apply_model_method_verdict(judgment, verdict):
    # Only the model may soften a program "contradicts"; it cannot invent errors alone.
    if judgment.get("status") != "contradicts" or verdict == "contradicts":
        return judgment
    if verdict == "not_enough":
        reason = "model_caution"
        note = "模型认为证据还不足以下结论，暂不把报告记为最终对错。"
    else:
        reason = "model_disagrees"
        note = f"模型判断为「{verdict}」，与程序核对结果「contradicts」不一致，暂不记为最终对错。"
    updated = dict(judgment)
    updated.update(
        {
            "status": "not_enough",
            "reason": reason,
            "program_status": "contradicts",
            "statement": f"{judgment.get('statement', '')}{note}",
        }
    )
    return updated


def _attach_model_notes(judgment, args):
    explanation = _model_text(args.get("explanation"), 500)
    improvement = _model_text(args.get("improvement"), 500)
    if explanation:
        judgment["explanation"] = explanation
    if improvement:
        judgment["improvement"] = improvement


def _model_text(value, limit):
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if len(text) < 4:
        return None
    return text[:limit]


def _with_model_notes(payload, items):
    for key in ("explanation", "improvement"):
        for item in reversed(items):
            if item.get(key):
                payload[key] = item[key]
                break
    return payload


def _judge_method(claim, sentence, literature_span, experiment=""):
    slot = claim["slot"]
    if same_reaction(claim["quote"], sentence, experiment) is False:
        return {
            "status": "not_enough",
            "statement": f"文献写的是另一个反应，不能用来判断报告里的「{slot}」。文献写「{sentence}」。",
            "slot": slot,
        }
    if not isinstance(literature_span, str) or _compact(literature_span) not in _compact(sentence):
        return {
            "status": "not_enough",
            "statement": f"文献句没有给出与「{slot}」相对的做法，不能判断。报告写「{claim['quote']}」。文献写「{sentence}」。",
            "slot": slot,
        }
    if _compact(literature_span) == _compact(slot):
        return {
            "status": "supports",
            "statement": f"报告写「{claim['quote']}」。文献写「{sentence}」。两边都是「{slot}」，不记为错误。",
            "slot": slot,
            "literature_span": literature_span.strip(),
        }
    if _compact(slot) not in _compact(sentence):
        return {
            "status": "not_enough",
            "statement": (
                f"文献句没有讨论报告中的做法「{slot}」，不能因为另一套做法「{literature_span.strip()}」就把报告记为错误。"
                f"报告写「{claim['quote']}」。文献写「{sentence}」。"
            ),
            "slot": slot,
            "literature_span": literature_span.strip(),
        }
    return {
        "status": "contradicts",
        "statement": (
            f"报告写「{claim['quote']}」，其中做法是「{slot}」。"
            f"文献写「{sentence}」，要求的是「{literature_span.strip()}」。"
            f"用量改变不改变这一步。改进时按文献原句处理「{slot}」。"
        ),
        "slot": slot,
        "literature_span": literature_span.strip(),
    }


def _judge_value(claim, sentence, experiment=""):
    issue = setup_issue(claim)
    if issue is not None:
        return issue
    if same_reaction(claim["quote"], sentence, experiment) is False:
        return {
            "status": "not_comparable",
            "reason": "reaction",
            "quantity": claim["quantity"],
            "statement": f"文献与报告不是同一个反应，{claim['quantity']}不能比较。文献写「{sentence}」。",
            "kind": "value",
        }
    allowed, reason, missing = comparable(claim["quantity_kind"], claim, sentence)
    if not allowed:
        detail = "、".join(missing) or "实验条件"
        return {
            "status": "not_comparable",
            "reason": reason,
            "quantity": claim["quantity"],
            "statement": (
                f"文献与报告的{detail}不是同一套实验条件，{claim['quantity']}不能据此判断对错。"
                f"文献写「{sentence}」。"
            ),
            "kind": "value",
        }
    compared = compare_quantity(
        claim["quote"],
        sentence,
        claim["quantity"],
        claim["conditions"],
        enforce_conditions=False,
        accepted_dimensions=accepted_dimensions(claim["quantity_kind"]),
        quantity_kind=claim["quantity_kind"],
    )
    status = compared["status"]
    quantity = claim["quantity"]
    dosage_note = ""
    if dosage_differs(claim["dosage"], sentence) and status in {"supports", "contradicts"}:
        dosage_note = "报告用量与文献不同。同一反应的速率常数和活化能不随初始用量改变，因此仍按温度和测定方法比较数字。"
    if status == "contradicts":
        statement = (
            f"报告中的{quantity}为 {compared['reported']} {compared['reported_unit']}，"
            f"文献为 {compared['reference']} {compared['reference_unit']}，"
            f"相对差 {compared['relative_difference']:.1%}，超过容差 {compared['tolerance']:.1%}。"
            f"{dosage_note}"
            f"报告写「{claim['quote']}」。文献写「{sentence}」。"
        )
    elif status == "supports":
        statement = (
            f"报告中的{quantity}为 {compared['reported']} {compared['reported_unit']}，"
            f"文献为 {compared['reference']} {compared['reference_unit']}，相对差在容差内。"
            f"{dosage_note}"
            f"报告写「{claim['quote']}」。文献写「{sentence}」。"
        )
    elif status == "not_comparable" and compared.get("reason") == "conditions":
        statement = f"报告条件「{claim['conditions']}」没有完整出现在文献句中，数值不可比。文献写「{sentence}」。"
    elif status == "not_comparable":
        statement = f"报告与文献的{quantity}单位不能换算，数值不可比。文献写「{sentence}」。"
    else:
        statement = f"文献句没有给出可核对的{quantity}。文献写「{sentence}」。"
    compared.update({"status": status, "statement": statement, "kind": "value"})
    return compared


def _judge_calculation(claim, verdict):
    expression = claim.get("expression")
    if expression in {"arrhenius", "rate", "dilution", "stoichiometry"}:
        compared = {
            "status": claim["fit_status"],
            "computed": claim["computed"],
            "reported": claim["reported"],
            "relative_difference": claim["relative_difference"],
        }
    else:
        compared = calculation_status(claim["computed"], claim["reported"])
    statement = _calculation_statement(claim, compared)
    judgment = {
        "claim_id": claim["id"],
        "kind": "calculation",
        "status": compared["status"],
        "statement": statement,
        "expression": claim["expression"],
        "computed": compared["computed"],
        "reported": claim["reported"],
        "relative_difference": compared["relative_difference"],
        "model_verdict": verdict,
    }
    if claim.get("metering"):
        judgment["metering"] = claim["metering"]
    if claim.get("expected_working_concentration") is not None:
        judgment["expected_working_concentration"] = claim["expected_working_concentration"]
        judgment["expected_unit"] = claim.get("computed_unit")
    if claim.get("equation"):
        judgment["equation"] = claim["equation"]
    return judgment


def _calculation_statement(claim, compared):
    expression = claim.get("expression")
    quote = claim["quote"]
    if expression == "dilution":
        meta = claim.get("metering") or {}
        lead = (
            f"按稀释公式 c = c0·V0/V，用母液 {meta.get('stock')} mol/L、"
            f"移取 {meta.get('aliquot')} {meta.get('aliquot_unit')}、"
            f"定容 {meta.get('total')} {meta.get('total_unit')} 重算，"
        )
        if compared["status"] == "contradicts":
            return (
                f"{lead}应得工作浓度约 {compared['computed']:.6g} {claim.get('computed_unit', 'mol/L')}，"
                f"报告写的是 {claim['reported']}。这是配制计量错误。报告写「{quote}」。"
            )
        return (
            f"{lead}应得工作浓度约 {compared['computed']:.6g} {claim.get('computed_unit', 'mol/L')}，"
            f"与报告所写 {claim['reported']} 一致。报告写「{quote}」。"
        )
    if expression == "stoichiometry":
        meta = claim.get("metering") or {}
        lead = (
            f"反应式「{claim.get('equation', '')}」按二级等浓度处理时，"
            f"原句浓度分别为 {meta.get('left')} {meta.get('left_unit')} 与 "
            f"{meta.get('right')} {meta.get('right_unit')}，相对差 {compared['relative_difference']:.1%}。"
        )
        if compared["status"] == "contradicts":
            return f"{lead}报告写了等浓度假设，但两边浓度不一致，属于计量/设计错误。报告写「{quote}」。"
        if compared["status"] == "not_enough":
            return f"{lead}原句未写等浓度假设，不能据此记为计量错误。报告写「{quote}」。"
        return f"{lead}两边浓度在容差内，等浓度假设成立。报告写「{quote}」。"
    if expression == "rate":
        lead = f"按反应式「{claim['equation']}」把计量数当作级数，"
    else:
        lead = "按报告原句中的数字计算，"
    if compared["status"] == "contradicts":
        return (
            f"{lead}{expression} = {compared['computed']:.6g}，"
            f"报告写的是 {claim['reported']}。报告写「{quote}」。"
        )
    return (
        f"{lead}{expression} = {compared['computed']:.6g}，"
        f"与报告所写 {claim['reported']} 一致。报告写「{quote}」。"
    )


def _causal_notes(confirmed, claims, judgments=None):
    by_id = {claim["id"]: claim for claim in claims}
    metering_ids = []
    value_ids = []
    expected_bits = []
    for item in confirmed:
        claim = by_id.get(item["claim_id"])
        if claim is None:
            continue
        if claim["kind"] == "calculation" and claim.get("expression") in {"dilution", "stoichiometry"}:
            metering_ids.append(claim["id"])
            if claim.get("expression") == "dilution" and claim.get("expected_working_concentration") is not None:
                unit = claim.get("computed_unit") or "mol/L"
                expected_bits.append(
                    f"主张 {claim['id']} 按稀释公式应得工作浓度约 "
                    f"{claim['expected_working_concentration']:.6g} {unit}，"
                    f"报告声明为 {claim['reported']} {unit}"
                )
        elif claim["kind"] == "value":
            value_ids.append(claim["id"])
    # 计量未单独成主张、但数值已证实错误时，也提示优先查配制
    if not value_ids and judgments:
        for item in judgments:
            if item.get("status") != "contradicts":
                continue
            claim = by_id.get(item.get("claim_id"))
            if claim and claim.get("kind") == "value":
                value_ids.append(claim["id"])
    if not metering_ids or not value_ids:
        return []
    detail = "；".join(expected_bits)
    statement = (
        "同一报告中配制/等浓度计量主张与速率常数或活化能均已证实错误。"
        "结果偏差应优先排查移取体积、定容体积、工作浓度和等浓度假设是否算错或用不一致，"
        "而不是先把问题只归到曲线拟合。"
    )
    if detail:
        statement = f"{statement}{detail}。"
    return [
        {
            "kind": "metering_may_cause_value_error",
            "metering_claim_ids": metering_ids,
            "value_claim_ids": value_ids,
            "statement": statement,
        }
    ]


def _relation_notes(frame, claims, judgments):
    """按实验类先验检查报告内温度–k 关系等（辅助说明，不单独定罪）。"""
    family = (frame or {}).get("family") or (frame or {}).get("legacy_family")
    if family not in {"saponification", "alkaline_hydrolysis", "solution_kinetics"}:
        return []
    notes = []
    value_claims = [c for c in claims if c.get("kind") == "value" and c.get("quantity_kind") == "rate"]
    # 从主张条件解析摄氏度与 k
    points = []
    for claim in value_claims:
        temp = claim.get("temperature") or ""
        match = re.search(r"(\d+(?:\.\d+)?)", temp)
        if not match:
            continue
        nums = measurements(claim.get("quote") or "")
        rates = [item for item in nums if item.get("dimension") == "second_order_rate"]
        if not rates:
            continue
        points.append((float(match.group(1)), float(rates[0]["number"]), claim["id"]))
    if len(points) >= 2:
        points.sort(key=lambda item: item[0])
        low, high = points[0], points[-1]
        if high[0] > low[0] + 0.5 and high[1] < low[1] * 0.95:
            notes.append(
                {
                    "kind": "temperature_rate_relation",
                    "claim_ids": [low[2], high[2]],
                    "statement": (
                        f"实验族先验：同测定方法下升温应使表观 k 增大；"
                        f"报告中 {low[0]:g}℃ 的 k≈{low[1]:.4g}，"
                        f"{high[0]:g}℃ 的 k≈{high[1]:.4g}，升温反而变小，"
                        f"宜复核温度记录、拟合与单位（仍须文献证据支撑最终对错）。"
                    ),
                }
            )
    contradicted = [
        item["claim_id"]
        for item in judgments or []
        if item.get("status") == "contradicts" and by_id_kind(claims, item.get("claim_id")) == "value"
    ]
    if contradicted and frame.get("understanding"):
        notes.append(
            {
                "kind": "framed_value_mismatch",
                "claim_ids": contradicted,
                "statement": (
                    f"{frame.get('understanding')} "
                    "数值主张已与同反应同方法文献对照后证实偏差；"
                    "请结合 expected_relations 排查拟合、单位与等浓度假设。"
                ),
            }
        )
    return notes


def by_id_kind(claims, claim_id):
    for claim in claims or []:
        if claim.get("id") == claim_id:
            return claim.get("kind")
    return None


_CLAIM_HINTS = {
    "dilution_missing_reported_concentration": "原句里找不到与 reported 一致的工作浓度，请把声明的工作浓度数字原样填入 reported。",
    "dilution_missing_stock_concentration": "原句需写出母液浓度，并且与工作浓度是两个不同的数字。",
    "dilution_missing_volumes": "原句需同时写出移取体积和定容体积，例如 10.0 mL 与 100 mL。",
    "dilution_ambiguous_volumes": "原句里体积多于两个，请把稀释相关的移取体积和定容体积写进同一连续原句。",
    "dilution_invalid_volumes": "移取体积必须小于定容体积，且两者都大于 0。",
    "stoichiometry_need_two_reactants": "等浓度核对需要反应式左侧至少两种反应物。",
    "stoichiometry_missing_concentrations": "原句需写出至少两个摩尔浓度，才能核对等浓度假设。",
    "equation_required": "equation 必须是 quote 中的连续反应式原文。",
    "arrhenius_data_required": "原句需至少两组温度和对应速率常数，以及要核对的活化能数字。",
    "rate_law_data_required": "原句需有反应式、一个速率常数、足够浓度，以及要核对的反应速率数字。",
    "reported_required": "reported 必须是 quote 中出现的完整数字字符串。",
    "kinetic_conditions_required": "dosage、temperature 必须是 quote 里的短原文；method 可在报告全文（表格行常不含测定方法）。表格请用 propose_candidates 合并候选，勿自造跨行句子。",
    "quantity_not_in_class": (
        "数值主张的 quantity 允许「速率常数」或「活化能」（二者都可，不是只许活化能），"
        "也可写原文中的 k、k(单位)、Ea；且该标记必须出现在同一段 quote 里。"
        "若已有 recommended_claims，请改调 extract_recommended_claims，勿因本错误放弃速率常数。"
    ),
    "quantity_number_required": "quote 里 k/速率常数/活化能附近需要可解析的数字和单位（支持 k(L/mol/min)=5.193 这种表头写法）。",
    "candidate_required": "quote 必须来自 propose_candidates 返回的候选句，或传入对应的 candidate_id；不要跨行自造拼接。",
}


def _claim_error(code, claim_id):
    item = {"error": code, "id": claim_id}
    hint = _CLAIM_HINTS.get(code)
    if hint:
        item["hint"] = hint
    return None, item


_METHOD_ALIASES = {
    "电导法": ("电导", "conductivity", "conductance", "conductometric"),
    "分光光度法": ("分光", "spectrophot"),
    "停流法": ("停流", "stoppedflow", "stopped-flow"),
}


def _condition_in_text(compact_value, quote_compact, report_compact, method=False):
    if compact_value in quote_compact or compact_value in report_compact:
        return True
    if not method:
        return False
    for name, aliases in _METHOD_ALIASES.items():
        if compact_value not in {_compact(name), *( _compact(a) for a in aliases)}:
            continue
        markers = (_compact(name), *( _compact(a) for a in aliases))
        return any(mark in quote_compact or mark in report_compact for mark in markers)
    return False


def _store_judgment(job, judgment):
    key = (judgment["claim_id"], judgment.get("url"), judgment.get("sentence_id"))
    job.judgments = [
        item
        for item in job.judgments
        if (item["claim_id"], item.get("url"), item.get("sentence_id")) != key
    ]
    job.judgments.append(judgment)


def _resolve_claim(claim, items):
    if not items:
        return "insufficient", {"claim_id": claim["id"], "kind": claim["kind"], "status": "unjudged", "statement": "这条主张还没有判断。"}
    if claim["kind"] == "value":
        return _resolve_values(claim, items)
    decisive = [item for item in items if item["status"] in {"supports", "contradicts"}]
    statuses = {item["status"] for item in decisive}
    if statuses == {"supports", "contradicts"}:
        return "insufficient", _with_model_notes(
            {
                "claim_id": claim["id"],
                "kind": claim["kind"],
                "status": "literature_inconsistent",
                "statement": "不同文献对这一主张的结论不一致，不能据此判断报告错误。",
                "items": items,
            },
            items,
        )
    if statuses == {"contradicts"}:
        return "confirmed_errors", _with_model_notes(
            {"claim_id": claim["id"], "kind": claim["kind"], "status": "contradicts", "statement": decisive[-1]["statement"], "items": decisive},
            decisive,
        )
    if statuses == {"supports"}:
        return "supported", _with_model_notes(
            {"claim_id": claim["id"], "kind": claim["kind"], "status": "supports", "statement": decisive[-1]["statement"], "items": decisive},
            decisive,
        )
    latest = items[-1]
    return "insufficient", _with_model_notes(
        {"claim_id": claim["id"], "kind": claim["kind"], "status": latest["status"], "statement": latest["statement"], "items": items},
        items,
    )


def _resolve_values(claim, items):
    comparable = [item for item in items if item["status"] in {"supports", "contradicts"}]
    if len(comparable) >= 2:
        bases = [item["reference_base"] for item in comparable]
        spread = (max(bases) - min(bases)) / max(abs(sum(bases) / len(bases)), 1e-12)
        allowed = max(item["tolerance"] for item in comparable)
        if spread > allowed:
            return "insufficient", _with_model_notes(
                {
                    "claim_id": claim["id"],
                    "kind": "value",
                    "status": "literature_inconsistent",
                    "statement": f"文献给出的{claim['quantity']}彼此不一致，不能据此判断报告错误。",
                    "items": items,
                },
                items,
            )
    statuses = {item["status"] for item in comparable}
    if statuses == {"contradicts"}:
        return "confirmed_errors", _with_model_notes(
            {"claim_id": claim["id"], "kind": "value", "status": "contradicts", "statement": comparable[-1]["statement"], "items": comparable},
            comparable,
        )
    if statuses == {"supports"}:
        return "supported", _with_model_notes(
            {"claim_id": claim["id"], "kind": "value", "status": "supports", "statement": comparable[-1]["statement"], "items": comparable},
            comparable,
        )
    if len(statuses) > 1:
        return "insufficient", _with_model_notes(
            {
                "claim_id": claim["id"],
                "kind": "value",
                "status": "literature_inconsistent",
                "statement": f"文献给出的{claim['quantity']}彼此不一致，不能据此判断报告错误。",
                "items": items,
            },
            items,
        )
    latest = items[-1]
    return "insufficient", _with_model_notes(
        {"claim_id": claim["id"], "kind": "value", "status": latest["status"], "statement": latest["statement"], "items": items},
        items,
    )


def _required_phrases(claim):
    if claim["kind"] == "method":
        return [claim["slot"]]
    if claim["kind"] == "value":
        return [claim["quantity"], claim["dosage"], claim["temperature"], claim["method"]]
    return []


def _find_claim(job, claim_id):
    if not isinstance(claim_id, str):
        return None
    return next((claim for claim in job.claims if claim["id"] == claim_id), None)


def _compact(text):
    return "".join(text.split()).casefold()


TOOLS = {
    "read_report": read_report,
    "record_report": record_report,
    "frame_experiment": frame_experiment,
    "propose_candidates": propose_candidates,
    "extract_claims": extract_claims,
    "extract_recommended_claims": extract_recommended_claims,
    "search_references": search_references,
    "search_solution_kinetics": search_solution_kinetics,
    "search_enzyme_kinetics": search_enzyme_kinetics,
    "retry_claim": retry_claim,
    "read_reference": read_reference,
    "select_evidence": select_evidence,
    "judge_claim": judge_claim,
    "finish_review": finish_review,
}

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "read_report",
            "description": "读取项目目录中的实验报告电子档，支持 txt、md、csv、docx、pdf。照片不要用这个工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment": {"type": "string", "description": "报告对应的实验名称"},
                    "path": {"type": "string", "description": "项目目录内的报告文件路径"},
                },
                "required": ["experiment", "path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_report",
            "description": "保存从照片或对话中读到的实验报告正文。判断前必须先有报告正文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment": {"type": "string", "description": "报告对应的实验名称"},
                    "text": {"type": "string", "description": "报告正文，保留原句"},
                },
                "required": ["experiment", "text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "frame_experiment",
            "description": "读完报告后、检索前必做。完整判断报告在讲什么（report_about）、要核实什么（what_to_verify）、需要哪些文献（literature_needs）。未调用本工具不得 search_*。不直接判错。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_candidates",
            "description": "程序扫描报告，枚举可核对的候选原句；并返回 recommended_claims（已填好的速率常数主张草稿）。有 recommended_claims 时优先用 extract_recommended_claims 或原样交给 extract_claims。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_recommended_claims",
            "description": "一键采纳 propose_candidates 返回的 recommended_claims（测得/文献速率常数短句）。表格 PDF 点选失败时优先调用本工具，不要空交 extract_claims。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_claims",
            "description": "从 propose_candidates 的候选句中点选主张。若刚拿到 recommended_claims，可原样提交；也可先调用 extract_recommended_claims。quote 必须落在候选句内。value 还要给 dosage、temperature、method。",
            "parameters": {
                "type": "object",
                "properties": {
                    "claims": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "kind": {"type": "string", "enum": ["method", "value", "calculation"]},
                                "quote": {"type": "string", "description": "候选句中的连续原句"},
                                "candidate_id": {"type": "string", "description": "propose_candidates 返回的候选编号"},
                                "slot": {"type": "string", "description": "方法主张里被核对的做法，必须出现在 quote 中"},
                                "quantity": {
                                    "type": "string",
                                    "description": "允许「速率常数」或「活化能」（都可）；须出现在 quote 中并紧邻数字。也可写 k、k(单位)、Ea",
                                },
                                "dosage": {"type": "string", "description": "用量或浓度，必须是 quote 中的短原文"},
                                "temperature": {"type": "string", "description": "温度条件，必须是 quote 中的短原文"},
                                "method": {"type": "string", "description": "测定方法，必须是 quote 中的短原文"},
                                "expression": {
                                    "type": "string",
                                    "description": "arrhenius、rate、dilution、stoichiometry，或只含报告原句中的数字和加减乘除括号",
                                },
                                "equation": {
                                    "type": "string",
                                    "description": "反应式，必须是 quote 中的连续原文。expression 为 rate 或 stoichiometry 时必填",
                                },
                                "reported": {
                                    "type": "string",
                                    "description": "报告写出的计算结果，必须是 quote 中的完整数字；dilution 为声明的工作浓度",
                                },
                            },
                            "required": ["id", "kind", "quote"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["claims"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_references",
            "description": "按一条主张检索公开网页，并优先合并 reference_cache。碱水解/皂化等教学类主张应优先本工具（用 frame.search_plan.queries），不要先撞 NIST。酶反应再用 search_enzyme_kinetics；羟基自由基类才优先 search_solution_kinetics。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "针对一条主张的检索词"},
                    "claim_id": {"type": "string", "description": "这条检索对应的主张编号"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_solution_kinetics",
            "description": "查询 NDRL/NIST 溶液动力学库。仅适合羟基自由基等研究向溶液动力学；碱水解/皂化教学类请改用 search_references（否则易命中自由基同名酯、不可比）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "reactant": {"type": "string", "description": "反应物名称、化学式或 CAS 号"},
                    "solvent": {"type": "string", "description": "溶剂，例如 water 或 H2O"},
                },
                "required": ["claim_id", "reactant"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_enzyme_kinetics",
            "description": "查询 SABIO-RK 酶反应动力学。substrate 写底物，enzyme 和 organism 可选。温度、缓冲液和 kcat 等参数来自数据库原文。用返回的 url 调用 select_evidence。测定方法没有出现在记录里时不可比。",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "substrate": {"type": "string", "description": "底物名称，例如 ethanol"},
                    "enzyme": {"type": "string", "description": "酶名称，例如 alcohol dehydrogenase"},
                    "organism": {"type": "string", "description": "物种名，例如 Saccharomyces cerevisiae"},
                },
                "required": ["claim_id", "substrate"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retry_claim",
            "description": "一条主张被判为不可比或证据不足时，程序用用量、温度和测定方法再检索一次公开网页。每条主张只能调用一次。已有判断保留。接着 read_reference、select_evidence、judge_claim，然后 finish_review。计算主张不要调用。",
            "parameters": {
                "type": "object",
                "properties": {"claim_id": {"type": "string"}},
                "required": ["claim_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_reference",
            "description": "打开检索结果中的公开页面；若 url 在 reference_cache/ 缓存中则直接读本地原文。按句切开并建立本次运行的内存向量。url 必须来自 search_references 或 retry_claim。数据库工具返回的记录已经带有原文，直接 select_evidence。",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "select_evidence",
            "description": "用主张对已打开页面做向量检索。先硬过滤同一反应、测定方法与温度，再排序；通不过的句子不进入可选集合。可用 focus。judge_claim 只能引用返回的 sentence_id。若无合格句则 abstain。",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "url": {"type": "string"},
                    "focus": {"type": "string", "description": "模型补充的检索焦点，例如同一测定方法或同一反应写法"},
                },
                "required": ["claim_id", "url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "judge_claim",
            "description": "判断一条溶液反应动力学主张。模型必须给出 verdict，并尽量写 explanation；若认为有错还要写 improvement。方法要给 literature_span。方法主张上，程序判为错误时若模型给 supports 或 not_enough，最终记为证据不足；模型不能单独把方法主张判错。数值主张的对错仍由程序按温度、测定方法和数字容差决定。dilution/stoichiometry/arrhenius/rate 由程序验算，不检索。电导法用量高于 0.20 mol/L 时条件不合理。",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["supports", "contradicts", "not_enough"]},
                    "url": {"type": "string", "description": "select_evidence 使用的页面"},
                    "sentence_id": {"type": "string", "description": "select_evidence 返回的句子编号"},
                    "literature_span": {"type": "string", "description": "文献句中要求的做法，必须是选中句子里的连续原文"},
                    "explanation": {"type": "string", "description": "模型对这次判断的简要说明，不编造原句外的内容"},
                    "improvement": {"type": "string", "description": "若认为报告有错，写可执行的改进建议"},
                },
                "required": ["claim_id", "verdict"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_review",
            "description": "汇总判断。须先做过 frame_experiment：summary 写清实验族理解→关系是否成立→证据结论。结果含 frame 摘要与 causal_notes。计量与数值同时出错时提示因果链。文献彼此不一致时不把报告判错。",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "模型对整份报告审查结果的概括与改进建议"},
                },
                "additionalProperties": False,
            },
        },
    },
]


def dispatch(job, name, arguments):
    handler = TOOLS.get(name)
    if handler is None:
        return {"ok": False, "error": "unknown_tool", "name": name}
    if not isinstance(arguments, dict):
        return {"ok": False, "error": "arguments_must_be_object"}
    return handler(job, arguments)
