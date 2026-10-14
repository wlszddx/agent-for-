"""Run claim-level gold eval without an online model."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.metrics import (  # noqa: E402
    STATUSES,
    candidate_recall,
    format_report,
    summarize,
)
from kinetics_audit.tools import Job, dispatch  # noqa: E402

GOLD_DIR = Path(__file__).resolve().parent / "gold"
GOLD_DEFAULT = GOLD_DIR / "cases.json"


def load_cases(path):
    gold_path = Path(path)
    payload = json.loads(gold_path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list) or not cases:
        raise ValueError("gold file must contain a non-empty cases list")
    base = gold_path.parent
    resolved = []
    for case in cases:
        item = dict(case)
        report_file = item.get("report_file")
        if report_file:
            text = (base / report_file).read_text(encoding="utf-8")
            item["report"] = text
        if not item.get("report"):
            raise ValueError(f"case {item.get('id')}: report or report_file required")
        resolved.append(item)
    return resolved


def _open_page(job, evidence, claim_id):
    url = evidence["url"]
    title = evidence.get("title") or url
    text = evidence["text"]
    query = evidence.get("query") or title
    hit = {"title": title, "url": url, "excerpt": text[:80]}
    with patch("kinetics_audit.tools.search_web", return_value=[hit]), patch(
        "kinetics_audit.tools.fetch_page", return_value=text
    ):
        found = dispatch(job, "search_references", {"query": query, "claim_id": claim_id})
        opened = dispatch(job, "read_reference", {"url": url})
    return found, opened


def _predicted_status(review, claim_id):
    for bucket in ("confirmed_errors", "supported", "insufficient"):
        for item in review.get(bucket) or []:
            if item.get("claim_id") == claim_id:
                status = item.get("status")
                if status in STATUSES:
                    return status
                if status in {"literature_inconsistent", "unjudged"}:
                    return "not_enough"
                return status
    return "not_enough"


def run_case(case):
    gold = case["gold_status"]
    if gold not in STATUSES:
        raise ValueError(f"case {case.get('id')}: invalid gold_status {gold!r}")

    job = Job.closed()
    experiment = case.get("experiment") or "溶液动力学"
    report = case["report"]
    claim = case["claim"]
    claim_id = claim["id"]

    recorded = dispatch(job, "record_report", {"experiment": experiment, "text": report})
    if not recorded.get("ok"):
        raise RuntimeError(f"{case['id']}: record_report failed: {recorded}")

    candidate_score = None
    gold_quotes = case.get("gold_quotes") or [claim.get("quote")]
    if case.get("measure_candidates", True):
        proposed = dispatch(job, "propose_candidates", {})
        quotes = [item.get("quote") or "" for item in proposed.get("candidates") or []]
        candidate_score = candidate_recall(gold_quotes, quotes)

    extracted = dispatch(job, "extract_claims", {"claims": [claim]})
    if not extracted.get("ok"):
        # Missing fields / rejected claim → treat as not_enough unless gold expects otherwise.
        review = {
            "insufficient": [
                {"claim_id": claim_id, "status": "not_enough", "statement": str(extracted)}
            ],
            "confirmed_errors": [],
            "supported": [],
        }
        return {
            "id": case["id"],
            "kind": case.get("kind") or claim.get("kind"),
            "gold": gold,
            "pred": "not_enough",
            "candidate_recall": candidate_score,
            "extract_ok": False,
            "detail": extracted,
        }

    evidence = case.get("evidence")
    if evidence:
        _open_page(job, evidence, claim_id)
        select_args = {"claim_id": claim_id, "url": evidence["url"]}
        select_args.update(case.get("select") or {})
        selected = dispatch(job, "select_evidence", select_args)
        expect_abstain = bool(case.get("expect_abstain"))
        if expect_abstain or selected.get("abstain"):
            finished = dispatch(job, "finish_review", {})
            pred = _predicted_status(finished["review"], claim_id)
            return {
                "id": case["id"],
                "kind": case.get("kind") or claim.get("kind"),
                "gold": gold,
                "pred": pred,
                "candidate_recall": candidate_score,
                "extract_ok": True,
                "abstain": True,
            }
        judge = dict(case.get("judge") or {})
        verdict = judge.pop("verdict", "supports")
        pick_contains = judge.pop("pick_contains", None)
        sentence_id = judge.pop("sentence_id", None)
        if sentence_id is None:
            sentences = selected.get("sentences") or []
            if pick_contains:
                match = next((s for s in sentences if pick_contains in s.get("text", "")), None)
                if match is None:
                    raise RuntimeError(f"{case['id']}: no sentence containing {pick_contains!r}")
                sentence_id = match["id"]
            elif sentences:
                sentence_id = sentences[0]["id"]
            else:
                raise RuntimeError(f"{case['id']}: select_evidence returned no sentences")
        judged = dispatch(
            job,
            "judge_claim",
            {"claim_id": claim_id, "verdict": verdict, "url": evidence["url"], "sentence_id": sentence_id, **judge},
        )
        if judged.get("ok") is False:
            raise RuntimeError(f"{case['id']}: judge_claim failed: {judged}")
    else:
        judge = dict(case.get("judge") or {})
        verdict = judge.pop("verdict", "supports")
        judged = dispatch(job, "judge_claim", {"claim_id": claim_id, "verdict": verdict, **judge})
        if judged.get("ok") is False:
            raise RuntimeError(f"{case['id']}: judge_claim failed: {judged}")

    finished = dispatch(job, "finish_review", {})
    pred = _predicted_status(finished["review"], claim_id)
    return {
        "id": case["id"],
        "kind": case.get("kind") or claim.get("kind"),
        "gold": gold,
        "pred": pred,
        "candidate_recall": candidate_score,
        "extract_ok": True,
        "abstain": False,
    }


def evaluate(cases):
    rows = [run_case(case) for case in cases]
    pairs = [(row["gold"], row["pred"]) for row in rows]
    summary = summarize(pairs)
    by_kind_pairs = defaultdict(list)
    for row in rows:
        by_kind_pairs[row["kind"] or "unknown"].append((row["gold"], row["pred"]))
    by_kind = {kind: summarize(items) for kind, items in by_kind_pairs.items()}
    recalls = [row["candidate_recall"] for row in rows if row.get("candidate_recall") is not None]
    mean_candidate_recall = sum(recalls) / len(recalls) if recalls else None
    return {
        "rows": rows,
        "summary": summary,
        "by_kind": by_kind,
        "mean_candidate_recall": mean_candidate_recall,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="eval-accuracy")
    parser.add_argument("--gold", default=str(GOLD_DEFAULT), help="path to gold cases JSON")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args(argv)
    cases = load_cases(args.gold)
    result = evaluate(cases)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result["summary"], result["by_kind"]))
        if result["mean_candidate_recall"] is not None:
            print(f"\nmean_candidate_recall={result['mean_candidate_recall']:.4f}")
        print("\ncases:")
        for row in result["rows"]:
            mark = "OK" if row["gold"] == row["pred"] else "MISS"
            print(f"  [{mark}] {row['id']}: gold={row['gold']} pred={row['pred']}")
    mismatches = sum(1 for row in result["rows"] if row["gold"] != row["pred"])
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
