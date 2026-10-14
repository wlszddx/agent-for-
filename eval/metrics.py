"""Claim-level accuracy metrics for kinetics report audit."""

from __future__ import annotations

STATUSES = ("supports", "contradicts", "not_enough", "not_comparable")


def confusion_matrix(pairs):
    """pairs: iterable of (gold_status, predicted_status)."""
    matrix = {gold: {pred: 0 for pred in STATUSES} for gold in STATUSES}
    for gold, pred in pairs:
        if gold not in matrix or pred not in matrix[gold]:
            continue
        matrix[gold][pred] += 1
    return matrix


def claim_accuracy(pairs):
    pairs = list(pairs)
    if not pairs:
        return 0.0
    return sum(1 for gold, pred in pairs if gold == pred) / len(pairs)


def _prf(tp, fp, fn):
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def per_status_scores(pairs):
    pairs = list(pairs)
    scores = {}
    for label in STATUSES:
        tp = sum(1 for gold, pred in pairs if gold == label and pred == label)
        fp = sum(1 for gold, pred in pairs if gold != label and pred == label)
        fn = sum(1 for gold, pred in pairs if gold == label and pred != label)
        scores[label] = _prf(tp, fp, fn)
    return scores


def macro_f1(pairs):
    scores = per_status_scores(pairs)
    return sum(item["f1"] for item in scores.values()) / len(STATUSES)


def false_conviction_rate(pairs):
    """Gold is not an error, but system predicted contradicts."""
    safe = [(gold, pred) for gold, pred in pairs if gold != "contradicts"]
    if not safe:
        return 0.0
    return sum(1 for _gold, pred in safe if pred == "contradicts") / len(safe)


def missed_error_rate(pairs):
    """Gold is contradicts, but system did not predict contradicts."""
    errors = [(gold, pred) for gold, pred in pairs if gold == "contradicts"]
    if not errors:
        return 0.0
    return sum(1 for _gold, pred in errors if pred != "contradicts") / len(errors)


def candidate_recall(gold_quotes, proposed_quotes):
    """Fraction of gold quotes covered by proposed candidate quotes (substring either way)."""
    gold_quotes = [q for q in gold_quotes if isinstance(q, str) and q.strip()]
    if not gold_quotes:
        return 1.0
    proposed = [q for q in proposed_quotes if isinstance(q, str) and q.strip()]
    hit = 0
    for gold in gold_quotes:
        g = "".join(gold.split())
        if any(g in "".join(p.split()) or "".join(p.split()) in g for p in proposed):
            hit += 1
    return hit / len(gold_quotes)


def summarize(pairs):
    pairs = list(pairs)
    scores = per_status_scores(pairs)
    return {
        "n": len(pairs),
        "claim_accuracy": claim_accuracy(pairs),
        "macro_f1": macro_f1(pairs),
        "false_conviction_rate": false_conviction_rate(pairs),
        "missed_error_rate": missed_error_rate(pairs),
        "per_status": scores,
        "confusion": confusion_matrix(pairs),
    }


def format_report(summary, by_kind=None):
    lines = [
        f"n={summary['n']}",
        f"claim_accuracy={summary['claim_accuracy']:.4f}",
        f"false_conviction_rate={summary['false_conviction_rate']:.4f}",
        f"missed_error_rate={summary['missed_error_rate']:.4f}",
        f"macro_f1={summary['macro_f1']:.4f}",
        "",
        "confusion (rows=gold, cols=pred):",
        "gold\\pred\t" + "\t".join(STATUSES),
    ]
    for gold in STATUSES:
        row = summary["confusion"][gold]
        lines.append(gold + "\t" + "\t".join(str(row[pred]) for pred in STATUSES))
    lines.append("")
    lines.append("per-status F1:")
    for label in STATUSES:
        item = summary["per_status"][label]
        lines.append(
            f"  {label}: P={item['precision']:.4f} R={item['recall']:.4f} F1={item['f1']:.4f}"
        )
    if by_kind:
        lines.append("")
        lines.append("by kind:")
        for kind, sub in sorted(by_kind.items()):
            lines.append(
                f"  {kind}: n={sub['n']} acc={sub['claim_accuracy']:.4f} "
                f"FCR={sub['false_conviction_rate']:.4f} "
                f"MER={sub['missed_error_rate']:.4f} "
                f"macroF1={sub['macro_f1']:.4f}"
            )
    return "\n".join(lines)
