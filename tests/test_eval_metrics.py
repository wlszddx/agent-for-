import unittest

from eval.metrics import (
    candidate_recall,
    claim_accuracy,
    confusion_matrix,
    false_conviction_rate,
    macro_f1,
    missed_error_rate,
    summarize,
)
from eval.run import GOLD_DEFAULT, evaluate, load_cases


class MetricsUnitTest(unittest.TestCase):
    def test_main_rates_on_a_fixed_confusion(self):
        pairs = [
            ("supports", "supports"),
            ("supports", "contradicts"),  # false conviction
            ("contradicts", "contradicts"),
            ("contradicts", "not_enough"),  # missed error
            ("not_enough", "not_enough"),
            ("not_comparable", "not_comparable"),
        ]
        self.assertAlmostEqual(claim_accuracy(pairs), 4 / 6)
        self.assertAlmostEqual(false_conviction_rate(pairs), 1 / 4)
        self.assertAlmostEqual(missed_error_rate(pairs), 1 / 2)
        matrix = confusion_matrix(pairs)
        self.assertEqual(matrix["supports"]["contradicts"], 1)
        self.assertEqual(matrix["contradicts"]["not_enough"], 1)
        summary = summarize(pairs)
        self.assertEqual(summary["n"], 6)
        self.assertGreater(summary["macro_f1"], 0.0)
        self.assertLessEqual(summary["macro_f1"], 1.0)

    def test_macro_f1_is_one_on_perfect_labels(self):
        pairs = [(label, label) for label in ("supports", "contradicts", "not_enough", "not_comparable")]
        self.assertEqual(claim_accuracy(pairs), 1.0)
        self.assertEqual(false_conviction_rate(pairs), 0.0)
        self.assertEqual(missed_error_rate(pairs), 0.0)
        self.assertEqual(macro_f1(pairs), 1.0)

    def test_candidate_recall_allows_substring_either_way(self):
        gold = ["在 0.10 mol/L、25摄氏度、电导法下测得活化能为 48.5 kJ/mol。"]
        proposed = ["前言。在 0.10 mol/L、25摄氏度、电导法下测得活化能为 48.5 kJ/mol。结语。"]
        self.assertEqual(candidate_recall(gold, proposed), 1.0)
        self.assertEqual(candidate_recall(gold, ["完全无关"]), 0.0)


class GoldEvalSmokeTest(unittest.TestCase):
    def test_bundled_gold_cases_match_labels(self):
        cases = load_cases(GOLD_DEFAULT)
        result = evaluate(cases)
        mismatches = [row for row in result["rows"] if row["gold"] != row["pred"]]
        self.assertFalse(mismatches, mismatches)
        self.assertEqual(result["summary"]["claim_accuracy"], 1.0)
        self.assertEqual(result["summary"]["false_conviction_rate"], 0.0)
        self.assertEqual(result["summary"]["missed_error_rate"], 0.0)
        self.assertIsNotNone(result["mean_candidate_recall"])


if __name__ == "__main__":
    unittest.main()
