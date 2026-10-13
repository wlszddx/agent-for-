import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape

from repro.databases import enzyme_record, solution_links, solution_record
from repro.guard import GuardError, check_source
from repro.numbers import measurements, number_tokens
from repro.report_file import extract_report, locate_report
from repro.sandbox import execute
from repro.search import useful_result
from repro.tools import Job, dispatch


def _report(job, text, experiment="皂化反应"):
    return dispatch(job, "record_report", {"experiment": experiment, "text": text})


def _open_page(job, url, title, text, claim_id, query):
    hit = {"title": title, "url": url, "excerpt": text[:80]}
    with patch("repro.tools.search_web", return_value=[hit]), patch("repro.tools.fetch_page", return_value=text):
        found = dispatch(job, "search_references", {"query": query, "claim_id": claim_id})
        opened = dispatch(job, "read_reference", {"url": url})
    return found, opened


def _kinetic(quote):
    return {
        "id": "v1",
        "kind": "value",
        "quote": quote,
        "quantity": "活化能",
        "dosage": "0.10 mol/L",
        "temperature": "25摄氏度",
        "method": "电导法",
    }


class HarnessTest(unittest.TestCase):
    def test_method_error_requires_the_same_slot(self):
        job = Job.closed()
        report = "本实验直接用摄氏温度拟合速率常数。"
        _report(job, report)
        extracted = dispatch(
            job,
            "extract_claims",
            {"claims": [{"id": "m1", "kind": "method", "quote": report, "slot": "摄氏温度"}]},
        )
        self.assertTrue(extracted["ok"])
        page = "实验使用玻璃烧杯装样品。拟合必须使用热力学温度，不能把摄氏温度直接代入。"
        found, opened = _open_page(job, "https://example.test/arrhenius", "阿伦尼乌斯公式", page, "m1", "Arrhenius 温度")
        self.assertTrue(found["ok"])
        self.assertGreaterEqual(opened["sentence_count"], 2)
        selected = dispatch(job, "select_evidence", {"claim_id": "m1", "url": "https://example.test/arrhenius"})
        self.assertTrue(selected["ok"])
        self.assertIn("热力学温度", selected["sentences"][0]["text"])
        blocked = dispatch(
            job,
            "judge_claim",
            {"claim_id": "m1", "verdict": "contradicts", "url": "https://example.test/arrhenius", "sentence_id": "s9"},
        )
        self.assertEqual(blocked["error"], "evidence_required")
        glass = next(item for item in selected["sentences"] if "玻璃" in item["text"])
        weak = dispatch(
            job,
            "judge_claim",
            {
                "claim_id": "m1",
                "verdict": "contradicts",
                "url": "https://example.test/arrhenius",
                "sentence_id": glass["id"],
                "literature_span": "热力学温度",
            },
        )
        self.assertEqual(weak["judgment"]["status"], "not_enough")
        relevant = next(item for item in selected["sentences"] if "热力学温度" in item["text"])
        judged = dispatch(
            job,
            "judge_claim",
            {
                "claim_id": "m1",
                "verdict": "contradicts",
                "url": "https://example.test/arrhenius",
                "sentence_id": relevant["id"],
                "literature_span": "热力学温度",
            },
        )
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        self.assertIn(report, judged["judgment"]["statement"])
        self.assertIn("摄氏温度直接代入", judged["judgment"]["statement"])
        review = dispatch(job, "finish_review", {})
        self.assertEqual(review["review"]["confirmed_errors"][0]["claim_id"], "m1")
        self.assertFalse(review["review"]["insufficient"])

    def test_unrelated_method_wording_is_not_a_report_error(self):
        job = Job.closed()
        report = "做法：在 5、10、15、20 min 用电导法测定电导并回归速率常数。"
        _report(job, report)
        dispatch(job, "extract_claims", {"claims": [{"id": "m1", "kind": "method", "quote": report, "slot": "电导法"}]})
        page = "NDRL/NIST 溶液动力学库记录。反应 ·OH + CH3CO2C2H5。Experimental method: Pulse radiolysis。Analytical technique: Vis-UV absorption。"
        _open_page(job, "https://example.test/radical", "自由基", page, "m1", "ethyl acetate")
        selected = dispatch(job, "select_evidence", {"claim_id": "m1", "url": "https://example.test/radical"})
        judged = dispatch(
            job,
            "judge_claim",
            {
                "claim_id": "m1",
                "verdict": "contradicts",
                "url": "https://example.test/radical",
                "sentence_id": selected["sentences"][0]["id"],
                "literature_span": "Pulse radiolysis",
            },
        )
        self.assertEqual(judged["judgment"]["status"], "not_enough")
        review = dispatch(job, "finish_review", {})
        self.assertFalse(review["review"]["confirmed_errors"])
        self.assertEqual(review["review"]["insufficient"][0]["status"], "not_enough")

    def test_conflicting_method_sources_do_not_convict_the_report(self):
        job = Job.closed()
        report = "本实验直接用摄氏温度拟合速率常数。"
        _report(job, report)
        dispatch(job, "extract_claims", {"claims": [{"id": "m1", "kind": "method", "quote": report, "slot": "摄氏温度"}]})
        page = "拟合必须使用热力学温度，不能把摄氏温度直接代入。记录和拟合都可以直接使用摄氏温度。"
        _open_page(job, "https://example.test/mixed", "温度", page, "m1", "摄氏温度 拟合")
        selected = dispatch(job, "select_evidence", {"claim_id": "m1", "url": "https://example.test/mixed"})
        for item in selected["sentences"]:
            span = "热力学温度" if "热力学温度" in item["text"] else "摄氏温度"
            dispatch(
                job,
                "judge_claim",
                {
                    "claim_id": "m1",
                    "verdict": "contradicts",
                    "url": "https://example.test/mixed",
                    "sentence_id": item["id"],
                    "literature_span": span,
                },
            )
        review = dispatch(job, "finish_review", {})
        self.assertFalse(review["review"]["confirmed_errors"])
        self.assertEqual(review["review"]["insufficient"][0]["status"], "literature_inconsistent")

    def test_values_use_program_pairing_and_conditions(self):
        report = "在 0.10 mol/L、25摄氏度、电导法下测得活化能为 30 kJ/mol。"
        evidence = "0.10 mol/L、25摄氏度、电导法下皂化反应活化能约为 48.5 kJ/mol。"
        job = Job.closed()
        _report(job, report)
        self.assertTrue(dispatch(job, "extract_claims", {"claims": [_kinetic(report)]})["ok"])
        self.assertEqual(number_tokens("测得活化能为 300 kJ/mol。"), ["300"])
        _open_page(job, "https://example.test/ea", "乙酸乙酯皂化", evidence, "v1", "皂化 活化能")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/ea"})
        judged = dispatch(
            job,
            "judge_claim",
            {"claim_id": "v1", "verdict": "supports", "url": "https://example.test/ea", "sentence_id": selected["sentences"][0]["id"]},
        )
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        self.assertEqual(judged["judgment"]["reported"], "30")
        self.assertEqual(judged["judgment"]["reference"], "48.5")
        close = Job.closed()
        close_report = "在 0.10 mol/L、25摄氏度、电导法下测得活化能为 40 kJ/mol。"
        _report(close, close_report)
        dispatch(close, "extract_claims", {"claims": [_kinetic(close_report)]})
        _open_page(close, "https://example.test/ea", "乙酸乙酯皂化", evidence, "v1", "皂化 活化能")
        picked = dispatch(close, "select_evidence", {"claim_id": "v1", "url": "https://example.test/ea"})
        widened = dispatch(
            close,
            "judge_claim",
            {"claim_id": "v1", "verdict": "contradicts", "url": "https://example.test/ea", "sentence_id": picked["sentences"][0]["id"]},
        )
        self.assertEqual(widened["judgment"]["status"], "supports")
        bare = Job.closed()
        _report(bare, report)
        dispatch(bare, "extract_claims", {"claims": [_kinetic(report)]})
        _open_page(bare, "https://example.test/ea", "乙酸乙酯皂化", "皂化反应活化能约为 48.5 kJ/mol。", "v1", "活化能")
        picked = dispatch(bare, "select_evidence", {"claim_id": "v1", "url": "https://example.test/ea"})
        skipped = dispatch(
            bare,
            "judge_claim",
            {"claim_id": "v1", "verdict": "contradicts", "url": "https://example.test/ea", "sentence_id": picked["sentences"][0]["id"]},
        )
        self.assertEqual(skipped["judgment"]["status"], "not_comparable")

    def test_rate_constant_with_a_different_dosage_is_not_comparable(self):
        report = "在 0.10 mol/L、25摄氏度、电导法下测得速率常数为 0.020 s^-1。"
        evidence = "在 0.02 mol/L、25摄氏度、电导法下速率常数为 0.001 s^-1。"
        job = Job.closed()
        _report(job, report)
        claim = _kinetic(report)
        claim["quantity"] = "速率常数"
        self.assertTrue(dispatch(job, "extract_claims", {"claims": [claim]})["ok"])
        _open_page(job, "https://example.test/rate", "速率", evidence, "v1", "速率常数")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/rate"})
        judged = dispatch(
            job,
            "judge_claim",
            {"claim_id": "v1", "verdict": "contradicts", "url": "https://example.test/rate", "sentence_id": selected["sentences"][0]["id"]},
        )
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        self.assertIn("不随初始用量改变", judged["judgment"]["statement"])

    def test_conductivity_above_the_dilute_limit_is_an_unreasonable_step(self):
        report = "在 0.50 mol/L、25摄氏度、电导法下测得速率常数为 0.020 s^-1。"
        evidence = "在 0.50 mol/L、25摄氏度、电导法下速率常数为 0.020 s^-1。"
        job = Job.closed()
        _report(job, report)
        claim = _kinetic(report)
        claim["quantity"] = "速率常数"
        claim["dosage"] = "0.50 mol/L"
        dispatch(job, "extract_claims", {"claims": [claim]})
        _open_page(job, "https://example.test/dense", "电导", evidence, "v1", "电导")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/dense"})
        judged = dispatch(
            job,
            "judge_claim",
            {"claim_id": "v1", "verdict": "supports", "url": "https://example.test/dense", "sentence_id": selected["sentences"][0]["id"]},
        )
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        self.assertEqual(judged["judgment"]["reason"], "setup")
        review = dispatch(job, "finish_review", {})
        self.assertEqual(review["review"]["confirmed_errors"][0]["claim_id"], "v1")

    def test_matching_conditions_compare_the_number_even_when_the_wording_differs(self):
        report = "在 0.0101 mol/L、25℃、电导法下测得速率常数为 5.193 L/(mol·min)。"
        evidence = "At 25 °C and 0.01 mol/L, the conductivity method gives k = 6.43 L/(mol·min)."
        job = Job.closed()
        _report(job, report)
        claim = _kinetic(report)
        claim["quantity"] = "速率常数"
        claim["dosage"] = "0.0101 mol/L"
        claim["temperature"] = "25℃"
        self.assertTrue(dispatch(job, "extract_claims", {"claims": [claim]})["ok"])
        _open_page(job, "https://example.test/cond", "电导", evidence, "v1", "saponification")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/cond"})
        judged = dispatch(
            job,
            "judge_claim",
            {"claim_id": "v1", "verdict": "supports", "url": "https://example.test/cond", "sentence_id": selected["sentences"][0]["id"]},
        )
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        hotter = "At 35 °C and 0.01 mol/L, the conductivity method gives k = 6.43 L/(mol·min)."
        other = Job.closed()
        _report(other, report)
        dispatch(other, "extract_claims", {"claims": [claim]})
        _open_page(other, "https://example.test/hot", "电导", hotter, "v1", "saponification")
        picked = dispatch(other, "select_evidence", {"claim_id": "v1", "url": "https://example.test/hot"})
        skipped = dispatch(
            other,
            "judge_claim",
            {"claim_id": "v1", "verdict": "contradicts", "url": "https://example.test/hot", "sentence_id": picked["sentences"][0]["id"]},
        )
        self.assertEqual(skipped["judgment"]["status"], "not_comparable")
        radical = "At 25 °C and 0.01 mol/L, Experimental method: Pulse radiolysis, k = 4.0E8 L/(mol·s)."
        third = Job.closed()
        _report(third, report)
        dispatch(third, "extract_claims", {"claims": [claim]})
        _open_page(third, "https://example.test/pulse", "辐解", radical, "v1", "ethyl acetate")
        picked = dispatch(third, "select_evidence", {"claim_id": "v1", "url": "https://example.test/pulse"})
        blocked = dispatch(
            third,
            "judge_claim",
            {"claim_id": "v1", "verdict": "contradicts", "url": "https://example.test/pulse", "sentence_id": picked["sentences"][0]["id"]},
        )
        self.assertEqual(blocked["judgment"]["status"], "not_comparable")

    def test_a_different_reaction_is_not_compared(self):
        report = "乙酸乙酯皂化。在 0.0101 mol/L、25℃、电导法下测得速率常数为 5.193 L/(mol·min)。"
        evidence = "At 25 °C the conductivity method for ·OH + ethyl acetate gives k = 4.0E8 L/(mol·s)."
        job = Job.closed()
        _report(job, report, "乙酸乙酯皂化")
        claim = _kinetic(report)
        claim["quantity"] = "速率常数"
        claim["dosage"] = "0.0101 mol/L"
        claim["temperature"] = "25℃"
        dispatch(job, "extract_claims", {"claims": [claim]})
        _open_page(job, "https://example.test/radical-k", "自由基", evidence, "v1", "ethyl acetate")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/radical-k"})
        judged = dispatch(
            job,
            "judge_claim",
            {"claim_id": "v1", "verdict": "contradicts", "url": "https://example.test/radical-k", "sentence_id": selected["sentences"][0]["id"]},
        )
        self.assertEqual(judged["judgment"]["status"], "not_comparable")
        self.assertEqual(judged["judgment"]["reason"], "reaction")

    def test_dictionary_pages_are_not_search_results(self):
        self.assertFalse(useful_result("速率_百度百科", "https://baike.baidu.com/item/%E9%80%9F%E7%8E%87/1181335"))
        self.assertFalse(useful_result("ethyl", "https://global.bing.com/dict/search?q=ethyl"))
        self.assertTrue(useful_result("乙酸乙酯皂化反应速率常数", "https://etcps.fudan.edu.cn/images/report.pdf"))

    def test_activation_energy_can_use_an_independence_statement(self):
        report = "在 0.10 mol/L、25摄氏度、电导法下测得活化能为 30 kJ/mol。"
        evidence = "该反应活化能与用量无关，约为 48.5 kJ/mol。"
        job = Job.closed()
        _report(job, report)
        dispatch(job, "extract_claims", {"claims": [_kinetic(report)]})
        _open_page(job, "https://example.test/free", "活化能", evidence, "v1", "活化能 用量")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/free"})
        judged = dispatch(
            job,
            "judge_claim",
            {"claim_id": "v1", "verdict": "supports", "url": "https://example.test/free", "sentence_id": selected["sentences"][0]["id"]},
        )
        self.assertEqual(judged["judgment"]["status"], "contradicts")

    def test_arrhenius_is_recomputed_from_the_report(self):
        report = "25摄氏度时速率常数为 0.001 s^-1，35摄氏度时速率常数为 0.002 s^-1，活化能为 10 kJ/mol。"
        job = Job.closed()
        _report(job, report)
        extracted = dispatch(
            job,
            "extract_claims",
            {"claims": [{"id": "c1", "kind": "calculation", "quote": report, "expression": "arrhenius", "reported": "10"}]},
        )
        self.assertTrue(extracted["ok"])
        judged = dispatch(job, "judge_claim", {"claim_id": "c1", "verdict": "supports"})
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        self.assertGreater(judged["judgment"]["computed"], 40)

    def test_rate_is_computed_from_the_equation_and_the_report(self):
        equation = "CH3COOC2H5 + NaOH → CH3COONa + C2H5OH"
        report = f"反应式 {equation}。0.0100 mol/L 下速率常数为 6.00 L/(mol·min)，速率为 0.000600 mol/(L·min)。"
        job = Job.closed()
        _report(job, report)
        extracted = dispatch(
            job,
            "extract_claims",
            {"claims": [{"id": "c1", "kind": "calculation", "quote": report, "expression": "rate", "equation": equation, "reported": "0.000600"}]},
        )
        self.assertTrue(extracted["ok"], extracted)
        judged = dispatch(job, "judge_claim", {"claim_id": "c1", "verdict": "supports"})
        self.assertEqual(judged["judgment"]["status"], "supports")
        wrong = f"反应式 {equation}。0.0100 mol/L 下速率常数为 6.00 L/(mol·min)，速率为 0.006000 mol/(L·min)。"
        other = Job.closed()
        _report(other, wrong)
        dispatch(
            other,
            "extract_claims",
            {"claims": [{"id": "c1", "kind": "calculation", "quote": wrong, "expression": "rate", "equation": equation, "reported": "0.006000"}]},
        )
        contradicted = dispatch(other, "judge_claim", {"claim_id": "c1", "verdict": "supports"})
        self.assertEqual(contradicted["judgment"]["status"], "contradicts")

    def test_disagreeing_literature_values_are_not_report_errors(self):
        report = "在 0.10 mol/L、25摄氏度、电导法下测得活化能为 30 kJ/mol。"
        job = Job.closed()
        _report(job, report)
        dispatch(job, "extract_claims", {"claims": [_kinetic(report)]})
        pages = {
            "https://example.test/low": "0.10 mol/L、25摄氏度、电导法下活化能为 48.5 kJ/mol。",
            "https://example.test/high": "0.10 mol/L、25摄氏度、电导法下活化能为 80 kJ/mol。",
        }
        hits = [{"title": url, "url": url, "excerpt": text} for url, text in pages.items()]
        with patch("repro.tools.search_web", return_value=hits), patch("repro.tools.fetch_page", side_effect=lambda url: pages[url]):
            dispatch(job, "search_references", {"query": "皂化 活化能", "claim_id": "v1"})
            for url in pages:
                dispatch(job, "read_reference", {"url": url})
                selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": url})
                dispatch(
                    job,
                    "judge_claim",
                    {"claim_id": "v1", "verdict": "contradicts", "url": url, "sentence_id": selected["sentences"][0]["id"]},
                )
        review = dispatch(job, "finish_review", {})
        self.assertFalse(review["review"]["confirmed_errors"])
        self.assertEqual(review["review"]["insufficient"][0]["status"], "literature_inconsistent")

    def test_calculation_uses_only_numbers_from_the_report(self):
        job = Job.closed()
        report = "2 与 3 相加得到 6。"
        _report(job, report)
        rejected = dispatch(
            job,
            "extract_claims",
            {"claims": [{"id": "c1", "kind": "calculation", "quote": report, "expression": "2+9", "reported": "6"}]},
        )
        self.assertEqual(rejected["rejected"][0]["error"], "number_not_in_quote")
        extracted = dispatch(
            job,
            "extract_claims",
            {"claims": [{"id": "c1", "kind": "calculation", "quote": report, "expression": "2+3", "reported": "6"}]},
        )
        self.assertTrue(extracted["ok"])
        blocked = dispatch(job, "select_evidence", {"claim_id": "c1", "url": "https://example.test/calc"})
        self.assertEqual(blocked["error"], "calculation_skips_search")
        judged = dispatch(job, "judge_claim", {"claim_id": "c1", "verdict": "supports"})
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        self.assertAlmostEqual(judged["judgment"]["computed"], 5.0)
        review = dispatch(job, "finish_review", {})
        self.assertEqual(review["review"]["confirmed_errors"][0]["kind"], "calculation")

    def test_solution_database_record_keeps_measured_fields(self):
        page = (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "nist_solution_detail.html").read_text(encoding="utf-8")
        text = solution_record(page)
        self.assertIn("3.2E10", text)
        self.assertIn("Pulse radiolysis", text)
        self.assertIn("H2O", text)
        self.assertIn("Baxendale", text)
        links = solution_links('<a href="Detail?id=1965BAX/FIE207-216B:1">x</a>')
        self.assertEqual(links, ["https://kinetics.nist.gov/solution/Detail?id=1965BAX/FIE207-216B:1"])

    def test_enzyme_database_record_keeps_temperature_and_kcat(self):
        record = enzyme_record(
            {
                "id": 4505,
                "reaction": {"equation": "NAD+ + Ethanol = NADH + Acetaldehyde + H+"},
                "enzyme_description": {"enzyme_name": "alcohol dehydrogenase"},
                "general": {"organism": {"name": "Kluyveromyces lactis"}},
                "experimental_conditions": {
                    "buffer": "50 mM Tris-HCl",
                    "envvar_ph": {"start_value": 8},
                    "envvar_temperature": {"start_value": 25, "unit": "°C"},
                },
                "kineticlaw": {
                    "parameter": [
                        {
                            "name": "kcat",
                            "role": "Constant",
                            "parameter_type": {"name": "kcat"},
                            "start_value": 24500,
                            "unit": {"name": "min^(-1)"},
                        }
                    ]
                },
                "publication": {"author": "Brisdelli F", "journal": "Biochimie", "year": 2004, "title": "Kinetic properties"},
            }
        )
        self.assertIn("kcat 24500 min^(-1)", record["text"])
        self.assertIn("温度 25 °C", record["text"])
        self.assertIn("4505", record["url"])

    def test_database_record_enters_the_same_judgment(self):
        report = "在 0.10 mol/L、25摄氏度、电导法下测得速率常数为 0.020 s^-1。"
        evidence = "在 0.10 mol/L、25摄氏度、电导法下速率常数为 0.001 s^-1。"
        job = Job.closed()
        _report(job, report)
        claim = _kinetic(report)
        claim["quantity"] = "速率常数"
        dispatch(job, "extract_claims", {"claims": [claim]})
        with patch(
            "repro.tools.search_solution",
            return_value=[{"title": "OH", "url": "https://kinetics.nist.gov/solution/Detail?id=test", "text": evidence}],
        ):
            found = dispatch(job, "search_solution_kinetics", {"claim_id": "v1", "reactant": "OH", "solvent": "water"})
        self.assertTrue(found["ok"])
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": found["results"][0]["url"]})
        judged = dispatch(
            job,
            "judge_claim",
            {
                "claim_id": "v1",
                "verdict": "supports",
                "url": found["results"][0]["url"],
                "sentence_id": selected["sentences"][0]["id"],
            },
        )
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        blocked = dispatch(job, "search_solution_kinetics", {"claim_id": "v1", "reactant": "<script>"})
        self.assertEqual(blocked["error"], "query_required")

    def test_retry_searches_the_missing_conditions_once(self):
        report = "在 0.10 mol/L、25摄氏度、电导法下测得速率常数为 0.020 s^-1。"
        weak = "皂化反应速率常数约为 0.001 s^-1。"
        strong = "在 0.10 mol/L、25摄氏度、电导法下速率常数为 0.001 s^-1。"
        job = Job.closed()
        _report(job, report)
        claim = _kinetic(report)
        claim["quantity"] = "速率常数"
        dispatch(job, "extract_claims", {"claims": [claim]})
        _open_page(job, "https://example.test/weak", "速率", weak, "v1", "速率常数")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/weak"})
        first = dispatch(
            job,
            "judge_claim",
            {"claim_id": "v1", "verdict": "contradicts", "url": "https://example.test/weak", "sentence_id": selected["sentences"][0]["id"]},
        )
        self.assertEqual(first["judgment"]["status"], "not_comparable")
        limited = dispatch(job, "search_references", {"query": "速率常数 0.10 mol/L", "claim_id": "v1"})
        self.assertEqual(limited["error"], "search_limit")
        hit = {"title": "条件一致", "url": "https://example.test/strong", "excerpt": strong}
        with patch("repro.tools.search_web", return_value=[hit]), patch("repro.tools.fetch_page", return_value=strong):
            retried = dispatch(job, "retry_claim", {"claim_id": "v1"})
            self.assertTrue(retried["ok"])
            self.assertIn("0.10 mol/L", retried["query"])
            self.assertIn("25摄氏度", retried["query"])
            self.assertIn("电导法", retried["query"])
            dispatch(job, "read_reference", {"url": "https://example.test/strong"})
        picked = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/strong"})
        second = dispatch(
            job,
            "judge_claim",
            {
                "claim_id": "v1",
                "verdict": "supports",
                "url": "https://example.test/strong",
                "sentence_id": picked["sentences"][0]["id"],
            },
        )
        self.assertEqual(second["judgment"]["status"], "contradicts")
        self.assertEqual(dispatch(job, "retry_claim", {"claim_id": "v1"})["error"], "retry_exhausted")
        review = dispatch(job, "finish_review", {})
        self.assertEqual(review["review"]["confirmed_errors"][0]["claim_id"], "v1")

    def test_retry_does_not_run_after_a_decisive_judgment(self):
        job = Job.closed()
        report = "2 与 3 相加得到 6。"
        _report(job, report)
        dispatch(
            job,
            "extract_claims",
            {"claims": [{"id": "c1", "kind": "calculation", "quote": report, "expression": "2+3", "reported": "6"}]},
        )
        dispatch(job, "judge_claim", {"claim_id": "c1", "verdict": "supports"})
        self.assertEqual(dispatch(job, "retry_claim", {"claim_id": "c1"})["error"], "calculation_skips_search")

    def test_number_token_does_not_match_inside_longer_number(self):
        found = measurements("测得活化能为 300 kJ/mol。")
        self.assertEqual([item["number"] for item in found], ["300"])

    def test_report_documents_are_read_and_photos_are_not(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = root / "report.docx"
            paragraph = "拟合时把摄氏温度换算成开尔文。"
            xml = (
                "<?xml version='1.0' encoding='UTF-8'?>"
                "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
                f"<w:p><w:r><w:t>{escape(paragraph)}</w:t></w:r></w:p></w:document>"
            )
            with zipfile.ZipFile(document, "w") as archive:
                archive.writestr("word/document.xml", xml)
            self.assertIn("开尔文", extract_report(document))
            photo = root / "page.png"
            photo.write_bytes(b"\x89PNG\r\n")
            with self.assertRaises(ValueError) as raised:
                extract_report(photo)
            self.assertEqual(str(raised.exception), "image")
            secret = root.parent / "secret.txt"
            secret.write_text("hidden", encoding="utf-8")
            try:
                with self.assertRaises(ValueError):
                    locate_report(secret, root)
            finally:
                secret.unlink()
        project_photo = Path(__file__).resolve().parents[1] / "page.png"
        project_photo.write_bytes(b"\x89PNG\r\n")
        try:
            seen = dispatch(Job.closed(), "read_report", {"experiment": "皂化反应", "path": "page.png"})
        finally:
            project_photo.unlink()
        self.assertEqual(seen["error"], "image_use_session_image")

    def test_guard_blocks_import(self):
        with self.assertRaises(GuardError):
            check_source("import os\ndef run(data_path, out_dir):\n    pass\n")

    def test_sandbox_blocks_parent_read(self):
        source = "def run(data_path, out_dir):\n    open('../outside.txt', encoding='utf-8').read()\n"
        result = execute(source, [{"run_id": 1, "value": 1}])
        self.assertNotEqual(result["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
